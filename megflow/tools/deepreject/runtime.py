# -*- coding: utf-8 -*-
"""Standalone DeepReject predictor for other Python files."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .accelerated import OnnxRuntimeBackend, OpenVINOBackend, is_intel_cpu
from .postprocess import artifact_probs_to_bad_intervals, predictions_to_bad_intervals
from .preprocessing import build_export_inputs, load_single_fif_record


DEFAULT_EXPORT_DIR = Path(__file__).resolve().parent / "models" / "litev6"


@dataclass
class DeepRejectPrediction:
    artifact_logits: np.ndarray
    artifact_probs: np.ndarray
    artifact_pred: np.ndarray
    bad_channel_logits: Optional[np.ndarray]
    bad_channel_probs: Optional[np.ndarray]
    bad_channel_pred: Optional[np.ndarray]
    bad_intervals: List[Tuple[float, float]]
    backend: str
    ch_names: Optional[List[str]] = None


class DeepRejectPredictor:
    """
    Reusable DeepReject inference wrapper.

    Backend selection:
    - backend="auto" + CUDA device: ONNX Runtime CUDA.
    - backend="auto" + Intel/x86 CPU: OpenVINO CPU.
    - backend="auto" otherwise: ONNX Runtime CPU.
    - Missing, unvalidated, or shape-incompatible exported models raise a clear error.
    """

    def __init__(
        self,
        device: str = "cpu",
        backend: str = "auto",
        export_dir: Path = DEFAULT_EXPORT_DIR,
        batch_size: int = 32,
        encoder_chunk_size: Optional[int] = None,
        artifact_prob_threshold: Optional[float] = None,
        bad_channel_prob_threshold: Optional[float] = None,
        artifact_hysteresis_high_threshold: Optional[float] = None,
        artifact_hysteresis_low_threshold: Optional[float] = None,
        artifact_merge_gap_sec: float = 0.0,
        artifact_min_duration_sec: float = 0.0,
        artifact_short_keep_threshold: Optional[float] = None,
    ):
        self.export_dir = Path(export_dir)
        self.metadata_path = self.export_dir / "metadata.json"
        self.metadata = self._load_metadata()
        self.window_duration_sec = float(self.metadata.get("window_duration_sec") or 1.0)
        self.batch_size = int(batch_size)
        self.device = str(device)
        self.backend_request = str(backend).lower()
        self.artifact_prob_threshold = artifact_prob_threshold
        self.bad_channel_prob_threshold = bad_channel_prob_threshold
        self.artifact_hysteresis_high_threshold = artifact_hysteresis_high_threshold
        self.artifact_hysteresis_low_threshold = artifact_hysteresis_low_threshold
        self.artifact_merge_gap_sec = float(artifact_merge_gap_sec)
        self.artifact_min_duration_sec = float(artifact_min_duration_sec)
        self.artifact_short_keep_threshold = artifact_short_keep_threshold

        self.accelerated_backend = self._init_accelerated_backend()

    def _load_metadata(self) -> Dict[str, Any]:
        if not self.metadata_path.exists():
            return {}
        with self.metadata_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _init_accelerated_backend(self):
        metadata_path = self.export_dir / "metadata.json"
        onnx_path = self.export_dir / "model.onnx"
        ov_path = self.export_dir / "openvino" / "model.xml"
        req = self.backend_request
        device_l = self.device.lower()
        use_cuda = device_l.startswith("cuda") or device_l == "gpu"
        if req in {"torch", "pytorch"}:
            raise ValueError("standalone runtime 不提供 Torch 后端；请使用导出的 ONNX/OpenVINO 后端。")

        candidates: List[Tuple[str, bool]] = []
        if req in {"onnx", "onnxruntime"}:
            candidates = [("onnx", use_cuda)]
        elif req in {"openvino", "ov"}:
            candidates = [("openvino", False)]
        elif req == "auto":
            if use_cuda:
                candidates = [("onnx", True), ("onnx", False)]
            elif is_intel_cpu():
                candidates = [("openvino", False), ("onnx", False)]
            else:
                candidates = [("onnx", False)]
        else:
            raise ValueError(f"未知 backend={self.backend_request!r}，应为 auto|onnx|openvino")

        errors: List[str] = []
        for kind, cuda_flag in candidates:
            if kind == "onnx":
                if not (onnx_path.exists() and metadata_path.exists()):
                    errors.append(f"缺少 ONNX 导出物: {onnx_path} 或 {metadata_path}")
                    continue
                try:
                    backend = OnnxRuntimeBackend(onnx_path, metadata_path, use_cuda=cuda_flag)
                    if backend.is_validated():
                        return backend
                    errors.append("ONNX Runtime 导出模型尚未通过数值一致性验证")
                except Exception as exc:
                    errors.append(f"ONNX Runtime 初始化失败: {exc}")
            elif kind == "openvino":
                if not (ov_path.exists() and metadata_path.exists()):
                    errors.append(f"缺少 OpenVINO 导出物: {ov_path} 或 {metadata_path}")
                    continue
                try:
                    backend = OpenVINOBackend(ov_path, metadata_path, device_name="CPU")
                    if backend.is_validated():
                        return backend
                    errors.append("OpenVINO 导出模型尚未通过数值一致性验证")
                except Exception as exc:
                    errors.append(f"OpenVINO 初始化失败: {exc}")
        raise RuntimeError("没有可用的已验证导出后端: " + " | ".join(errors))

    def predict_inputs(self, inputs: Dict[str, Any]) -> DeepRejectPrediction:
        try:
            art_logits, bad_logits, art_probs, bad_probs = self.accelerated_backend.predict_inputs(inputs)
        except Exception as exc:
            raise RuntimeError(f"{self.accelerated_backend.name} 推理失败: {exc}") from exc
        return self._postprocess(art_logits, bad_logits, art_probs, bad_probs, self.accelerated_backend.name)

    def predict_data_list(self, data_list: Sequence[Any]) -> DeepRejectPrediction:
        raise RuntimeError(
            "standalone runtime 不接收 PyG Data list；请使用 predict_fif(...) 或 predict_inputs(...)。"
        )

    def predict_fif(
        self,
        fif_path: Path,
        *,
        annot_root: Optional[Path] = None,
        category: Optional[str] = None,
        dataset: Optional[str] = None,
        meg_scale_mag: float = 1e15,
        meg_scale_grad: float = 1e13,
        pick_exclude_marked_bads: bool = False,
        edge_k: int = 6,
    ) -> DeepRejectPrediction:
        record = load_single_fif_record(
            Path(fif_path),
            annot_root,
            category,
            dataset,
            meg_scale_mag,
            meg_scale_grad,
            self.window_duration_sec,
            pick_exclude_marked_bads=pick_exclude_marked_bads,
        )
        inputs = build_export_inputs(record, edge_k=edge_k)
        pred = self.predict_inputs(inputs)
        pred.ch_names = list(record.get("ch_names") or [])
        return pred

    def _postprocess(
        self,
        art_logits: np.ndarray,
        bad_logits: Optional[np.ndarray],
        art_probs: np.ndarray,
        bad_probs: Optional[np.ndarray],
        backend_name: str,
    ) -> DeepRejectPrediction:
        if self.artifact_prob_threshold is None:
            artifact_pred = np.asarray(art_logits).argmax(axis=1).astype(np.int64)
        else:
            artifact_pred = (art_probs >= float(self.artifact_prob_threshold)).astype(np.int64)

        bad_pred = None
        if bad_probs is not None:
            if self.bad_channel_prob_threshold is None:
                assert bad_logits is not None
                bad_pred = np.asarray(bad_logits).argmax(axis=1).astype(np.int64)
            else:
                bad_pred = (bad_probs >= float(self.bad_channel_prob_threshold)).astype(np.int64)

        if (
            self.artifact_hysteresis_high_threshold is not None
            or self.artifact_hysteresis_low_threshold is not None
            or self.artifact_merge_gap_sec > 0
            or self.artifact_min_duration_sec > 0
        ):
            intervals = artifact_probs_to_bad_intervals(
                art_probs,
                duration_sec=self.window_duration_sec,
                threshold=self.artifact_prob_threshold,
                hysteresis_high=self.artifact_hysteresis_high_threshold,
                hysteresis_low=self.artifact_hysteresis_low_threshold,
                merge_gap_sec=self.artifact_merge_gap_sec,
                min_duration_sec=self.artifact_min_duration_sec,
                short_keep_threshold=self.artifact_short_keep_threshold,
            )
        else:
            intervals = predictions_to_bad_intervals(
                artifact_pred,
                duration_sec=self.window_duration_sec,
            )

        return DeepRejectPrediction(
            artifact_logits=np.asarray(art_logits, dtype=np.float32),
            artifact_probs=np.asarray(art_probs, dtype=np.float32),
            artifact_pred=artifact_pred,
            bad_channel_logits=None if bad_logits is None else np.asarray(bad_logits, dtype=np.float32),
            bad_channel_probs=None if bad_probs is None else np.asarray(bad_probs, dtype=np.float32),
            bad_channel_pred=bad_pred,
            bad_intervals=intervals,
            backend=backend_name,
        )
