# -*- coding: utf-8 -*-
"""Torch-only DeepReject predictor for other Python files."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch

from .config import DEFAULT_CKPT, DEFAULT_MODEL_CONFIG, load_model_config, window_duration_from_config
from .postprocess import artifact_probs_to_bad_intervals, predictions_to_bad_intervals
from .preprocessing import build_torch_data_list, load_single_fif_record
from .torch_backend import load_torch_model, predict_data_list_torch


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
    """Reusable Torch DeepReject inference wrapper."""

    def __init__(
        self,
        device: str = "cpu",
        backend: str = "torch",
        ckpt_path: Path = DEFAULT_CKPT,
        model_config_path: Path = DEFAULT_MODEL_CONFIG,
        batch_size: int = 0,
        encoder_chunk_size: Optional[int] = None,
        artifact_prob_threshold: Optional[float] = None,
        bad_channel_prob_threshold: Optional[float] = None,
        artifact_hysteresis_high_threshold: Optional[float] = None,
        artifact_hysteresis_low_threshold: Optional[float] = None,
        artifact_merge_gap_sec: float = 0.0,
        artifact_min_duration_sec: float = 0.0,
        artifact_short_keep_threshold: Optional[float] = None,
    ):
        backend_l = str(backend).lower()
        if backend_l not in {"torch", "pytorch", "auto"}:
            raise ValueError("当前 runtime 已切换为 Torch-only；backend 仅支持 torch/auto。")
        self.backend_request = "torch"
        self.device = torch.device("cuda" if str(device).lower() == "gpu" else str(device))
        self.ckpt_path = Path(ckpt_path)
        self.model_config_path = Path(model_config_path)
        self.model_config = load_model_config(self.model_config_path)
        self.window_duration_sec = window_duration_from_config(self.model_config, fallback=2.0)
        self.batch_size = int(batch_size)
        self.artifact_prob_threshold = artifact_prob_threshold
        self.bad_channel_prob_threshold = bad_channel_prob_threshold
        self.artifact_hysteresis_high_threshold = artifact_hysteresis_high_threshold
        self.artifact_hysteresis_low_threshold = artifact_hysteresis_low_threshold
        self.artifact_merge_gap_sec = float(artifact_merge_gap_sec)
        self.artifact_min_duration_sec = float(artifact_min_duration_sec)
        self.artifact_short_keep_threshold = artifact_short_keep_threshold
        self.model = load_torch_model(
            self.ckpt_path,
            self.model_config_path,
            device=self.device,
            encoder_chunk_size=encoder_chunk_size,
        )

    def predict_inputs(self, inputs: Dict[str, Any]) -> DeepRejectPrediction:
        raise RuntimeError("Torch-only runtime 不接收导出输入字典；请使用 predict_fif(...) 或 predict_data_list(...)。")

    def predict_data_list(self, data_list: Sequence[Any]) -> DeepRejectPrediction:
        art_logits, bad_logits, art_probs, bad_probs = predict_data_list_torch(
            self.model,
            list(data_list),
            device=self.device,
            batch_size=self.batch_size,
        )
        return self._postprocess(art_logits, bad_logits, art_probs, bad_probs, "torch")

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
        data_list = build_torch_data_list(record, edge_k=edge_k)
        pred = self.predict_data_list(data_list)
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
