# -*- coding: utf-8 -*-
"""Self-contained FIF loading and graph construction for DeepReject inference."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np


BAD_CHANNEL_SUFFIXES = ("_bad_chn.txt",)


def meg_stem_for_annot(meg_path: Path) -> str:
    name = Path(meg_path).name
    if name.endswith("_preprocessed.fif"):
        return name[: -len("_preprocessed.fif")]
    if name.endswith(".fif"):
        return name[:-4]
    return Path(name).stem


def resolve_bad_channels_path(
    meg_path: Path,
    annot_root: Optional[Path] = None,
    category: Optional[str] = None,
    dataset: Optional[str] = None,
) -> Optional[Path]:
    if annot_root is not None and category is not None and dataset is not None:
        base_dir = Path(annot_root) / str(category) / str(dataset)
        stem = meg_stem_for_annot(Path(meg_path))
    else:
        base_dir = Path(meg_path).parent
        stem = Path(meg_path).stem
    for suffix in BAD_CHANNEL_SUFFIXES:
        path = base_dir / f"{stem}{suffix}"
        if path.exists():
            return path
    return None


def load_bad_channel_names_from_txt(path: Path) -> List[str]:
    names: List[str] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")] if "," in line else [line]
            names.extend([p for p in parts if p])
    return names


def get_channel_positions_3d(raw: Any) -> np.ndarray:
    import mne

    picks = mne.pick_types(raw.info, meg=True, eeg=False, ref_meg=False, exclude=[])
    pos = []
    for idx in picks:
        loc = raw.info["chs"][idx]["loc"]
        xyz = np.asarray(loc[:3], dtype=np.float32)
        if not np.all(np.isfinite(xyz)):
            xyz = np.zeros(3, dtype=np.float32)
        pos.append(xyz)
    if not pos:
        raise RuntimeError("未找到 MEG 通道位置")
    return np.vstack(pos).astype(np.float32)


def meg_amplitude_scale_per_channel(raw: Any, meg_scale_mag: float, meg_scale_grad: float) -> np.ndarray:
    import mne

    picks = mne.pick_types(raw.info, meg=True, eeg=False, ref_meg=False, exclude=[])
    scales: List[float] = []
    for idx in picks:
        ch_type = mne.channel_type(raw.info, int(idx))
        if ch_type == "mag":
            scales.append(float(meg_scale_mag))
        elif ch_type == "grad":
            scales.append(float(meg_scale_grad))
        else:
            scales.append(float(meg_scale_mag))
    return np.asarray(scales, dtype=np.float64)


def build_edge_index_knn(pos: np.ndarray, k: int = 6) -> np.ndarray:
    try:
        from sklearn.neighbors import NearestNeighbors
    except ImportError as exc:
        raise RuntimeError("build_edge_index_knn 需要 scikit-learn") from exc

    pos = np.asarray(pos, dtype=np.float32)
    n = int(pos.shape[0])
    if n <= 1:
        return np.zeros((2, 0), dtype=np.int64)
    k_eff = min(int(k) + 1, n)
    nbrs = NearestNeighbors(n_neighbors=k_eff, algorithm="auto", metric="euclidean").fit(pos)
    indices = nbrs.kneighbors(pos, return_distance=False)[:, 1:]
    rows = np.repeat(np.arange(n), indices.shape[1])
    cols = indices.reshape(-1)
    edge_index = np.stack([rows, cols], axis=0)
    edge_index = np.hstack([edge_index, edge_index[[1, 0], :]])
    edge_index = np.unique(edge_index, axis=1)
    return edge_index.astype(np.int64)


def _load_recording_epochs_from_raw(
    raw: Any,
    *,
    bad_name_set: Set[str],
    duration_sec: float,
    meg_scale_mag: float,
    meg_scale_grad: float,
    pick_exclude_marked_bads: bool,
) -> Tuple[List[np.ndarray], np.ndarray, float, np.ndarray, np.ndarray, np.ndarray, List[str], np.ndarray]:
    import mne

    if duration_sec <= 0:
        raise ValueError("duration_sec must be > 0")
    picks = mne.pick_types(raw.info, meg=True, eeg=False, ref_meg=False, exclude=[])
    if len(picks) == 0:
        raise RuntimeError("fif 中未找到 MEG 通道")

    ch_names = [raw.ch_names[int(i)] for i in picks]
    y_bad_channel = np.asarray([1 if nm in bad_name_set else 0 for nm in ch_names], dtype=np.int64)
    if pick_exclude_marked_bads:
        mask_names = set(bad_name_set)
    else:
        mask_names = set()
    node_valid = np.asarray([0 if nm in mask_names else 1 for nm in ch_names], dtype=np.int64)
    channel_pos = get_channel_positions_3d(raw)
    x_raw_channel_scale = meg_amplitude_scale_per_channel(raw, meg_scale_mag, meg_scale_grad)

    sfreq = float(raw.info["sfreq"])
    n_samples_per_window = int(round(float(duration_sec) * sfreq))
    if n_samples_per_window <= 0:
        raise ValueError("duration_sec 太小，窗口采样点数为 0")
    data = raw.get_data(picks=picks, reject_by_annotation="omit")
    n_windows = int(data.shape[1] // n_samples_per_window)
    window_signals: List[np.ndarray] = []
    for i in range(n_windows):
        s = i * n_samples_per_window
        e = s + n_samples_per_window
        window_signals.append(data[:, s:e].astype(np.float32, copy=True))
    window_labels = np.zeros(n_windows, dtype=np.int64)
    return (
        window_signals,
        window_labels,
        sfreq,
        channel_pos,
        x_raw_channel_scale,
        y_bad_channel,
        ch_names,
        node_valid,
    )


def load_single_fif_record(
    fif_path: Path,
    annot_root: Optional[Path],
    category: Optional[str],
    dataset: Optional[str],
    meg_scale_mag: float,
    meg_scale_grad: float,
    window_duration_sec: float,
    pick_exclude_marked_bads: bool = False,
) -> Dict[str, Any]:
    import mne

    fif_path = Path(fif_path)
    bad_chn = None
    if pick_exclude_marked_bads:
        bad_chn = resolve_bad_channels_path(fif_path, annot_root, category, dataset)
    raw = mne.io.read_raw_fif(fif_path, preload=True, verbose=False)
    bad_name_set: Set[str] = set()
    if bad_chn is not None and bad_chn.exists():
        bad_name_set = {n for n in load_bad_channel_names_from_txt(bad_chn) if n in raw.ch_names}
    (
        window_signals,
        _,
        sfreq,
        channel_pos,
        x_raw_channel_scale,
        y_bad_channel,
        ch_names,
        node_valid,
    ) = _load_recording_epochs_from_raw(
        raw,
        bad_name_set=bad_name_set,
        duration_sec=window_duration_sec,
        meg_scale_mag=meg_scale_mag,
        meg_scale_grad=meg_scale_grad,
        pick_exclude_marked_bads=pick_exclude_marked_bads,
    )
    n_win = len(window_signals)
    if n_win == 0:
        raise RuntimeError(f"fif 未得到任何窗口: {fif_path}")
    return {
        "meg_path": fif_path,
        "window_signals": window_signals,
        "window_labels": np.zeros(n_win, dtype=np.int64),
        "sfreq": sfreq,
        "channel_pos": channel_pos,
        "x_raw_channel_scale": x_raw_channel_scale,
        "y_bad_channel": y_bad_channel,
        "ch_names": ch_names,
        "node_valid": node_valid,
        "dataset": str(dataset) if dataset else "single",
        "category": str(category) if category else "single",
        "pre_pick_auto_bad_channel_names": [],
    }


def _channel_pos_to_xyz3(channel_pos: np.ndarray, n_channels: int) -> np.ndarray:
    cp = np.asarray(channel_pos, dtype=np.float32).reshape(n_channels, -1)
    if cp.shape[1] >= 3:
        return cp[:, :3].copy()
    out = np.zeros((n_channels, 3), dtype=np.float32)
    out[:, : cp.shape[1]] = cp
    return out


def build_export_inputs(record: Dict[str, Any], edge_k: int = 6) -> Dict[str, np.ndarray]:
    """Build fixed-shape tensor inputs expected by exported ONNX/OpenVINO models."""
    window_signals = [np.asarray(x, dtype=np.float32) for x in record["window_signals"]]
    if not window_signals:
        raise ValueError("record 中没有 window_signals")
    n_windows = len(window_signals)
    n_channels, n_times = window_signals[0].shape
    for idx, sig in enumerate(window_signals):
        if tuple(sig.shape) != (n_channels, n_times):
            raise ValueError(f"window {idx} shape {tuple(sig.shape)} 与首窗 {(n_channels, n_times)} 不一致")

    x_raw = np.concatenate(window_signals, axis=0).astype(np.float32)
    base_edge = build_edge_index_knn(np.asarray(record["channel_pos"], dtype=np.float32), k=int(edge_k))
    edges = []
    for win_idx in range(n_windows):
        offset = win_idx * n_channels
        edges.append(base_edge + offset)
    edge_index = np.concatenate(edges, axis=1).astype(np.int64) if edges else np.zeros((2, 0), dtype=np.int64)
    batch_idx = np.repeat(np.arange(n_windows, dtype=np.int64), n_channels)
    ptr = (np.arange(n_windows + 1, dtype=np.int64) * n_channels).astype(np.int64)

    scale = np.asarray(record["x_raw_channel_scale"], dtype=np.float32).reshape(-1)
    if scale.shape[0] != n_channels:
        raise ValueError("x_raw_channel_scale 与通道数不一致")
    x_raw_scale = np.tile(scale, n_windows).astype(np.float32)

    node_valid_base = np.asarray(record.get("node_valid", np.ones(n_channels)), dtype=np.float32).reshape(-1)
    if node_valid_base.shape[0] != n_channels:
        raise ValueError("node_valid 与通道数不一致")
    node_valid = np.tile(node_valid_base, n_windows).astype(np.float32)

    sensor_type_base = np.where(scale >= 1e14, 1, 2).astype(np.int64)
    sensor_type = np.tile(sensor_type_base, n_windows).astype(np.int64)
    pos3 = _channel_pos_to_xyz3(np.asarray(record["channel_pos"], dtype=np.float32), n_channels)
    meg_ch_pos = np.tile(pos3, (n_windows, 1)).astype(np.float32)

    return {
        "x_raw": np.nan_to_num(x_raw, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32),
        "edge_index": edge_index,
        "batch_idx": batch_idx,
        "ptr": ptr,
        "x_raw_scale": x_raw_scale,
        "node_valid": node_valid,
        "sensor_type": sensor_type,
        "meg_ch_pos": meg_ch_pos,
    }
