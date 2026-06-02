# -*- coding: utf-8 -*-
"""Optional ONNX Runtime / OpenVINO backends for exported fixed-shape models."""
from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

EXPORT_INPUT_NAMES = [
    "x_raw",
    "edge_index",
    "batch_idx",
    "ptr",
    "x_raw_scale",
    "node_valid",
    "sensor_type",
    "meg_ch_pos",
]


def _to_numpy_inputs(inputs: Dict[str, Any]) -> Dict[str, np.ndarray]:
    out: Dict[str, np.ndarray] = {}
    for key, value in inputs.items():
        if hasattr(value, "detach") and hasattr(value, "cpu"):
            out[key] = value.detach().cpu().numpy()
        else:
            out[key] = np.asarray(value)
    return out


def _softmax_class1(logits: np.ndarray) -> np.ndarray:
    x = np.asarray(logits, dtype=np.float32)
    x = x - np.max(x, axis=-1, keepdims=True)
    exp = np.exp(x)
    probs = exp / np.sum(exp, axis=-1, keepdims=True)
    return probs[..., 1].astype(np.float32)


def _logits_to_probs(
    art_logits: np.ndarray,
    bad_logits: Optional[np.ndarray],
) -> Tuple[np.ndarray, Optional[np.ndarray], np.ndarray, Optional[np.ndarray]]:
    art_logits_np = np.asarray(art_logits, dtype=np.float32)
    art_probs = _softmax_class1(art_logits_np)
    bad_probs = None
    bad_np = None
    if bad_logits is not None and np.asarray(bad_logits).size > 0:
        bad_np = np.asarray(bad_logits, dtype=np.float32)
        bad_probs = _softmax_class1(bad_np)
    return art_logits_np, bad_np, art_probs, bad_probs


def is_intel_cpu() -> bool:
    text = " ".join(
        [
            platform.processor() or "",
            platform.machine() or "",
            platform.platform() or "",
        ]
    ).lower()
    if "intel" in text or "x86_64" in text or "amd64" in text:
        return True
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        try:
            content = cpuinfo.read_text(errors="ignore").lower()
            return "intel" in content or "genuineintel" in content
        except OSError:
            return False
    return False


class ExportedBackend:
    name = "exported"

    def __init__(self, model_path: Path, metadata_path: Path):
        self.model_path = Path(model_path)
        self.metadata_path = Path(metadata_path)
        with self.metadata_path.open("r", encoding="utf-8") as f:
            self.metadata = json.load(f)
        self.input_signature = self.metadata.get("input_signature", {})
        self.export_input_names = list(self.metadata.get("input_names", EXPORT_INPUT_NAMES))
        self.validation = self.metadata.get("validation", {})

    def is_validated(self) -> bool:
        info = self.validation.get(self.name, {})
        return bool(info.get("safe_to_use", False))

    def supports(self, inputs: Dict[str, Any]) -> bool:
        np_inputs = _to_numpy_inputs(inputs)
        for name, spec in self.input_signature.items():
            if name not in np_inputs:
                return False
            value = np_inputs[name]
            if list(spec.get("shape", [])) != list(value.shape):
                return False
            if str(spec.get("dtype", "")) != str(value.dtype):
                return False
        return True

    def _check_supports(self, inputs: Dict[str, Any]) -> None:
        if not self.supports(inputs):
            raise ValueError(f"{self.name} 导出模型输入形状与当前 recording 不一致，请重新导出该形状。")

    def predict_inputs(self, inputs: Dict[str, Any]):
        raise NotImplementedError


class OnnxRuntimeBackend(ExportedBackend):
    name = "onnxruntime"

    def __init__(self, model_path: Path, metadata_path: Path, *, use_cuda: bool = False):
        super().__init__(model_path, metadata_path)
        import onnxruntime as ort

        providers = ["CPUExecutionProvider"]
        if use_cuda:
            available = set(ort.get_available_providers())
            if "CUDAExecutionProvider" in available:
                providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self.session = ort.InferenceSession(str(self.model_path), providers=providers)
        self.providers = self.session.get_providers()
        self.input_names = [inp.name for inp in self.session.get_inputs()]

    def predict_inputs(self, inputs: Dict[str, Any]):
        self._check_supports(inputs)
        np_inputs = _to_numpy_inputs(inputs)
        feed = {name: np_inputs[name] for name in self.input_names if name in np_inputs}
        outputs = self.session.run(None, feed)
        art_logits = outputs[0]
        bad_logits = outputs[1] if len(outputs) > 1 else None
        return _logits_to_probs(art_logits, bad_logits)


class OpenVINOBackend(ExportedBackend):
    name = "openvino"

    def __init__(self, model_path: Path, metadata_path: Path, *, device_name: str = "CPU"):
        super().__init__(model_path, metadata_path)
        import openvino as ov

        core = ov.Core()
        self.compiled = core.compile_model(str(self.model_path), device_name)
        self.input_names = [inp.get_any_name() for inp in self.compiled.inputs]
        self.output_names = [out.get_any_name() for out in self.compiled.outputs]

    def predict_inputs(self, inputs: Dict[str, Any]):
        self._check_supports(inputs)
        np_inputs = _to_numpy_inputs(inputs)
        feed = {
            port: np_inputs[name]
            for port, name in zip(self.compiled.inputs, self.export_input_names)
            if name in np_inputs
        }
        result = self.compiled(feed)
        values = [result[out] for out in self.compiled.outputs]
        art_logits = values[0]
        bad_logits = values[1] if len(values) > 1 else None
        return _logits_to_probs(art_logits, bad_logits)
