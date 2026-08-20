# -*- coding: utf-8 -*-
"""Self-contained FIF loading and input construction for MEGFlow inference."""
from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np


BAD_CHANNEL_SUFFIXES = ("_bad_chn.txt",)
LOGGER = logging.getLogger(__name__)

DEFAULT_DEEPREJECT_PREPROC: List[Dict[str, Any]] = [
    {
        "filter": {
            "l_freq": 1.0,
            "h_freq": 100.0,
            "method": "iir",
            "iir_params": {"order": 5, "ftype": "butter"},
        }
    },
    {"notch_filter": {"freqs": 50}},
    {"resample": {"sfreq": 250}},
]
_SUPPORTED_DEEPREJECT_PREPROC = {"filter", "notch_filter", "resample"}


def _positive_float(value: Any, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive number") from exc
    if not np.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{field_name} must be a positive number")
    return parsed


def _numeric_freqs(value: Any, field_name: str = "preproc.notch_filter.freqs") -> List[float]:
    if isinstance(value, str):
        values = value.replace(",", " ").split()
    elif isinstance(value, (list, tuple, np.ndarray)):
        values = list(value)
    else:
        values = [value]
    if not values:
        raise ValueError(f"{field_name} must contain at least one positive frequency")
    return [_positive_float(item, field_name) for item in values]


def resolve_deepreject_preproc(value: Any = None) -> List[Dict[str, Any]]:
    """Resolve and validate the complete DeepReject model-input recipe.

    Missing, null, and empty recipes select an isolated copy of the bundled
    model-validated default. Only an explicit false/off value disables it.
    """
    if value is None or value == []:
        return deepcopy(DEFAULT_DEEPREJECT_PREPROC)
    if value is False or (
        isinstance(value, str) and value.strip().lower() in {"false", "off"}
    ):
        return []
    if not isinstance(value, list):
        raise ValueError(
            "artifacts.deepreject.preproc must be a list of single-operation mappings, false, or off"
        )

    resolved = deepcopy(value)
    for index, step in enumerate(resolved):
        if not isinstance(step, dict) or len(step) != 1:
            raise ValueError(
                f"artifacts.deepreject.preproc[{index}] must contain exactly one operation"
            )
        operation, parameters = next(iter(step.items()))
        if operation not in _SUPPORTED_DEEPREJECT_PREPROC:
            supported = ", ".join(sorted(_SUPPORTED_DEEPREJECT_PREPROC))
            raise ValueError(
                f"Unsupported artifacts.deepreject.preproc operation {operation!r}; "
                f"supported operations: {supported}"
            )
        if not isinstance(parameters, dict):
            raise ValueError(
                f"artifacts.deepreject.preproc[{index}].{operation} must be a mapping"
            )
        if operation == "filter":
            l_freq = parameters.get("l_freq")
            h_freq = parameters.get("h_freq")
            if l_freq is None and h_freq is None:
                raise ValueError("DeepReject filter requires l_freq and/or h_freq")
            if l_freq is not None:
                l_freq = _positive_float(l_freq, "preproc.filter.l_freq")
            if h_freq is not None:
                h_freq = _positive_float(h_freq, "preproc.filter.h_freq")
            if l_freq is not None and h_freq is not None and l_freq >= h_freq:
                raise ValueError("preproc.filter.l_freq must be below h_freq")
        elif operation == "notch_filter":
            if "freqs" not in parameters:
                raise ValueError("DeepReject notch_filter requires freqs")
            _numeric_freqs(parameters["freqs"])
        elif "sfreq" not in parameters:
            raise ValueError("DeepReject resample requires sfreq")
        else:
            _positive_float(parameters["sfreq"], "preproc.resample.sfreq")
    return resolved


def _raw_frequency_summary(raw: Any) -> Dict[str, float]:
    return {
        "highpass_hz": float(raw.info.get("highpass", 0.0) or 0.0),
        "lowpass_hz": float(raw.info.get("lowpass", 0.0) or 0.0),
        "sfreq_hz": float(raw.info.get("sfreq", 0.0) or 0.0),
    }


def _recipe_source(value: Any) -> str:
    if value is False or (
        isinstance(value, str) and value.strip().lower() in {"false", "off"}
    ):
        return "disabled"
    if value is None or value == []:
        return "default"
    return "user_override"


def _step_requested_frequencies(step: Dict[str, Any]) -> List[float]:
    operation, parameters = next(iter(step.items()))
    if operation == "filter":
        return [
            float(parameters[key])
            for key in ("l_freq", "h_freq")
            if parameters.get(key) is not None
        ]
    if operation == "notch_filter":
        return _numeric_freqs(parameters.get("freqs"))
    return []


def _mne_notch_design_error(
    sfreq: float,
    parameters: Dict[str, Any],
    *,
    freqs: Optional[List[float]] = None,
) -> Optional[str]:
    """Return MNE's sampling-domain error for a notch design, if any.

    The public MNE filter designer is the source of truth for FIR transition
    edges. A second design at a safely higher sampling rate distinguishes a
    Nyquist-domain limitation from malformed configuration, which must remain
    an error.
    """
    import mne

    requested = _numeric_freqs(
        parameters.get("freqs") if freqs is None else freqs
    )
    method = str(parameters.get("method", "fir"))
    if method == "spectrum_fit":
        if any(frequency >= float(sfreq) / 2.0 for frequency in requested):
            return (
                f"frequency at/above Nyquist={float(sfreq) / 2.0:g} Hz "
                "is not admissible for MNE spectrum_fit notch filtering"
            )
        return None

    notch_widths = parameters.get("notch_widths")
    if notch_widths is None:
        widths = np.asarray(requested, dtype=float) / 200.0
    else:
        widths = np.atleast_1d(np.asarray(notch_widths, dtype=float))
        if np.any(widths < 0):
            raise ValueError("preproc.notch_filter.notch_widths must be non-negative")
        if widths.size == 1:
            widths = np.repeat(widths, len(requested))
        elif widths.size != len(requested):
            raise ValueError(
                "preproc.notch_filter.notch_widths must be scalar or match freqs"
            )

    transition = _positive_float(
        parameters.get("trans_bandwidth", 1.0),
        "preproc.notch_filter.trans_bandwidth",
    )
    transition_half = transition / 2.0
    requested_array = np.asarray(requested, dtype=float)
    lows = requested_array - widths / 2.0 - transition_half
    highs = requested_array + widths / 2.0 + transition_half

    design_kwargs = {
        "data": None,
        "l_freq": highs.tolist(),
        "h_freq": lows.tolist(),
        "filter_length": parameters.get("filter_length", "auto"),
        "l_trans_bandwidth": transition_half,
        "h_trans_bandwidth": transition_half,
        "method": method,
        "iir_params": parameters.get("iir_params"),
        "phase": parameters.get("phase", "zero"),
        "fir_window": parameters.get("fir_window", "hamming"),
        "fir_design": parameters.get("fir_design", "firwin"),
        "verbose": "error",
    }

    def _design(candidate_sfreq: float) -> None:
        mne.filter.create_filter(sfreq=float(candidate_sfreq), **design_kwargs)

    try:
        _design(sfreq)
    except ValueError as current_error:
        safe_sfreq = max(float(sfreq) * 2.0, float(np.max(highs)) * 4.0 + 1.0)
        try:
            _design(safe_sfreq)
        except ValueError:
            raise current_error
        return str(current_error)
    return None


def _mne_notch_frequency_outcomes(
    sfreq: float,
    parameters: Dict[str, Any],
) -> Tuple[List[float], Optional[List[float]], List[str]]:
    """Return usable notch centers, aligned widths, and skipped reasons."""
    requested_freqs = _numeric_freqs(parameters.get("freqs"))
    configured_widths = parameters.get("notch_widths")
    if configured_widths is not None:
        aligned_widths = np.atleast_1d(
            np.asarray(configured_widths, dtype=float)
        )
        if aligned_widths.size == 1:
            aligned_widths = np.repeat(aligned_widths, len(requested_freqs))
        elif aligned_widths.size != len(requested_freqs):
            raise ValueError(
                "preproc.notch_filter.notch_widths must be scalar or match freqs"
            )
    else:
        aligned_widths = None

    usable_freqs: List[float] = []
    usable_widths: Optional[List[float]] = [] if aligned_widths is not None else None
    skipped_reasons: List[str] = []
    for index, frequency in enumerate(requested_freqs):
        single_frequency_config = deepcopy(parameters)
        if aligned_widths is not None:
            single_frequency_config["notch_widths"] = float(aligned_widths[index])
        design_error = _mne_notch_design_error(
            sfreq,
            single_frequency_config,
            freqs=[frequency],
        )
        if design_error is None:
            usable_freqs.append(frequency)
            if usable_widths is not None:
                usable_widths.append(float(aligned_widths[index]))
        else:
            skipped_reasons.append(
                f"{frequency:g} Hz: MNE notch design is not admissible "
                f"at {float(sfreq):g} Hz ({design_error})"
            )
    return usable_freqs, usable_widths, skipped_reasons


def _execution_recipe(recipe: List[Dict[str, Any]], source_sfreq: float) -> List[Dict[str, Any]]:
    """Defer frequency steps without reversing the configured resample order."""
    pending = deepcopy(recipe)
    execution: List[Dict[str, Any]] = []
    current_sfreq = float(source_sfreq)
    while pending:
        step = pending[0]
        operation = next(iter(step))
        requested = _step_requested_frequencies(step)
        if operation == "notch_filter":
            current_admissible_count = len(
                _mne_notch_frequency_outcomes(
                    current_sfreq,
                    step["notch_filter"],
                )[0]
            )
            frequency_step_is_admissible = current_admissible_count == len(requested)
        else:
            frequency_step_is_admissible = not any(
                frequency >= current_sfreq / 2.0 for frequency in requested
            )
        if operation in {"filter", "notch_filter"} and not frequency_step_is_admissible:
            resample_index = next(
                (
                    index
                    for index, candidate in enumerate(pending[1:], start=1)
                    if "resample" in candidate
                    and (
                        len(
                            _mne_notch_frequency_outcomes(
                                candidate["resample"].get("sfreq"),
                                step["notch_filter"],
                            )[0]
                        )
                        > current_admissible_count
                        if operation == "notch_filter"
                        else all(
                            frequency
                            < _positive_float(
                                candidate["resample"].get("sfreq"),
                                "preproc.resample.sfreq",
                            )
                            / 2.0
                            for frequency in requested
                        )
                    )
                ),
                None,
            )
            if resample_index is not None:
                prefix = pending[: resample_index + 1]
                pending = (
                    [candidate for candidate in prefix if "resample" in candidate]
                    + [candidate for candidate in prefix if "resample" not in candidate]
                    + pending[resample_index + 1 :]
                )
                continue
        execution.append(pending.pop(0))
        if operation == "resample":
            current_sfreq = float(step["resample"]["sfreq"])
    return execution


def apply_deepreject_preproc(raw: Any, value: Any = None) -> Tuple[Any, Dict[str, Any]]:
    """Apply the resolved recipe to an isolated DeepReject model-input copy."""
    import mne

    recipe = resolve_deepreject_preproc(value)
    recipe_source = _recipe_source(value)
    source_before = _raw_frequency_summary(raw)
    source_limitations: List[str] = []
    if source_before["highpass_hz"] > 1.05:
        source_limitations.append("source high-pass is above 1 Hz")
    if source_before["lowpass_hz"] < 99.95:
        source_limitations.append("source low-pass is below 100 Hz")
    if source_before["sfreq_hz"] < 249.9:
        source_limitations.append("source sampling rate is below 250 Hz")
    for limitation in source_limitations:
        LOGGER.info(
            "DeepReject source limitation: %s; preprocessing cannot recreate unavailable source information.",
            limitation,
        )

    model_raw = raw.copy()
    applied_steps: List[Dict[str, Any]] = []
    if recipe:
        model_raw.load_data()
        picks = mne.pick_types(
            model_raw.info,
            meg=True,
            ref_meg=False,
            exclude=[],
        )
        if len(picks) == 0:
            raise ValueError("no MEG channels available for DeepReject preprocessing")

        for step in _execution_recipe(recipe, source_before["sfreq_hz"]):
            operation, configured = next(iter(step.items()))
            parameters = deepcopy(configured)
            sfreq_before = float(model_raw.info["sfreq"])
            nyquist = sfreq_before / 2.0
            if operation == "resample":
                target = _positive_float(parameters.pop("sfreq"), "preproc.resample.sfreq")
                if np.isclose(sfreq_before, target, rtol=0.0, atol=1e-9):
                    applied_steps.append(
                        {
                            "step": "resample",
                            "status": "skipped",
                            "reason": "already at target sampling rate",
                            "sfreq_before": sfreq_before,
                            "sfreq_after": sfreq_before,
                        }
                    )
                    continue
                parameters.setdefault("npad", "auto")
                parameters.setdefault("verbose", "error")
                model_raw.resample(target, **parameters)
                sfreq_after = float(model_raw.info["sfreq"])
                applied_steps.append(
                    {
                        "step": "resample",
                        "status": "applied",
                        "sfreq_before": sfreq_before,
                        "sfreq_after": sfreq_after,
                    }
                )
                LOGGER.info(
                    "DeepReject model input resampled from %.1f Hz to %.1f Hz "
                    "(model-only; main FIF unchanged).",
                    sfreq_before,
                    sfreq_after,
                )
                continue

            if operation == "filter":
                l_freq = parameters.pop("l_freq", None)
                h_freq = parameters.pop("h_freq", None)
                skipped = []
                if l_freq is not None and float(l_freq) >= nyquist:
                    skipped.append(f"l_freq={float(l_freq):g} Hz is not below Nyquist={nyquist:g} Hz")
                    l_freq = None
                if h_freq is not None and float(h_freq) >= nyquist:
                    skipped.append(f"h_freq={float(h_freq):g} Hz is not below Nyquist={nyquist:g} Hz")
                    h_freq = None
                if l_freq is None and h_freq is None:
                    applied_steps.append(
                        {"step": "filter", "status": "skipped", "reason": "; ".join(skipped)}
                    )
                    continue
                parameters.update(l_freq=l_freq, h_freq=h_freq, picks=picks)
                parameters.setdefault("verbose", "error")
                model_raw.filter(**parameters)
                record: Dict[str, Any] = {
                    "step": "filter",
                    "status": "applied",
                    "l_freq": l_freq,
                    "h_freq": h_freq,
                }
                if skipped:
                    record["skipped_frequency_parts"] = skipped
                    record["reason"] = "; ".join(skipped)
                applied_steps.append(record)
                continue

            requested_freqs = _numeric_freqs(parameters.pop("freqs"))
            usable_freqs, usable_widths, skipped_reasons = (
                _mne_notch_frequency_outcomes(
                    sfreq_before,
                    configured,
                )
            )
            if not usable_freqs:
                applied_steps.append(
                    {
                        "step": "notch_filter",
                        "status": "skipped",
                        "freqs": requested_freqs,
                        "reason": "; ".join(skipped_reasons),
                    }
                )
                continue
            if usable_widths is not None:
                parameters["notch_widths"] = np.asarray(usable_widths, dtype=float)
            parameters.update(freqs=usable_freqs, picks=picks)
            parameters.setdefault("verbose", "error")
            model_raw.notch_filter(**parameters)
            record = {
                "step": "notch_filter",
                "status": "applied",
                "freqs": usable_freqs,
            }
            if usable_widths is not None:
                record["notch_widths"] = usable_widths
            if skipped_reasons:
                record["reason"] = "; ".join(skipped_reasons)
            applied_steps.append(record)

    provenance = {
        "source_before": source_before,
        "recipe_source": recipe_source,
        "resolved_recipe": deepcopy(recipe),
        "applied_steps": applied_steps,
        "model_input_after": _raw_frequency_summary(model_raw),
        "default_recipe_match": recipe == DEFAULT_DEEPREJECT_PREPROC,
        "source_limitations": source_limitations,
    }
    return model_raw, provenance


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
