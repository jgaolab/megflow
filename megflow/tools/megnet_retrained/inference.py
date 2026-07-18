from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Sequence, Tuple

import numpy as np

from .runtime.preprocessing import (
    load_component_sources,
    prepare_clean_topomap_images,
    temporal_window_plan,
)


PACKAGE_ROOT = Path(__file__).resolve().parent
MODEL_FILE = PACKAGE_ROOT / "model.onnx"
CLASS_NAMES = ("brain_or_other", "heart_beat", "eye_blink", "eye_movement")
DISPLAY_NAMES = ("Brain/other", "ECG", "EOG blink", "EOG saccade")
EPOCH_SAMPLES = 15000
OVERLAP_SAMPLES = 3750
MAX_TEMPORAL_WINDOWS = 128


@dataclass(frozen=True)
class PredictionResult:
    probabilities: np.ndarray
    labels: Tuple[str, ...]
    original_sfreq: float
    effective_sfreq: float
    metadata: Dict[str, Any]

    @property
    def artifact_indices(self) -> list[int]:
        return [
            index
            for index, label in enumerate(self.labels)
            if label != "brain_or_other"
        ]

    def indices_for(self, *class_names: str) -> list[int]:
        selected = set(class_names)
        return [
            index
            for index, label in enumerate(self.labels)
            if label in selected
        ]


def canonical_labels(probabilities: np.ndarray) -> list[str]:
    probabilities = np.asarray(probabilities)
    if probabilities.ndim != 2 or probabilities.shape[1] != len(CLASS_NAMES):
        raise ValueError(
            "MEGNet probabilities must have four class columns in canonical order"
        )
    if not np.isfinite(probabilities).all():
        raise ValueError("MEGNet probabilities contain non-finite values")
    return [CLASS_NAMES[index] for index in probabilities.argmax(axis=1).tolist()]


def default_cpu_threads() -> int:
    try:
        count = len(os.sched_getaffinity(0))
    except AttributeError:
        count = os.cpu_count() or 1
    return max(1, min(int(count), 16))


def _load_onnxruntime():
    import onnxruntime

    return onnxruntime


def resolve_providers(device: str, *, ort_module=None):
    ort_module = ort_module or _load_onnxruntime()
    available = set(ort_module.get_available_providers())
    value = str(device).strip().lower()
    if value == "auto":
        value = "cpu"
    if value == "cpu":
        if "CPUExecutionProvider" not in available:
            raise RuntimeError("ONNX Runtime CPUExecutionProvider is unavailable")
        return ["CPUExecutionProvider"], "cpu"
    if value == "cuda" or value.startswith("cuda:"):
        if "CUDAExecutionProvider" not in available:
            raise RuntimeError(
                "CUDA was requested, but ONNX Runtime CUDAExecutionProvider is "
                "unavailable. Install onnxruntime-gpu or use device=cpu."
            )
        device_id = int(value.split(":", maxsplit=1)[1]) if ":" in value else 0
        providers = [
            (
                "CUDAExecutionProvider",
                {
                    "device_id": device_id,
                    "use_tf32": 0,
                    "cudnn_conv_algo_search": "DEFAULT",
                },
            ),
            "CPUExecutionProvider",
        ]
        return providers, f"cuda:{device_id}"
    raise ValueError(f"Unsupported device value: {device!r}")


def create_session(
    model_file: Path,
    *,
    device: str,
    intra_op_threads: int,
):
    ort = _load_onnxruntime()
    providers, resolved_device = resolve_providers(device, ort_module=ort)
    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    if int(intra_op_threads) > 0:
        options.intra_op_num_threads = int(intra_op_threads)
    session = ort.InferenceSession(
        str(model_file),
        sess_options=options,
        providers=providers,
    )
    active_provider = session.get_providers()[0]
    if resolved_device.startswith("cuda") and active_provider != "CUDAExecutionProvider":
        raise RuntimeError(
            f"CUDA provider was requested but active provider is {active_provider}"
        )
    expected_inputs = {"signal", "topomap_rgb", "epoch_weight"}
    actual_inputs = {item.name for item in session.get_inputs()}
    if actual_inputs != expected_inputs:
        raise RuntimeError(
            f"Unexpected ONNX inputs: expected {sorted(expected_inputs)}, "
            f"got {sorted(actual_inputs)}"
        )
    return session, resolved_device, str(ort.__version__)


def build_signal_batch(
    signals: np.ndarray,
    component_indices: Sequence[int],
    starts: Sequence[int],
) -> np.ndarray:
    components = []
    for component_idx in component_indices:
        windows = [
            signals[int(component_idx), int(start) : int(start) + EPOCH_SAMPLES]
            for start in starts
        ]
        components.append(np.stack(windows, axis=0))
    return np.ascontiguousarray(np.stack(components, axis=0), dtype=np.float32)


