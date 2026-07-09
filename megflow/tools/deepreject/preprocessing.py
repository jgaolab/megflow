# -*- coding: utf-8 -*-
"""Self-contained FIF loading and input construction for MEGFlow inference."""
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


def _apply_optional_raw_filter_resample(
    raw: Any,
    *,
    filter_l_freq: Optional[float] = None,
    filter_h_freq: Optional[float] = None,
    resample_sfreq: Optional[float] = None,
) -> Any:
    l_freq = None if filter_l_freq is None or float(filter_l_freq) <= 0 else float(filter_l_freq)
    h_freq = None if filter_h_freq is None or float(filter_h_freq) <= 0 else float(filter_h_freq)
    target = None if resample_sfreq is None or float(resample_sfreq) <= 0 else float(resample_sfreq)
    if l_freq is not None or h_freq is not None:
        raw.filter(l_freq=l_freq, h_freq=h_freq, picks="meg", verbose=False)
    if target is not None:
        if h_freq is not None and h_freq >= 0.5 * target:
            raise ValueError(f"filter_h_freq={h_freq} must be below Nyquist for resample_sfreq={target}")
        raw.resample(target, npad="auto", verbose=False)
    return raw


def sensor_type_from_scale(scale: np.ndarray) -> np.ndarray:
    """Return 1=mag, 2=grad, matching BadChnNet training caches."""
    s = np.asarray(scale, dtype=np.float32).reshape(-1)
    return np.where(s >= 1e14, 1, 2).astype(np.int64)


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
) -> Tuple[List[np.ndarray], np.ndarray, float, np.ndarray, np.ndarray, np.ndarray, List[str], np.ndarray, np.ndarray]:
    import mne

    if duration_sec <= 0:
        raise ValueError("duration_sec must be > 0")
    picks = mne.pick_types(raw.info, meg=True, eeg=False, ref_meg=False, exclude=[])
    if len(picks) == 0:
        raise RuntimeError("fif 中未找到 MEG 通道")

    raw = raw.copy().pick(picks)
    ch_names = list(raw.ch_names)
    y_bad_channel = np.asarray([1 if nm in bad_name_set else 0 for nm in ch_names], dtype=np.int64)
    if pick_exclude_marked_bads:
        mask_names = set(bad_name_set)
    else:
        mask_names = set()
    node_valid = np.asarray([0 if nm in mask_names else 1 for nm in ch_names], dtype=np.int64)
    channel_pos = get_channel_positions_3d(raw)
    x_raw_channel_scale = meg_amplitude_scale_per_channel(raw, meg_scale_mag, meg_scale_grad)

    sfreq = float(raw.info["sfreq"])
    epochs = mne.make_fixed_length_epochs(
        raw,
        duration=float(duration_sec),
        overlap=0.0,
        reject_by_annotation=False,
        preload=True,
        verbose=False,
    )
    window_array = epochs.get_data().astype(np.float32, copy=False)
    window_signals = [window_array[i] for i in range(int(window_array.shape[0]))]
    window_labels = np.zeros(len(window_signals), dtype=np.int64)
    return (
        window_signals,
        window_labels,
        sfreq,
        channel_pos,
        x_raw_channel_scale,
        y_bad_channel,
        ch_names,
        node_valid,
        window_array,
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
    filter_l_freq: Optional[float] = None,
    filter_h_freq: Optional[float] = None,
    resample_sfreq: Optional[float] = None,
) -> Dict[str, Any]:
    import mne

    fif_path = Path(fif_path)
    bad_chn = None
    if pick_exclude_marked_bads:
        bad_chn = resolve_bad_channels_path(fif_path, annot_root, category, dataset)
    raw = mne.io.read_raw_fif(fif_path, preload=True, verbose=False)
    _apply_optional_raw_filter_resample(
        raw,
        filter_l_freq=filter_l_freq,
        filter_h_freq=filter_h_freq,
        resample_sfreq=resample_sfreq,
    )
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
        window_array,
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
        "window_array": window_array,
        "dataset": str(dataset) if dataset else "single",
        "category": str(category) if category else "single",
        "pre_pick_auto_bad_channel_names": [],
    }


def build_torch_data_list(record: Dict[str, Any], edge_k: int = 6) -> List[Any]:
    """Build PyG Data list using the same data_builder path as m0_deepreject."""
    from .model.data_builder import build_recording_data_list

    return build_recording_data_list(
        record["window_signals"],
        record["window_labels"],
        record["sfreq"],
        record["channel_pos"],
        record["x_raw_channel_scale"],
        edge_method="knn",
        edge_k=int(edge_k),
        y_bad_channel=record["y_bad_channel"],
        node_valid=record.get("node_valid"),
    )


def build_badchnnet_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Build V11/BadChnNet tensor input from a loaded recording."""
    window_array = record.get("window_array")
    if window_array is not None:
        x_raw = np.asarray(window_array, dtype=np.float32)
    else:
        window_signals = record.get("window_signals") or []
        if not window_signals:
            raise RuntimeError("recording has no windows")
        x_raw = np.stack(window_signals, axis=0).astype(np.float32, copy=False)
    if x_raw.size == 0:
        raise RuntimeError("recording has no windows")
    scale = np.asarray(record["x_raw_channel_scale"], dtype=np.float32).reshape(1, -1, 1)
    x_scaled = np.nan_to_num(x_raw * scale, nan=0.0, posinf=0.0, neginf=0.0)
    channel_pos = np.asarray(record["channel_pos"], dtype=np.float32)
    if channel_pos.ndim == 1:
        channel_pos = channel_pos.reshape(-1, 3)
    if channel_pos.shape[1] < 3:
        pad = np.zeros((channel_pos.shape[0], 3 - channel_pos.shape[1]), dtype=np.float32)
        channel_pos = np.concatenate([channel_pos, pad], axis=1)
    return {
        "x": x_scaled,
        "channel_pos": channel_pos[:, :3].astype(np.float32, copy=False),
        "sensor_type": sensor_type_from_scale(record["x_raw_channel_scale"]),
        "ch_names": list(record.get("ch_names") or []),
        "sfreq": float(record.get("sfreq", 0.0)),
    }
