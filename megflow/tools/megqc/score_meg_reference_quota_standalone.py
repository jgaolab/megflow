#!/usr/bin/env python3
# coding: utf-8
"""Standalone scorer for the selected MEG QC reference-quota metrics.

The metric names keep the training/report namespace (for example
``tsfel.max_abs_diff``), but this script does not import tsfel or msqms.  The
selected tsfel-like metrics are implemented directly with NumPy, and the
msqms-derived frequency/fractal formulas are ported from the local msqms source
so that deployment cannot drift because of package-version differences.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections.abc import Iterable as IterableABC
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL = "lowcost_quota_T4_S2_Stat1_Fr1"


def load_optional_mne():
    try:
        import mne  # type: ignore

        return mne
    except Exception as exc:
        raise SystemExit("mne is required for --fif scoring. Activate the MEG environment first.") from exc


def fnum(value: object, digits: int = 4) -> str:
    try:
        v = float(value)
    except Exception:
        return ""
    if not np.isfinite(v):
        return ""
    return f"{v:.{digits}g}"


def json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if hasattr(value, "item"):
        try:
            return json_ready(value.item())
        except Exception:
            pass
    return value


def normalize_device_type(value: object) -> str:
    text = str(value or "").strip()
    key = text.lower().replace("_", "-").replace(" ", "")
    mapping = {
        "4d": "4D",
        "magnes": "4D",
        "ctf": "CTF",
        "elekta": "Elekta",
        "neuromag": "Elekta",
        "kit": "KIT",
        "quanmag": "QuanMag",
        "opm-quanmag": "QuanMag",
        "quspin": "QuSpin",
        "opm-quspin": "QuSpin",
    }
    return mapping.get(key, text or "ALL")


def str_to_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _parse_freqs(value: object) -> list[float]:
    if value is None:
        return []
    if isinstance(value, str):
        tokens = value.replace(",", " ").split()
    elif isinstance(value, IterableABC):
        tokens = list(value)
    else:
        tokens = [value]
    freqs = []
    for token in tokens:
        parsed = _float_or_none(token)
        if parsed is not None and parsed > 0:
            freqs.append(parsed)
    return freqs


def _fallback_preproc_steps(text: str) -> list[dict[str, object]]:
    """Parse the simple inline configs used by nextflow.config without PyYAML."""
    steps: list[dict[str, object]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "filter:" in stripped and "notch_filter" not in stripped:
            cfg: dict[str, object] = {}
            l_match = re.search(r"l_freq\s*:\s*([-+]?\d+(?:\.\d+)?)", stripped)
            h_match = re.search(r"h_freq\s*:\s*([-+]?\d+(?:\.\d+)?)", stripped)
            method_match = re.search(r"method\s*:\s*([A-Za-z0-9_]+)", stripped)
            order_match = re.search(r"order\s*:\s*(\d+)", stripped)
            ftype_match = re.search(r"ftype\s*:\s*([A-Za-z0-9_]+)", stripped)
            if l_match:
                cfg["l_freq"] = float(l_match.group(1))
            if h_match:
                cfg["h_freq"] = float(h_match.group(1))
            if method_match:
                cfg["method"] = method_match.group(1)
            if order_match or ftype_match:
                cfg["iir_params"] = {}
                if order_match:
                    cfg["iir_params"]["order"] = int(order_match.group(1))
                if ftype_match:
                    cfg["iir_params"]["ftype"] = ftype_match.group(1)
            if cfg:
                steps.append({"filter": cfg})
        elif "notch_filter:" in stripped:
            cfg = {}
            freqs_match = re.search(r"freqs\s*:\s*([^}\]]+)", stripped)
            method_match = re.search(r"method\s*:\s*([A-Za-z0-9_]+)", stripped)
            if freqs_match:
                cfg["freqs"] = freqs_match.group(1).replace("[", "").replace(",", " ")
            if method_match:
                cfg["method"] = method_match.group(1)
            if cfg:
                steps.append({"notch_filter": cfg})
    if not steps:
        raise ValueError("Could not parse MEG QC preprocessing config without PyYAML.")
    return steps


def load_preproc_steps(config_text: str | None) -> list[dict[str, object]]:
    """Parse the small OSL-style preprocessing subset used before QC scoring."""
    text = (config_text or "").strip()
    if not text or text.lower() in {"none", "false", "off"}:
        return []
    try:
        import yaml  # type: ignore
    except Exception:
        return _fallback_preproc_steps(text)

    parsed = yaml.safe_load(text) or {}
    steps = parsed.get("preproc", parsed if isinstance(parsed, list) else [])
    if not isinstance(steps, list):
        raise ValueError("MEG QC preprocessing config must contain a 'preproc' list.")
    return [step for step in steps if isinstance(step, dict)]


def apply_reference_preprocessing(raw, args: argparse.Namespace):
    """Apply reference-space preprocessing before metric extraction.

    The bundled reference was built after light preprocessing.  Keeping this
    step inside the scorer prevents raw scale/frequency content from drifting
    away from the normative reference.  Bad channels and BAD annotations are
    intentionally retained by default; they are controlled separately in
    ``prepare_metric_raw``.
    """
    mne = load_optional_mne()
    steps = load_preproc_steps(getattr(args, "preproc_config", ""))
    if not steps:
        return raw, []

    raw = raw.copy().load_data(verbose="error")
    picks = mne.pick_types(raw.info, meg=True, ref_meg=False, exclude=[])
    if len(picks) == 0:
        raise ValueError("no MEG channels available for reference preprocessing")

    applied: list[dict[str, object]] = []
    sfreq = float(raw.info.get("sfreq", np.nan))
    nyquist = sfreq / 2.0 if np.isfinite(sfreq) and sfreq > 0 else np.nan
    for step in steps:
        if "filter" in step and isinstance(step["filter"], dict):
            cfg = dict(step["filter"])
            l_freq = _float_or_none(cfg.get("l_freq"))
            h_freq = _float_or_none(cfg.get("h_freq"))
            if h_freq is not None and np.isfinite(nyquist) and h_freq >= nyquist:
                h_freq = None
            if l_freq is None and h_freq is None:
                applied.append({"step": "filter", "status": "skipped", "reason": "no usable l_freq/h_freq"})
                continue
            kwargs = {
                "l_freq": l_freq,
                "h_freq": h_freq,
                "picks": picks,
                "verbose": "error",
            }
            for key in ("method", "iir_params", "fir_design", "phase", "filter_length", "l_trans_bandwidth", "h_trans_bandwidth"):
                if key in cfg and cfg[key] is not None:
                    kwargs[key] = cfg[key]
            raw.filter(**kwargs)
            applied.append({"step": "filter", "l_freq": l_freq, "h_freq": h_freq, "method": cfg.get("method", "fir")})
        elif "notch_filter" in step and isinstance(step["notch_filter"], dict):
            cfg = dict(step["notch_filter"])
            freqs = _parse_freqs(cfg.get("freqs"))
            if np.isfinite(nyquist):
                freqs = [freq for freq in freqs if freq < nyquist]
            if not freqs:
                applied.append(
                    {
                        "step": "notch_filter",
                        "status": "skipped",
                        "freqs": cfg.get("freqs", ""),
                        "reason": "no explicit numeric frequencies below Nyquist",
                    }
                )
                continue
            kwargs = {"freqs": freqs, "picks": picks, "verbose": "error"}
            for key in ("method", "notch_widths", "trans_bandwidth", "mt_bandwidth", "p_value", "filter_length", "phase", "fir_window", "fir_design"):
                if key in cfg and cfg[key] is not None:
                    kwargs[key] = cfg[key]
            raw.notch_filter(**kwargs)
            applied.append(
                {
                    "step": "notch_filter",
                    "freqs": freqs,
                    "method": cfg.get("method", "fir"),
                    "source": "config",
                }
            )
    return raw, applied


def summarize_vector(values: Iterable[float], prefix: str, out: dict[str, float]) -> None:
    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return
    stats = {
        "mean": np.nanmean(arr),
        "std": np.nanstd(arr),
        "min": np.nanmin(arr),
        "q05": np.nanquantile(arr, 0.05),
        "q25": np.nanquantile(arr, 0.25),
        "median": np.nanmedian(arr),
        "q75": np.nanquantile(arr, 0.75),
        "q95": np.nanquantile(arr, 0.95),
        "max": np.nanmax(arr),
    }
    stats["iqr"] = stats["q75"] - stats["q25"]
    abs_arr = np.abs(arr)
    stats["abs_mean"] = np.nanmean(abs_arr)
    stats["abs_q95"] = np.nanquantile(abs_arr, 0.95)
    stats["abs_max"] = np.nanmax(abs_arr)
    for name, value in stats.items():
        if np.isfinite(value):
            out[f"{prefix}.{name}"] = float(value)


def uniformly_subsample_time(data: np.ndarray, max_samples: int) -> np.ndarray:
    if max_samples <= 0 or data.shape[1] <= max_samples:
        return data
    idx = np.linspace(0, data.shape[1] - 1, int(max_samples)).astype(int)
    return data[:, idx]


def msqms_frequency_channel_features(signal: np.ndarray, sfreq: float = 1000.0) -> dict[str, float]:
    """Port of msqms.qc.freq_domain_metrics.FreqDomainMetric._get_fre_domain_features.

    Only ``skewness_amplitude`` and ``kurtosis_amplitude`` are needed by the
    selected T4/T5 models, but the shared intermediates follow the original
    implementation exactly: FFT on ``signal / L``, first half of the spectrum,
    and the DC component set to zero.
    """
    signal = np.asarray(signal, dtype=np.float64)
    n = int(signal.size)
    if n < 4 or not np.isfinite(sfreq) or sfreq <= 0:
        return {}
    y = np.abs(np.fft.fft(signal / float(n)))[: int(n / 2)]
    if y.size < 2:
        return {}
    y[0] = 0.0
    fre_line_num = len(y)
    y_mean = float(np.mean(y))
    y_var = float(np.var(y))
    y_std = math.sqrt(y_var) if y_var > 0 else 0.0
    y_sum = float(np.sum(y))
    if y_sum <= np.finfo(float).eps:
        return {"skewness_amplitude": 0.0, "kurtosis_amplitude": 0.0}
    return {
        "skewness_amplitude": float(np.sum((y - y_mean) ** 3) / (fre_line_num * y_std**3)) if y_std > 0 else 0.0,
        "kurtosis_amplitude": float(np.sum((y - y_mean) ** 4) / (fre_line_num * y_std**4)) if y_std > 0 else 0.0,
    }


def antropy_dfa_1d(data: np.ndarray) -> float:
    try:
        import antropy as ant  # type: ignore
    except Exception:
        return np.nan
    try:
        return float(ant.detrended_fluctuation(np.asarray(data, dtype=np.float64)))
    except Exception:
        return np.nan


def compute_dfa_channels(data: np.ndarray, n_jobs: int) -> np.ndarray:
    try:
        from joblib import Parallel, delayed  # type: ignore
    except Exception:
        return np.asarray([antropy_dfa_1d(data[i]) for i in range(data.shape[0])], dtype=float)
    vals = Parallel(n_jobs=max(1, int(n_jobs)), backend="threading")(
        delayed(antropy_dfa_1d)(data[i]) for i in range(data.shape[0])
    )
    return np.asarray(vals, dtype=float)


def sampled_dfa(data: np.ndarray, n_jobs: int) -> float:
    vals = compute_dfa_channels(np.nan_to_num(data.astype(np.float64), nan=0.0), n_jobs)
    arr = np.asarray(vals, dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(np.mean(arr)) if arr.size else np.nan


def msqms_segment_sample_bounds(n_samples: int, sfreq: float, seg_length: float) -> list[tuple[int, int]]:
    """Return sample bounds equivalent to msqms.utils.segment_raw_data.

    The original code segments by seconds and includes the final partial
    segment.  Here we work on the already prepared NumPy matrix to avoid any
    dependency on the msqms package while keeping the same averaging structure.
    """
    if n_samples <= 0 or not np.isfinite(sfreq) or sfreq <= 0:
        return []
    duration = n_samples / float(sfreq)
    if seg_length <= 0 or seg_length >= duration:
        return [(0, n_samples)]
    bounds: list[tuple[int, int]] = []
    for start_sec in np.arange(0.0, duration, float(seg_length)):
        stop_sec = min(float(start_sec + seg_length), duration)
        start = int(round(start_sec * sfreq))
        # mne.io.Raw.crop(..., include_tmax=True) includes the right endpoint,
        # which is what msqms.segment_raw_data feeds into FractalDomainMetric.
        stop = int(round(stop_sec * sfreq)) + 1
        if stop > start:
            bounds.append((start, min(stop, n_samples)))
    return bounds


def msqms_segmented_dfa(data: np.ndarray, sfreq: float, n_jobs: int, seg_length: int) -> float:
    """Port of msqms FractalDomainMetric DFA aggregation.

    For each segment, DFA is computed per channel.  Segment-level channel
    results are averaged across segments first, then the channel average is
    returned.  This mirrors ``compute_metrics(...).loc['avg_<meg_type>', 'DFA']``.
    """
    if data.ndim != 2 or data.shape[0] == 0 or data.shape[1] < 4:
        return np.nan
    data = np.nan_to_num(np.asarray(data, dtype=np.float64), nan=0.0)
    segment_values = []
    for start, stop in msqms_segment_sample_bounds(data.shape[1], sfreq, float(seg_length)):
        vals = compute_dfa_channels(data[:, start:stop], n_jobs)
        if vals.size:
            segment_values.append(vals)
    if not segment_values:
        return np.nan
    stacked = np.vstack(segment_values)
    channel_mean = np.nanmean(stacked, axis=0)
    channel_mean = channel_mean[np.isfinite(channel_mean)]
    return float(np.mean(channel_mean)) if channel_mean.size else np.nan


def prepare_metric_raw(
    raw,
    *,
    omit_bad_channels: bool = False,
    omit_bad_segments: bool = False,
):
    """Build a continuous MEG matrix for metric extraction.

    Defaults match the process_1 reference cohort: all MEG channels (including
    those marked bad) and the full timeline (including BAD-annotated spans).
    Use ``omit_bad_*`` only for ad-hoc diagnostics, not for normative scoring.
    """
    mne = load_optional_mne()
    meg_picks = mne.pick_types(raw.info, meg=True, ref_meg=False, exclude="bads" if omit_bad_channels else [])
    if len(meg_picks) == 0:
        raise ValueError("no MEG channels available for scoring")
    reject = "omit" if omit_bad_segments else None
    data = raw.get_data(picks=meg_picks, reject_by_annotation=reject)
    if data.ndim != 2 or data.shape[1] == 0:
        raise ValueError("no valid MEG samples available after annotation handling")
    info = mne.pick_info(raw.info.copy(), meg_picks, copy=True)
    if not omit_bad_channels:
        info["bads"] = []
    clean = mne.io.RawArray(data, info, first_samp=0, verbose="error")
    return clean


def compute_metric_values(raw, args: argparse.Namespace) -> dict[str, float]:
    mne = load_optional_mne()
    out: dict[str, float] = {}
    raw = prepare_metric_raw(
        raw,
        omit_bad_channels=args.omit_bad_channels,
        omit_bad_segments=args.omit_bad_annotations,
    )
    sfreq = float(raw.info.get("sfreq", np.nan))
    for meg_type in ("mag", "grad"):
        try:
            picks = mne.pick_types(raw.info, meg=meg_type, ref_meg=False, exclude=[])
        except Exception:
            picks = []
        if len(picks) == 0:
            continue
        data = np.asarray(raw.get_data(picks=picks), dtype=np.float64)
        if data.ndim != 2 or data.shape[0] == 0 or data.shape[1] < 4:
            continue
        out[f"extra_input.n_channels.{meg_type}"] = float(data.shape[0])
        out[f"extra_input.n_samples.{meg_type}"] = float(data.shape[1])
        out[f"extra_input.sfreq.{meg_type}"] = sfreq

        channel_min = np.nanmin(data, axis=1)
        channel_max = np.nanmax(data, axis=1)
        channel_ptp = channel_max - channel_min
        abs_diff = np.abs(np.diff(data, axis=1))
        channel_max_abs_diff = np.nanmax(abs_diff, axis=1)
        summarize_vector(channel_max_abs_diff, f"tsfel.max_abs_diff.{meg_type}", out)
        summarize_vector(channel_ptp, f"tsfel.ptp_amp.{meg_type}", out)

        sampled = uniformly_subsample_time(data, int(args.freq_max_samples))
        freq_acc: dict[str, list[float]] = {}
        for ch in range(sampled.shape[0]):
            for name, value in msqms_frequency_channel_features(sampled[ch], sfreq).items():
                freq_acc.setdefault(name, []).append(value)
        for name, values in freq_acc.items():
            arr = np.asarray(values, dtype=float)
            arr = arr[np.isfinite(arr)]
            if arr.size:
                out[f"freq_domain.{name}.{meg_type}"] = float(np.mean(arr))

        if not args.skip_dfa:
            if args.dfa_method == "msqms":
                dfa = msqms_segmented_dfa(data, sfreq, args.n_jobs, args.seg_length)
                if not np.isfinite(dfa):
                    dfa_data = uniformly_subsample_time(data, int(args.dfa_max_samples))
                    dfa = sampled_dfa(dfa_data, args.n_jobs)
            else:
                dfa_data = uniformly_subsample_time(data, int(args.dfa_max_samples))
                dfa = sampled_dfa(dfa_data, args.n_jobs)
            if np.isfinite(dfa):
                out[f"fractal_domain.DFA.{meg_type}"] = float(dfa)
    return out


def build_reference_lookup(ref_df: pd.DataFrame) -> dict[tuple[str, str, str, str, str], pd.Series]:
    out = {}
    for _, row in ref_df.iterrows():
        out[(str(row["scope"]), str(row["dataset"]), str(row["device_type"]), str(row["category"]), str(row["metric"]))] = row
    return out


def reference_candidates(device_type: str, category: str, reference_scope: str) -> list[tuple[str, str, str, str]]:
    device = normalize_device_type(device_type)
    cat = str(category or "ALL").strip() or "ALL"
    if reference_scope == "device_category":
        return [
            ("device_category", "ALL", device, cat),
            ("device", "ALL", device, "ALL"),
            ("category", "ALL", "ALL", cat),
            ("global", "ALL", "ALL", "ALL"),
        ]
    if reference_scope == "category":
        return [("category", "ALL", "ALL", cat), ("global", "ALL", "ALL", "ALL")]
    return [("global", "ALL", "ALL", "ALL")]


def get_reference_row(
    lookup: dict[tuple[str, str, str, str, str], pd.Series],
    metric: str,
    device_type: str,
    category: str,
    reference_scope: str,
    min_n: int,
) -> pd.Series | None:
    fallback = None
    for key in reference_candidates(device_type, category, reference_scope):
        ref = lookup.get((key[0], key[1], key[2], key[3], metric))
        if ref is None:
            continue
        if fallback is None:
            fallback = ref
        if int(float(ref.get("n", 0))) >= int(min_n):
            return ref
    return fallback


def score_value(x: float, ref: pd.Series, mode: str) -> float:
    q05, q50, q95 = float(ref["q05"]), float(ref["q50"]), float(ref["q95"])
    if not all(np.isfinite(v) for v in (x, q05, q50, q95)) or q95 <= q05:
        return np.nan
    z = min(1.0, max(0.0, (float(x) - q05) / (q95 - q05)))
    if mode == "lower_is_better":
        return 1.0 - z
    if mode == "higher_is_better":
        return z
    if float(x) <= q50:
        span = q50 - q05
        dev = (q50 - float(x)) / span if span > 0 else np.nan
    else:
        span = q95 - q50
        dev = (float(x) - q50) / span if span > 0 else np.nan
    return 1.0 - min(1.0, max(0.0, dev)) if np.isfinite(dev) else np.nan


def component_status(value: float, q05: float, q95: float) -> str:
    if not np.isfinite(value):
        return "missing"
    if value < q05:
        return "below_q05"
    if value > q95:
        return "above_q95"
    return "within_q05_q95"


def direction_label(mode: str) -> str:
    if mode == "lower_is_better":
        return "lower is better"
    if mode == "higher_is_better":
        return "higher is better"
    return "near q50 is better"


def score_metrics(
    metrics: dict[str, float],
    config: dict,
    ref_df: pd.DataFrame,
    device_type: str,
    category: str,
    reference_scope: str,
    min_reference_n: int,
) -> tuple[dict[str, object], pd.DataFrame]:
    lookup = build_reference_lookup(ref_df)
    rows = []
    family_scores = []
    family_details = []
    for family in config["families"]:
        comp_scores = []
        for metric in family["metrics"]:
            raw = float(metrics.get(metric, np.nan))
            ref = get_reference_row(lookup, metric, device_type, category, reference_scope, min_reference_n)
            mode = str(family.get("mode_by_metric", {}).get(metric, family.get("mode", "lower_is_better")))
            if ref is None:
                q05 = q50 = q95 = score = pos = np.nan
                scope = ref_category = ref_device = ""
                status = "no_reference"
            else:
                q05, q50, q95 = float(ref["q05"]), float(ref["q50"]), float(ref["q95"])
                scope = str(ref["scope"])
                ref_category = str(ref["category"])
                ref_device = str(ref["device_type"])
                score = score_value(raw, ref, mode) if np.isfinite(raw) else np.nan
                pos = (raw - q05) / (q95 - q05) if np.isfinite(raw) and q95 > q05 else np.nan
                status = component_status(raw, q05, q95)
            if np.isfinite(score):
                comp_scores.append(float(score))
            rows.append(
                {
                    "family": family["family"],
                    "domain": family["domain"],
                    "metric": metric,
                    "raw_value": raw,
                    "mode": mode,
                    "direction": direction_label(mode),
                    "reference_scope_used": scope,
                    "reference_device": ref_device,
                    "reference_category": ref_category,
                    "q05": q05,
                    "q50": q50,
                    "q95": q95,
                    "reference_position_q05_0_q95_1": pos,
                    "component_score_0_1": score,
                    "status": status,
                    "interpretation": family.get("quality_interpretation", ""),
                }
            )
        family_score = float(np.mean(comp_scores)) if comp_scores else np.nan
        if np.isfinite(family_score):
            family_scores.append(family_score)
        family_details.append({"family": family["family"], "domain": family["domain"], "score_0_100": family_score * 100.0 if np.isfinite(family_score) else np.nan, "n_components": len(comp_scores)})
    final_score = float(np.mean(family_scores) * 100.0) if family_scores else np.nan
    summary = {
        "model": config["model"],
        "score_0_100": final_score,
        "n_families_available": int(len(family_scores)),
        "n_families_expected": int(len(config["families"])),
        "device_type": normalize_device_type(device_type),
        "category": category,
        "reference_scope": reference_scope,
        "family_scores": family_details,
    }
    return summary, pd.DataFrame(rows)


STATUS_STYLES = {
    "within_q05_q95": {"color": "#059669", "label": "Within reference"},
    "above_q95": {"color": "#dc2626", "label": "Worse (above q95)"},
    "below_q05": {"color": "#2563eb", "label": "Better (below q05)"},
    "missing": {"color": "#94a3b8", "label": "Not computed"},
}


PLOTTED_STATUSES = {"within_q05_q95", "above_q95", "below_q05"}

DOMAIN_STYLES = {
    "Temporal": {"color": "#2563EB", "fill": "#EFF6FF"},
    "Statistic": {"color": "#7C3AED", "fill": "#F5F3FF"},
    "Spectral": {"color": "#D97706", "fill": "#FFFBEB"},
    "Fractal": {"color": "#059669", "fill": "#ECFDF5"},
}
DEFAULT_DOMAIN_STYLE = {"color": "#475569", "fill": "#F8FAFC"}


def _computed_plot_rows(detail: pd.DataFrame) -> pd.DataFrame:
    rows = detail.copy()
    rows["pos_plot"] = pd.to_numeric(rows["reference_position_q05_0_q95_1"], errors="coerce")
    rows["component_pct"] = pd.to_numeric(rows["component_score_0_1"], errors="coerce") * 100.0
    rows["status"] = rows["status"].astype(str)
    rows = rows[
        rows["status"].isin(PLOTTED_STATUSES)
        & np.isfinite(rows["pos_plot"])
        & np.isfinite(rows["component_pct"])
    ].copy()
    return rows.sort_values(["domain", "family", "metric"]).reset_index(drop=True)


def _domain_style(domain: str) -> dict[str, str]:
    return DOMAIN_STYLES.get(str(domain), DEFAULT_DOMAIN_STYLE)


def _metric_row_label(row: pd.Series, *, domain_prefix: str = "") -> str:
    family = str(row.get("family", ""))
    family_short = (
        family.replace("tsfel.", "")
        .replace("freq_domain.", "freq.")
        .replace("fractal_domain.", "fractal.")
    )
    metric = str(row.get("metric", ""))
    variant = ""
    if ".mag." in metric or metric.endswith(".mag"):
        variant = "mag"
    elif ".grad." in metric or metric.endswith(".grad"):
        variant = "grad"
    body = f"{family_short} · {variant}" if family_short and variant else (family_short or metric)
    return f"{domain_prefix}{body}"


def _status_label(status: str, mode: str) -> str:
    status = str(status)
    lower_better = "lower" in str(mode or "").lower()
    if status == "within_q05_q95":
        return "Within reference"
    if status == "above_q95":
        return "Worse (above q95)" if lower_better else "Above q95"
    if status == "below_q05":
        return "Better (below q05)" if lower_better else "Worse (below q05)"
    if status == "missing":
        return "Not computed"
    return status.replace("_", " ")


def _draw_reference_placeholder_plot(out_png: Path, message: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_axis_off()
    ax.text(0.5, 0.55, message, ha="center", va="center", fontsize=14, color="#374151")
    fig.savefig(out_png, facecolor="white", bbox_inches="tight", pad_inches=0.35)
    plt.close(fig)


def draw_reference_position_plot(
    detail: pd.DataFrame,
    out_png: Path,
    title: str,
    *,
    subtitle: str | None = None,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch, Rectangle

    rows = _computed_plot_rows(detail)
    if rows.empty:
        _draw_reference_placeholder_plot(out_png, "No computed reference-relative metrics are available for this recording.")
        return

    plot_rows: list[dict[str, object]] = []
    y = 0.0
    prev_domain = None
    for _, row in rows.iterrows():
        domain = str(row.get("domain", ""))
        if prev_domain is not None and domain != prev_domain:
            y += 1.0
        plot_rows.append({"y": y, "domain": domain, "row": row, "domain_first": domain != prev_domain})
        y += 1.0
        prev_domain = domain

    n = max(1, len(plot_rows))
    fig_h = max(8.0, 2.0 + 0.62 * n)
    fig_w = 16.5
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#FAFAFA")

    pos_values = pd.to_numeric(rows["reference_position_q05_0_q95_1"], errors="coerce")
    pos_max = float(pos_values.max()) if pos_values.notna().any() else 1.0
    pos_min = float(pos_values.min()) if pos_values.notna().any() else 0.0
    x_right = max(1.12, min(pos_max + 0.15, 3.0))
    x_left = min(-0.12, max(pos_min - 0.08, -0.35))

    domain_ranges: list[tuple[str, float, float]] = []
    current_domain = None
    start_y = 0.0
    last_y = 0.0
    for item in plot_rows:
        domain = str(item["domain"])
        y_pos = float(item["y"])
        if current_domain is None:
            current_domain = domain
            start_y = y_pos
        elif domain != current_domain:
            domain_ranges.append((current_domain, start_y, last_y))
            current_domain = domain
            start_y = y_pos
        last_y = y_pos
    if current_domain is not None:
        domain_ranges.append((current_domain, start_y, last_y))

    for domain, start, end in domain_ranges:
        style = _domain_style(domain)
        ax.axhspan(start - 0.44, end + 0.44, color=style["fill"], zorder=0)
        ax.vlines(x_left + 0.01, start - 0.36, end + 0.36, color=style["color"], linewidth=5.0, zorder=1)

    ax.axvspan(0.0, 1.0, color="#D1FAE5", alpha=0.46, zorder=0)
    ax.axvline(0.5, color="#6B7280", linewidth=1.4, linestyle="--", alpha=0.85, zorder=1)
    for tick in (0.0, 0.5, 1.0):
        ax.axvline(tick, color="#D1D5DB", linewidth=1.0, zorder=0)

    for item in plot_rows:
        row = item["row"]
        y_pos = item["y"]
        status = str(row.get("status", "missing"))
        style = STATUS_STYLES.get(status, STATUS_STYLES["missing"])
        pos = row["pos_plot"]
        ax.hlines(y_pos, 0.0, 1.0, colors="#CBD5E1", linewidth=5.0, zorder=2)
        if np.isfinite(pos):
            pos_f = float(pos)
            marker_x = float(np.clip(pos_f, x_left + 0.02, x_right - 0.02))
            ax.scatter(
                [marker_x],
                [y_pos],
                s=170,
                color=style["color"],
                edgecolors="white",
                linewidths=1.8,
                zorder=4,
            )
            if pos_f > x_right - 0.02:
                ax.annotate(
                    ">",
                    xy=(marker_x, y_pos),
                    xytext=(4, 0),
                    textcoords="offset points",
                    va="center",
                    ha="left",
                    fontsize=12,
                    color=style["color"],
                    fontweight="bold",
                    clip_on=False,
                )
            elif pos_f < x_left + 0.02:
                ax.annotate(
                    "<",
                    xy=(marker_x, y_pos),
                    xytext=(-4, 0),
                    textcoords="offset points",
                    va="center",
                    ha="right",
                    fontsize=12,
                    color=style["color"],
                    fontweight="bold",
                    clip_on=False,
                )

    yticks = [item["y"] for item in plot_rows]
    fixed_labels = []
    for item in plot_rows:
        fixed_labels.append(_metric_row_label(item["row"]))

    ax.set_yticks(yticks)
    ax.set_yticklabels(fixed_labels, fontsize=12)
    ax.set_xlim(x_left, x_right)
    ax.set_ylim(-0.8, max(yticks) + 0.8)
    ax.set_xticks([0.0, 0.5, 1.0])
    ax.set_xticklabels(["q05\n(5th pct)", "q50\n(median)", "q95\n(95th pct)"], fontsize=12)
    ax.set_xlabel(
        "Position relative to normative reference  (0 = q05,  0.5 = median,  1 = q95)"
        + ("  ·  values beyond 1 are above the 95th percentile" if x_right > 1.2 else ""),
        fontsize=12,
        labelpad=14,
    )
    ax.tick_params(axis="x", pad=8)
    ax.grid(axis="x", color="#E5E7EB", linewidth=0.8, alpha=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#D1D5DB")
    ax.spines["bottom"].set_color("#D1D5DB")

    bottom_margin = 0.22
    fig.subplots_adjust(left=0.34, right=0.76, top=0.86 if subtitle else 0.90, bottom=bottom_margin)

    title_y = 0.97
    fig.suptitle(title, fontsize=20, fontweight="bold", color="#111827", y=title_y)
    if subtitle:
        fig.text(0.08, 0.925, subtitle, ha="left", va="top", fontsize=12.5, color="#4B5563")

    legend_handles = [
        Patch(facecolor=style["color"], edgecolor="white", label=style["label"])
        for key, style in STATUS_STYLES.items()
        if key in PLOTTED_STATUSES
    ]
    fig.legend(
        handles=legend_handles,
        loc="lower left",
        bbox_to_anchor=(0.08, 0.07),
        ncol=4,
        frameon=False,
        fontsize=10.5,
        handlelength=1.2,
        columnspacing=1.2,
        labelspacing=0.6,
    )
    fig.text(
        0.08,
        0.032,
        "Shaded band = typical reference range (q05–q95).  Component scores are 0–100; higher is better.",
        ha="left",
        va="bottom",
        fontsize=10.5,
        color="#6B7280",
    )

    fig.canvas.draw()
    ax_pos = ax.get_position()
    y_min, y_max = ax.get_ylim()

    def _data_y_to_fig_y(y_data: float) -> float:
        frac = (y_data - y_min) / (y_max - y_min)
        return ax_pos.y0 + frac * ax_pos.height

    domain_label_x = 0.055
    domain_bar_x = 0.045
    domain_bar_w = 0.006
    for domain, start, end in domain_ranges:
        style = _domain_style(domain)
        fig_y0 = _data_y_to_fig_y(start - 0.36)
        fig_y1 = _data_y_to_fig_y(end + 0.36)
        fig_y0, fig_y1 = sorted((fig_y0, fig_y1))
        fig.patches.append(
            Rectangle(
                (domain_bar_x, fig_y0),
                domain_bar_w,
                fig_y1 - fig_y0,
                transform=fig.transFigure,
                facecolor=style["color"],
                edgecolor="none",
                zorder=5,
            )
        )
        fig.text(
            domain_label_x,
            (fig_y0 + fig_y1) / 2.0,
            domain,
            ha="left",
            va="center",
            fontsize=11.5,
            fontweight="bold",
            color=style["color"],
        )

    status_x = min(ax_pos.x1 + 0.012, 0.97)
    for item in plot_rows:
        row = item["row"]
        y_pos = float(item["y"])
        status = str(row.get("status", "missing"))
        score_pct = row["component_pct"]
        score_text = f"{score_pct:.0f}/100" if np.isfinite(score_pct) else "—"
        status_text = _status_label(status, str(row.get("mode", "")))
        fig.text(
            status_x,
            _data_y_to_fig_y(y_pos),
            f"{status_text}    {score_text}",
            ha="left",
            va="center",
            fontsize=11,
            color="#374151",
        )

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, facecolor="white", bbox_inches="tight", pad_inches=0.35)
    plt.close(fig)


def infer_data_type(device_type: str) -> str:
    text = normalize_device_type(device_type).lower()
    if text == "ctf":
        return "ctf"
    if text == "kit":
        return "kit"
    if text == "4d":
        return "4d"
    if text == "quanmag":
        return "quanmag"
    if text == "quspin":
        return "quspin"
    return "squid"


def self_test(config: dict, ref_df: pd.DataFrame) -> None:
    metrics = {}
    for family in config["families"]:
        for metric in family["metrics"]:
            sub = ref_df[(ref_df["metric"].astype(str) == metric) & (ref_df["scope"].astype(str) == "global")]
            if sub.empty:
                continue
            metrics[metric] = float(sub.iloc[0]["q50"])
    summary, detail = score_metrics(metrics, config, ref_df, "ALL", "ALL", "global", 1)
    if detail.empty or not np.isfinite(summary["score_0_100"]):
        raise SystemExit("self-test failed: no finite score")
    print(json.dumps({"self_test": "ok", "score_0_100": summary["score_0_100"], "n_components": int(detail["component_score_0_1"].notna().sum())}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Score one FIF file with the selected MEG QC reference-quota model.")
    parser.add_argument("--fif", type=Path, default=None, help="Input FIF file.")
    parser.add_argument("--meg-vendor", dest="meg_vendor", default="all", help="Case-insensitive MEG vendor/reference device used for lookup, e.g. elekta, ctf, kit, 4d.")
    parser.add_argument("--category", default="rest", help="Recording category, usually rest or task.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--config", type=Path, default=SCRIPT_DIR / "metric_config_reference_quota.json")
    parser.add_argument("--reference-csv", type=Path, default=SCRIPT_DIR / "reference_intervals_reference_quota.csv")
    parser.add_argument("--output-dir", type=Path, default=SCRIPT_DIR / "score_output")
    parser.add_argument("--reference-scope", default="device_category", choices=["device_category", "category", "global"])
    parser.add_argument("--min-reference-n", type=int, default=20)
    parser.add_argument(
        "--freq-max-samples",
        type=int,
        default=0,
        help="Uniform samples for frequency metrics; 0 uses the full recording and is the reference-exact default.",
    )
    parser.add_argument(
        "--dfa-max-samples",
        type=int,
        default=20000,
        help="Uniform samples only for --dfa-method sampled or msqms fallback; 0 uses full length.",
    )
    parser.add_argument("--max-samples", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--dfa-method", choices=["msqms", "sampled"], default="msqms")
    parser.add_argument("--skip-dfa", action="store_true")
    parser.add_argument(
        "--preproc-config",
        default="",
        help="Explicit YAML preprocessing config applied before scoring. No default is applied by the scorer.",
    )
    parser.add_argument(
        "--omit-bad-annotations",
        action="store_true",
        help="Drop BAD-annotated time spans before scoring (not used for the bundled reference; process_1 keeps them).",
    )
    parser.add_argument(
        "--omit-bad-channels",
        action="store_true",
        help="Exclude channels listed in raw.info['bads'] (not used for the bundled reference; process_1 keeps them).",
    )
    parser.add_argument("--n-jobs", type=int, default=1)
    parser.add_argument("--seg-length", type=int, default=100)
    parser.add_argument("--data-type", default=None, help="Compatibility option only; msqms is not imported by this standalone scorer.")
    parser.add_argument("--self-test", action="store_true", help="Run a reference-table-only smoke test without reading FIF.")
    args = parser.parse_args()

    config_all = json.loads(args.config.read_text(encoding="utf-8"))
    if args.model not in config_all["models"]:
        raise SystemExit(f"Unknown model {args.model}. Available: {', '.join(config_all['models'])}")
    config = config_all["models"][args.model]
    ref_df = pd.read_csv(args.reference_csv, low_memory=False)
    if args.self_test:
        self_test(config, ref_df)
        return
    if args.fif is None:
        raise SystemExit("--fif is required unless --self-test is used")
    if args.max_samples is not None:
        args.freq_max_samples = int(args.max_samples)
        args.dfa_max_samples = int(args.max_samples)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    mne = load_optional_mne()
    raw = mne.io.read_raw_fif(args.fif, preload=True, verbose="error")
    raw, preprocessing_steps = apply_reference_preprocessing(raw, args)
    metrics = compute_metric_values(raw, args)
    summary, detail = score_metrics(
        metrics,
        config,
        ref_df,
        args.meg_vendor,
        args.category,
        args.reference_scope,
        args.min_reference_n,
    )
    summary["reference_preprocessing"] = preprocessing_steps
    summary["bad_channel_policy"] = "omit raw.info['bads']" if args.omit_bad_channels else "keep raw.info['bads']"
    summary["bad_annotation_policy"] = "omit BAD annotations" if args.omit_bad_annotations else "keep BAD annotations"
    stem = args.fif.name
    for suffix in (".fif.gz", ".fif"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    out_prefix = args.output_dir / f"{stem}.{args.model}"
    detail.to_csv(out_prefix.with_suffix(".component_scores.csv"), index=False)
    summary_path = out_prefix.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(json_ready(summary), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    draw_reference_position_plot(
        detail,
        out_prefix.with_suffix(".reference_position.png"),
        title=f"Normative Reference MEG QC score: {fnum(summary['score_0_100'], 1)} / 100",
        subtitle=f"Model {args.model}  ·  Reference scope: {args.reference_scope}  ·  Category: {args.category}",
    )
    print(json.dumps(json_ready({"score_0_100": summary["score_0_100"], "n_families_available": summary["n_families_available"], "summary": str(summary_path)}), ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