def predict_onnx(
    session,
    signals: np.ndarray,
    topomap_images: np.ndarray,
    starts: Sequence[int],
    window_weights: np.ndarray,
    *,
    requested_batch_size: int,
    max_flat_windows: int,
) -> tuple[np.ndarray, int]:
    n_components = int(signals.shape[0])
    num_windows = len(starts)
    memory_safe_batch = max(1, int(max_flat_windows) // num_windows)
    batch_size = min(int(requested_batch_size), memory_safe_batch)
    probabilities = np.zeros((n_components, len(CLASS_NAMES)), dtype=np.float32)
    for begin in range(0, n_components, batch_size):
        end = min(begin + batch_size, n_components)
        indices = list(range(begin, end))
        signal = build_signal_batch(signals, indices, starts)
        topomap = np.ascontiguousarray(topomap_images[indices], dtype=np.float32)
        weight = np.broadcast_to(
            np.asarray(window_weights, dtype=np.float32)[None, :],
            (len(indices), num_windows),
        ).copy()
        output = session.run(
            ["component_probabilities"],
            {"signal": signal, "topomap_rgb": topomap, "epoch_weight": weight},
        )[0]
        probabilities[begin:end] = output
    return probabilities, batch_size


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def predict_components(
    raw,
    ica,
    *,
    ica_sources_file: Path | None = None,
    model_file: Path | None = None,
    device: str = "cpu",
    batch_size: int = 8,
    max_flat_windows: int = 128,
    intra_op_threads: int | None = None,
    ch_type: str = "auto",
    save_topomaps_dir: Path | None = None,
) -> PredictionResult:
    if int(batch_size) <= 0 or int(max_flat_windows) <= 0:
        raise ValueError("batch_size and max_flat_windows must be positive")

    model_path = Path(model_file or MODEL_FILE).expanduser().resolve()
    if not model_path.is_file():
        raise FileNotFoundError(model_path)
    if ica_sources_file is not None:
        ica_sources_file = Path(ica_sources_file)
    if save_topomaps_dir is not None:
        save_topomaps_dir = Path(save_topomaps_dir)

    started = time.perf_counter()
    preprocessing_started = time.perf_counter()
    sources = load_component_sources(
        raw,
        ica,
        ica_sources_file=ica_sources_file,
        target_sfreq=250.0,
    )
    n_components = int(ica.n_components_)
    if sources.data.shape[0] != n_components:
        raise RuntimeError("Internal component-count mismatch after source loading")
    topomap_images, _ = prepare_clean_topomap_images(
        ica,
        n_components=n_components,
        ch_type=str(ch_type),
        render_res=128,
        save_dir=save_topomaps_dir,
    )
    starts, window_weights = temporal_window_plan(
        sources.n_times,
        epoch_samples=EPOCH_SAMPLES,
        overlap_samples=OVERLAP_SAMPLES,
        max_epochs=MAX_TEMPORAL_WINDOWS,
    )
    preprocessing_seconds = time.perf_counter() - preprocessing_started

    session_started = time.perf_counter()
    session, resolved_device, onnxruntime_version = create_session(
        model_path,
        device=str(device),
        intra_op_threads=(
            default_cpu_threads() if intra_op_threads is None else int(intra_op_threads)
        ),
    )
    session_initialization_seconds = time.perf_counter() - session_started

    inference_started = time.perf_counter()
    probabilities, effective_batch_size = predict_onnx(
        session,
        sources.data,
        topomap_images,
        starts,
        window_weights,
        requested_batch_size=int(batch_size),
        max_flat_windows=int(max_flat_windows),
    )
    model_inference_seconds = time.perf_counter() - inference_started
    labels = tuple(canonical_labels(probabilities))
    class_counts = {
        class_name: labels.count(class_name) for class_name in CLASS_NAMES
    }
    metadata: Dict[str, Any] = {
        "source_mode": sources.source_mode,
        "source_file": sources.source_file,
        "source_samples": sources.n_times,
        "raw_first_samp": sources.raw_first_samp,
        "source_first_samp": sources.source_first_samp,
        "source_time_origin_reset": (
            sources.source_first_samp != sources.raw_first_samp
        ),
        "original_sfreq_hz": sources.original_sfreq,
        "effective_sfreq_hz": sources.sfreq,
        "num_temporal_windows": len(starts),
        "model_file": str(model_path),
        "model_sha256": sha256_file(model_path),
        "backend": "onnxruntime",
        "onnxruntime_version": onnxruntime_version,
        "requested_device": str(device),
        "resolved_device": resolved_device,
        "active_providers": list(session.get_providers()),
        "requested_batch_size": int(batch_size),
        "effective_batch_size": effective_batch_size,
        "max_flat_windows": int(max_flat_windows),
        "class_order": list(CLASS_NAMES),
        "class_counts": class_counts,
        "session_initialization_seconds": session_initialization_seconds,
        "preprocessing_seconds": preprocessing_seconds,
        "model_inference_seconds": model_inference_seconds,
        "elapsed_seconds": time.perf_counter() - started,
    }
    return PredictionResult(
        probabilities=probabilities,
        labels=labels,
        original_sfreq=sources.original_sfreq,
        effective_sfreq=sources.sfreq,
        metadata=metadata,
    )
