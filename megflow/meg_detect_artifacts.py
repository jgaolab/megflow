"""
识别MEG数据集的坏道、坏段、Jump等伪迹
运动伪迹识别：眼动、心跳、头动伪迹、哈欠等（有数据集）；

Step1：使用已有的伪迹检测算法
- autoreject
- osl
- mne
- preprep

Step2：基于MEG预训练模型做下游任务的伪迹检测、运动伪迹识别；
"""
import os
import mne
import argparse
import yaml
import logging
import numpy as np
import matplotlib as mpl
import json
import sys

mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from pathlib import Path

MEGFLOW_DIR = Path(__file__).resolve().parent
if str(MEGFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(MEGFLOW_DIR))

from osl_ephys.preprocessing.osl_wrappers import detect_badchannels, detect_badsegments
# from tools.osl.osl_wrappers import detect_badchannels, detect_badsegments
from mne.preprocessing import annotate_break,annotate_amplitude,annotate_muscle_zscore
from mne.preprocessing import find_bad_channels_lof
from tools.pyprep.find_noisy_channels import NoisyChannels
from utils import infer_artifact_vendor, set_random_seed, plot_snippets

try:
    from tools.deepreject import DeepRejectPredictor
except ImportError:  # pragma: no cover - optional dependency path
    DeepRejectPredictor = None

set_random_seed(2025)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _is_bad_annotation(description):
    return "bad" in str(description).lower()


def _annotation_to_sample_bounds(raw, onset, duration):
    raw_first_time = float(getattr(raw, "first_time", 0.0) or 0.0)
    raw_duration = float(raw.n_times / (raw.info.get("sfreq", 1.0) or 1.0))
    onset = float(onset)
    duration = float(duration)
    if raw_first_time and onset >= raw_first_time:
        shifted_onset = onset - raw_first_time
        if -1e-6 <= shifted_onset <= raw_duration + 1e-6:
            onset = shifted_onset
    try:
        start_sample, stop_sample = raw.time_as_index(
            [onset, onset + duration],
            use_rounding=True,
        )
    except Exception:
        sfreq = float(raw.info.get("sfreq", 1.0) or 1.0)
        start_sample = int(round(onset * sfreq))
        stop_sample = int(round((onset + duration) * sfreq))

    start_sample = max(0, min(int(start_sample), raw.n_times))
    stop_sample = max(0, min(int(stop_sample), raw.n_times))
    if stop_sample <= start_sample and duration > 0:
        stop_sample = min(raw.n_times, start_sample + 1)
    return start_sample, stop_sample


def plot_artifact_mask_heatmap(raw, bad_channels, output_path, max_time_bins=2400):
    """Plot a report-friendly mask of bad channels and bad time spans."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    picks = mne.pick_types(raw.info, meg=True, ref_meg=False, eeg=False, eog=False, stim=False, exclude=[])
    if len(picks) == 0:
        picks = mne.pick_types(raw.info, meg=False, eeg=True, eog=False, stim=False, exclude=[])
    if len(picks) == 0:
        excluded_types = {"stim", "eog", "ecg", "emg", "misc", "resp", "chpi", "ias", "syst", "exci"}
        picks = np.array(
            [
                idx
                for idx, channel_type in enumerate(raw.get_channel_types())
                if channel_type not in excluded_types
            ],
            dtype=int,
        )
    if len(picks) == 0 or raw.n_times <= 0:
        logger.warning("Skipping artifact mask heatmap because no plottable data channels were found.")
        return

    channel_names = [raw.ch_names[pick] for pick in picks]
    bad_channel_set = set(bad_channels or [])
    bad_channel_rows = np.array([name in bad_channel_set for name in channel_names], dtype=bool)
    n_channels = len(channel_names)
    n_bins = int(min(max_time_bins, max(240, min(raw.n_times, n_channels * 10))))
    n_bins = max(1, n_bins)
    mask = np.zeros((n_channels, n_bins), dtype=np.uint8)

    bad_segment_count = 0
    bad_segment_duration = 0.0
    for annotation in raw.annotations:
        if not _is_bad_annotation(annotation["description"]):
            continue
        start_sample, stop_sample = _annotation_to_sample_bounds(raw, annotation["onset"], annotation["duration"])
        if stop_sample <= start_sample:
            continue
        start_bin = int(np.floor(start_sample / raw.n_times * n_bins))
        stop_bin = int(np.ceil(stop_sample / raw.n_times * n_bins))
        start_bin = max(0, min(start_bin, n_bins - 1))
        stop_bin = max(start_bin + 1, min(stop_bin, n_bins))
        mask[:, start_bin:stop_bin] = np.maximum(mask[:, start_bin:stop_bin], 1)
        bad_segment_count += 1
        bad_segment_duration += float(annotation["duration"])

    if bad_channel_rows.any():
        mask[bad_channel_rows, :] = np.where(mask[bad_channel_rows, :] == 1, 3, 2)

    duration_sec = float(raw.n_times / (raw.info.get("sfreq", 1.0) or 1.0))
    raw_first_time = float(getattr(raw, "first_time", 0.0) or 0.0)
    raw_stop_time = raw_first_time + duration_sec
    time_scale = 60.0 if duration_sec >= 120 else 1.0
    time_label = "Time (min)" if time_scale == 60.0 else "Time (s)"
    extent = [raw_first_time / time_scale, raw_stop_time / time_scale, -0.5, n_channels - 0.5]

    cmap = ListedColormap(["#f8fafc", "#e11d48", "#2563eb", "#7c3aed"])
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5], cmap.N)
    figure_height = max(4.6, min(10.0, 2.3 + n_channels * 0.032))
    fig, ax = plt.subplots(figsize=(12.5, figure_height), dpi=180)

    ax.imshow(mask, aspect="auto", interpolation="nearest", origin="lower", cmap=cmap, norm=norm, extent=extent)
    ax.set_xlabel(time_label, fontsize=10, color="#334155")
    ax.set_ylabel(f"Channels (n={n_channels})", fontsize=10, color="#334155")
    max_y_ticks = 18
    if n_channels <= max_y_ticks:
        tick_idx = np.arange(n_channels)
    else:
        tick_idx = np.unique(np.linspace(0, n_channels - 1, max_y_ticks).astype(int))
    ax.set_yticks(tick_idx)
    ax.set_yticklabels([channel_names[idx] for idx in tick_idx], fontsize=7, color="#475569")
    ax.tick_params(axis="x", labelsize=8, colors="#475569")
    ax.tick_params(axis="y", labelsize=7, colors="#475569")
    ax.grid(False)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#cbd5e1")

    title = "Bad Channels and Bad Time Segments"
    subtitle = (
        f"{int(bad_channel_rows.sum())} bad channels | {bad_segment_count} bad segments | "
        f"{bad_segment_duration:.1f}s marked bad | raw.first_time={raw_first_time:.3f}s"
    )
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color="#111827", pad=22)
    ax.text(
        0,
        1.015,
        subtitle,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=8.5,
        color="#64748b",
    )

    swatches = [
        ("#e11d48", "bad segment"),
        ("#2563eb", "bad channel"),
        ("#7c3aed", "both"),
    ]
    x0 = 0.995
    y0 = 1.035
    swatch_offsets = [0.16, 0.22, 0.0]
    for idx, (color, label) in enumerate(reversed(swatches)):
        ax.text(
            x0,
            y0,
            f"■ {label}",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=9.5,
            color=color,
        )
        x0 -= swatch_offsets[idx]

    fig.subplots_adjust(left=0.085, right=0.985, top=0.88, bottom=0.16)
    fig.patch.set_facecolor("white")
    save_kwargs = {"bbox_inches": "tight", "facecolor": "white"}
    if output_path.suffix.lower() in {".jpg", ".jpeg"}:
        save_kwargs["pil_kwargs"] = {"quality": 92, "optimize": True}
    fig.savefig(output_path, **save_kwargs)
    plt.close(fig)
    logger.info(f"Artifact mask heatmap saved to {output_path}")


def read_bad_channels_file(bad_channels_file):
    bad_channels_file = Path(bad_channels_file)
    if not bad_channels_file.is_file():
        return []
    with open(bad_channels_file, "r", encoding="utf-8", errors="replace") as f:
        return [line.strip() for line in f if line.strip()]


def _record_bad_channel_sources(source_map, channels, source):
    for ch_name in channels or []:
        ch_name = str(ch_name).strip()
        if not ch_name:
            continue
        source_map.setdefault(ch_name, [])
        if source not in source_map[ch_name]:
            source_map[ch_name].append(source)


def _bad_channel_description_payload(bad_channels, source_map):
    rows = []
    for ch_name in bad_channels or []:
        sources = list(source_map.get(ch_name, []))
        if not sources:
            sources = ["Manual or pre-existing"]
        rows.append(
            {
                "channel": ch_name,
                "sources": sources,
                "description": "; ".join(sources),
            }
        )
    return {
        "schema_version": 1,
        "bad_channels": rows,
    }


def generate_artifact_mask_heatmap_from_saved_outputs(input_file, bad_channels_file, bad_segments_file, heatmap_output):
    """Generate the artifact mask heatmap from saved bad-channel and bad-segment outputs."""
    bad_channels = read_bad_channels_file(bad_channels_file)
    raw = mne.io.read_raw(input_file, preload=False)
    if Path(bad_segments_file).is_file():
        raw.set_annotations(mne.read_annotations(str(bad_segments_file)))
    raw.info["bads"] = list(dict.fromkeys(list(raw.info.get("bads", [])) + bad_channels))
    plot_artifact_mask_heatmap(raw=raw, bad_channels=bad_channels, output_path=heatmap_output)


def ensure_artifact_mask_heatmap(input_file, bad_channels_file, bad_segments_file, heatmap_output, force=False):
    heatmap_output = Path(heatmap_output)
    if heatmap_output.is_file() and not force:
        logger.info(f"Artifact mask heatmap already exists: {heatmap_output}")
        return
    try:
        logger.info("Generating artifact mask heatmap...")
        generate_artifact_mask_heatmap_from_saved_outputs(
            input_file=input_file,
            bad_channels_file=bad_channels_file,
            bad_segments_file=bad_segments_file,
            heatmap_output=heatmap_output,
        )
    except Exception as e:
        logger.error(f"Error generating artifact mask heatmap: {e}")


def find_bad_channels(raw, config, *, return_sources=False, source_map=None):
    """Detect bad channels using multiple methods."""
    bad_channels = []
    source_map = source_map if source_map is not None else {}
    if not config:
        return (bad_channels, source_map) if return_sources else bad_channels

    # PyPrep methods | slow.
    pyprep_config = config.get("pyprep", None)
    if pyprep_config:
        noisy_data = NoisyChannels(raw, random_state=2025)

        if pyprep_config.get('deviation',None):
            noisy_data.find_bad_by_deviation(**pyprep_config['deviation'])
            print("deviation",noisy_data.get_bads())
            _record_bad_channel_sources(source_map, noisy_data.bad_by_deviation, "PyPREP deviation")
        if pyprep_config.get('snr', None):
            noisy_data.find_bad_by_SNR()
            print("snr",noisy_data.get_bads())
            _record_bad_channel_sources(source_map, noisy_data.bad_by_SNR, "PyPREP SNR")

        if pyprep_config.get('nan_flat', None):
            noisy_data.find_bad_by_nan_flat()
            print("nan_flat",noisy_data.get_bads())
            _record_bad_channel_sources(source_map, noisy_data.bad_by_nan, "PyPREP NaN")
            _record_bad_channel_sources(source_map, noisy_data.bad_by_flat, "PyPREP flat")

        if pyprep_config.get('hfnoise', None):
            noisy_data.find_bad_by_hfnoise(**pyprep_config['hfnoise'])
            print("hfnoise", noisy_data.get_bads())
            _record_bad_channel_sources(source_map, noisy_data.bad_by_hf_noise, "PyPREP high-frequency noise")

        ## very slow,and comment.
        # find bad by ransac
        if pyprep_config.get('ransac', None):
            noisy_data.find_bad_by_ransac(**pyprep_config['ransac'])
            print("ransac", noisy_data.get_bads())
            _record_bad_channel_sources(source_map, noisy_data.bad_by_ransac, "PyPREP RANSAC")

        # find bad by corr
        if pyprep_config.get('correlation', None):
            noisy_data.find_bad_by_correlation(**pyprep_config['correlation'])
            print("correlation", noisy_data.get_bads())
            _record_bad_channel_sources(source_map, noisy_data.bad_by_correlation, "PyPREP correlation")
            _record_bad_channel_sources(source_map, noisy_data.bad_by_dropout, "PyPREP dropout")

        bad_channels.extend(noisy_data.get_bads())
        print("pyprep bad channels: ", bad_channels)


    # PSD method
    if config.get("psd", None):
        std_multiplier = config["psd"].get("std_multiplier",6)
        ch_names = raw.info['ch_names']
        psd = raw.compute_psd().get_data()
        ch_mean_psd = psd.mean(axis=1)
        total_mean, total_std = ch_mean_psd.mean(), ch_mean_psd.std()
        bad_psd_channels = [ch_names[i] for i in range(len(ch_mean_psd)) if ch_mean_psd[i] > (total_mean + std_multiplier * total_std)]
        bad_channels.extend(bad_psd_channels)
        _record_bad_channel_sources(source_map, bad_psd_channels, "PSD outlier")
        print("psd bad channels:", bad_psd_channels)

    # OSL methods
    osl_config = config.get("osl", None)
    if osl_config:
        _raw = raw.copy()
        _raw.info["bads"] = []
        before = set(_raw.info["bads"])
        detect_badchannels(_raw, picks='mag', **osl_config)
        mag_bads = [ch for ch in _raw.info["bads"] if ch not in before]
        _record_bad_channel_sources(source_map, mag_bads, "OSL bad-channel detector (mag)")
        try:
            before = set(_raw.info["bads"])
            detect_badchannels(_raw, picks='grad', **osl_config)
            grad_bads = [ch for ch in _raw.info["bads"] if ch not in before]
            _record_bad_channel_sources(source_map, grad_bads, "OSL bad-channel detector (grad)")
        except Exception as e:
            logger.error(e)
        bad_channels.extend(_raw.info["bads"])
        logger.info(f'osl bad channels: {_raw.info["bads"]}')

    # MNE methods
    mne_config = config.get("mne", None)
    if mne_config:
        try:
            _raw = raw.copy()
            _raw.info["bads"] = []
            find_bad_channels_lof(_raw, **mne_config.get('find_bad_channels_lof',{}))
            bad_channels.extend(_raw.info["bads"])
            _record_bad_channel_sources(source_map, _raw.info["bads"], "MNE LOF bad-channel detector")
            logger.info(f'mne bad channels: {_raw.info["bads"]}')
        except Exception as e:
            logger.error(e)
    bad_channels = list(dict.fromkeys(bad_channels))
    return (bad_channels, source_map) if return_sources else bad_channels


def find_bad_segments(raw, config):
    """Detect bad segments using OSL and MNE."""
    config = config or {}
    existing_annots = raw.annotations.copy()
    keep_existing = _config_bool(config.get("keep_existing_annotations"), False)
    empty_annots = mne.Annotations([], [], [], orig_time=existing_annots.orig_time)
    if keep_existing:
        annots = existing_annots
    else:
        if len(existing_annots):
            logger.info("Clearing %d existing raw annotations before bad-segment detection.", len(existing_annots))
        annots = empty_annots
    raw.set_annotations(empty_annots)

    if not config:
        raw.set_annotations(annots)
        return raw
    if config.get("osl",None):
        segment_len = config["osl"].get("segment_len",1000)
        try:
            raw_bad_segments = detect_badsegments(raw, picks='grad', segment_len=segment_len, detect_zeros=True)
        except Exception as e:
            logger.error(e)
            raw_bad_segments = raw

        raw_bad_segments = detect_badsegments(raw_bad_segments, picks='mag', segment_len=segment_len, ref_meg=False, detect_zeros=True)
        annots = raw_bad_segments.annotations + annots

    mne_config = config.get("mne",None)
    if mne_config:
        try:
            if mne_config.get("annotate_muscle_zscore"):
                annot_muscle, scores_muscle = annotate_muscle_zscore(raw,**mne_config.get("annotate_muscle_zscore"))
                annots = annots + annot_muscle
            if mne_config.get("annotate_break"):
                logger.info(mne_config.get("annotate_break"))
                annot_break = mne.preprocessing.annotate_break(raw=raw,**mne_config.get("annotate_break"))
                annots = annots + annot_break
            if mne_config.get("annotate_amplitude"):
                annot_amplitude, _ = annotate_amplitude(raw,**mne_config.get("annotate_amplitude"))
                annots = annots + annot_amplitude
        except Exception as e:
            logger.error(e)
    raw.set_annotations(annots)
    return raw


def _infer_deepreject_category(raw_path, requested):
    requested = str(requested or "auto").strip().lower()
    if requested and requested != "auto":
        return requested
    text = Path(raw_path).name.lower()
    if "rest" in text or "closedeye" in text or "openeye" in text:
        return "rest"
    return "task"


def _optional_float(value):
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"none", "null"}:
        return None
    return float(value)


def _optional_int(value):
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"none", "null"}:
        return None
    return int(value)


def _positive_int_preference(value, field_name):
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"", "auto", "none", "null"}:
        return None
    parsed = int(value)
    if parsed < 1:
        raise ValueError(f"{field_name} must be a positive integer or 'auto'")
    return parsed


def _runtime_cpu_budget(value):
    parsed = _positive_int_preference(value, "runtime_cpus")
    return parsed if parsed is not None else max(1, int(os.cpu_count() or 1))


def _resolve_deepreject_parallelism(
    *,
    runtime_cpus,
    fold_workers="auto",
    cpu_threads="auto",
    folds=None,
):
    """Resolve fold workers and Torch threads within one task CPU budget."""
    budget = _runtime_cpu_budget(runtime_cpus)
    fold_count = len(folds) if folds else 5
    fold_count = max(1, int(fold_count))
    preferred_workers = _positive_int_preference(fold_workers, "fold_workers")
    preferred_threads = _positive_int_preference(cpu_threads, "cpu_threads")

    if (
        preferred_workers is not None
        and preferred_threads is not None
        and preferred_workers <= fold_count
        and preferred_workers * preferred_threads <= budget
    ):
        return preferred_workers, preferred_threads

    max_workers = min(fold_count, preferred_workers or fold_count, budget)
    max_threads = min(preferred_threads or budget, budget)
    target_threads = preferred_threads or 4
    target_workers = preferred_workers or fold_count
    candidates = [
        (workers, threads)
        for workers in range(1, max_workers + 1)
        for threads in range(1, max_threads + 1)
        if workers * threads <= budget
    ]
    return max(
        candidates,
        key=lambda pair: (
            pair[0] * pair[1],
            -abs(pair[1] - target_threads),
            -abs(pair[0] - target_workers),
            pair[0],
        ),
    )


def _resolve_artifact_image_n_jobs(*, requested, runtime_cpus):
    """Resolve detailed-image workers without exceeding task CPUs."""
    budget = _runtime_cpu_budget(runtime_cpus)
    preferred = _positive_int_preference(requested, "artifact_image_n_jobs")
    return min(preferred or budget, budget)


def _config_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
        return False
    return bool(value)


def _parse_deepreject_folds(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [int(item) for item in value]
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    return [int(item.strip()) for item in text.split(",") if item.strip()]


DEEPREJECT_MODE_PRESETS = {
    "default": {},
    "strict": {
        "badsegnet_hysteresis_high": 0.85,
        "badsegnet_hysteresis_low": 0.15,
        "badsegnet_merge_gap_sec": 10.0,
        "badsegnet_min_duration_sec": 0.0,
        "badsegnet_short_keep_threshold": 0.95,
    },
    "lenient": {
        "badsegnet_hysteresis_high": 0.99,
        "badsegnet_hysteresis_low": 0.95,
        "badsegnet_merge_gap_sec": 0.0,
        "badsegnet_min_duration_sec": 0.0,
        "badsegnet_short_keep_threshold": 1.0,
    },
}

DEEPREJECT_RECOMMENDED_INPUT = {
    "highpass_hz": 1.0,
    "lowpass_hz": 100.0,
    "sfreq_hz": 250.0,
}


def _resolve_deepreject_mode_config(deep_config):
    mode_value = deep_config.get("mode", deep_config.get("profile", "default"))
    mode = "default" if mode_value is None else str(mode_value).strip().lower()
    if mode in {"", "none", "null"}:
        mode = "default"
    if mode not in DEEPREJECT_MODE_PRESETS:
        supported = ", ".join(sorted(DEEPREJECT_MODE_PRESETS))
        raise ValueError(f"Unsupported DeepReject mode '{mode_value}'. Supported modes: {supported}")

    resolved = dict(DEEPREJECT_MODE_PRESETS[mode])
    resolved.update(deep_config)
    resolved["mode"] = mode
    return mode, resolved, dict(DEEPREJECT_MODE_PRESETS[mode])


def _deepreject_input_preprocessing_summary(raw, deep_config):
    actual_highpass = float(raw.info.get("highpass", 0.0) or 0.0)
    actual_lowpass = float(raw.info.get("lowpass", 0.0) or 0.0)
    actual_sfreq = float(raw.info.get("sfreq", 0.0) or 0.0)
    requested_highpass = _optional_float(deep_config.get("filter_l_freq"))
    requested_lowpass = _optional_float(deep_config.get("filter_h_freq"))
    requested_sfreq = _optional_float(deep_config.get("resample_sfreq"))

    effective_highpass = (
        max(actual_highpass, requested_highpass)
        if requested_highpass is not None
        else actual_highpass
    )
    effective_lowpass = (
        min(actual_lowpass, requested_lowpass)
        if requested_lowpass is not None
        else actual_lowpass
    )
    effective_sfreq = requested_sfreq if requested_sfreq is not None else actual_sfreq
    recommended = DEEPREJECT_RECOMMENDED_INPUT
    matches = (
        np.isclose(effective_highpass, recommended["highpass_hz"], atol=0.05, rtol=0.0)
        and np.isclose(effective_lowpass, recommended["lowpass_hz"], atol=0.05, rtol=0.0)
        and np.isclose(effective_sfreq, recommended["sfreq_hz"], atol=0.1, rtol=0.0)
    )

    irreversible = []
    if actual_highpass > recommended["highpass_hz"] + 0.05:
        irreversible.append("input high-pass is above 1 Hz")
    if actual_lowpass < recommended["lowpass_hz"] - 0.05:
        irreversible.append("input low-pass is below 100 Hz")
    if actual_sfreq < recommended["sfreq_hz"] - 0.1:
        irreversible.append("input sampling rate is below 250 Hz")

    summary = {
        "actual": {
            "highpass_hz": actual_highpass,
            "lowpass_hz": actual_lowpass,
            "sfreq_hz": actual_sfreq,
        },
        "requested_internal_preproc": {
            "highpass_hz": requested_highpass,
            "lowpass_hz": requested_lowpass,
            "sfreq_hz": requested_sfreq,
        },
        "effective": {
            "highpass_hz": effective_highpass,
            "lowpass_hz": effective_lowpass,
            "sfreq_hz": effective_sfreq,
        },
        "recommended": dict(recommended),
        "recommended_input_match": bool(matches),
        "irreversible_mismatches": irreversible,
    }
    if matches:
        logger.info(
            "DeepReject input preprocessing matches the recommended 1-100 Hz at 250 Hz."
        )
    else:
        details = f" Irreversible mismatch: {'; '.join(irreversible)}." if irreversible else ""
        logger.warning(
            "DeepReject input preprocessing differs from the recommended 1-100 Hz at 250 Hz: "
            "effective highpass=%.3g Hz, lowpass=%.3g Hz, sfreq=%.3g Hz.%s",
            effective_highpass,
            effective_lowpass,
            effective_sfreq,
            details,
        )
    return summary


def _select_deepreject_channels(raw, *, exclude_marked_bads=False):
    exclude = "bads" if exclude_marked_bads else []
    picks = mne.pick_types(
        raw.info,
        meg=True,
        ref_meg=False,
        eeg=False,
        eog=False,
        ecg=False,
        emg=False,
        stim=False,
        misc=False,
        exclude=exclude,
    )
    if len(picks) == 0:
        raise RuntimeError("DeepReject requested data-MEG-only input, but no usable MEG channels were found.")
    return [raw.ch_names[pick] for pick in picks]


def _prepare_deepreject_input(raw, input_path, output_dir, deep_config):
    pick_meg_only = _config_bool(deep_config.get("pick_meg_only"), True)
    if not pick_meg_only:
        return Path(input_path), None, {
            "pick_meg_only": False,
            "input_path": str(input_path),
            "prediction_input_path": str(input_path),
            "input_channel_count": len(raw.ch_names),
            "prediction_channel_count": len(raw.ch_names),
        }

    exclude_marked_bads = _config_bool(deep_config.get("pick_exclude_marked_bads"), False)
    channel_names = _select_deepreject_channels(raw, exclude_marked_bads=exclude_marked_bads)
    tmp_path = Path(output_dir) / f"{Path(input_path).stem}_deepreject_meg_only_raw.fif"
    raw.copy().pick(channel_names).save(tmp_path, overwrite=True)
    return tmp_path, tmp_path, {
        "pick_meg_only": True,
        "pick_exclude_marked_bads": exclude_marked_bads,
        "input_path": str(input_path),
        "prediction_input_path": str(tmp_path),
        "input_channel_count": len(raw.ch_names),
        "prediction_channel_count": len(channel_names),
        "prediction_channels": channel_names,
    }


def _merge_annotations(base_annotations, extra_annotations):
    if len(extra_annotations) == 0:
        return base_annotations
    if len(base_annotations) == 0:
        return extra_annotations
    return base_annotations + extra_annotations


def run_deepreject_detection(raw, input_path, config, output_dir):
    """Run optional DeepReject detection and return bad channels plus annotations."""
    deep_config = config.get("deepreject") or {}
    if not deep_config or not deep_config.get("enabled", False):
        return [], mne.Annotations([], [], []), None
    deepreject_mode, deep_config, deepreject_mode_preset = _resolve_deepreject_mode_config(deep_config)
    input_preprocessing_summary = _deepreject_input_preprocessing_summary(raw, deep_config)

    if DeepRejectPredictor is None:
        raise RuntimeError("DeepReject runtime is not importable. Install its dependencies or disable artifacts.deepreject.enabled.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    category = _infer_deepreject_category(input_path, deep_config.get("category", "auto"))
    dataset = deep_config.get("dataset") or Path(input_path).parent.name

    predictor_kwargs = {
        "device": deep_config.get("device", "cpu"),
    }
    folds = _parse_deepreject_folds(deep_config.get("folds"))
    if folds:
        predictor_kwargs["folds"] = folds
    runtime_cpus = _runtime_cpu_budget(config.get("runtime_cpus"))
    fold_workers, cpu_threads = _resolve_deepreject_parallelism(
        runtime_cpus=runtime_cpus,
        fold_workers=deep_config.get("fold_workers", "auto"),
        cpu_threads=deep_config.get("cpu_threads", "auto"),
        folds=folds,
    )
    predictor_kwargs.update(
        fold_workers=fold_workers,
        cpu_threads=cpu_threads,
        cpu_interop_threads=1,
    )
    for key in (
        "badsegnet_batch_size",
        "badsegnet_encoder_chunk_size",
        "badsegnet_edge_k",
        "badchnnet_chunk_windows",
        "badchnnet_chunk_stride",
        "badchnnet_min_chunk_windows",
    ):
        value = _optional_int(deep_config.get(key))
        if value is not None:
            predictor_kwargs[key] = value

    for key in (
        "badsegnet_hysteresis_high",
        "badsegnet_hysteresis_low",
        "badsegnet_merge_gap_sec",
        "badsegnet_min_duration_sec",
        "badsegnet_short_keep_threshold",
        "badchnnet_lambda_lcb",
        "badchnnet_floor",
        "badchnnet_z",
    ):
        value = _optional_float(deep_config.get(key))
        if value is not None:
            predictor_kwargs[key] = value
    min_type_channels = _optional_int(deep_config.get("badchnnet_min_type_channels"))
    if min_type_channels is not None:
        predictor_kwargs["badchnnet_min_type_channels"] = min_type_channels

    if deep_config.get("badchnnet_chunk_prob_aggregation") is not None:
        predictor_kwargs["badchnnet_chunk_prob_aggregation"] = str(deep_config.get("badchnnet_chunk_prob_aggregation"))

    if deep_config.get("cache_models") is not None:
        predictor_kwargs["cache_models"] = _config_bool(deep_config.get("cache_models"), True)

    prediction_input_path, temporary_input_path, input_summary = _prepare_deepreject_input(
        raw=raw,
        input_path=input_path,
        output_dir=output_dir,
        deep_config=deep_config,
    )

    predictor = DeepRejectPredictor(**predictor_kwargs)
    pred = predictor.predict_fif(
        Path(prediction_input_path),
        category=category,
        dataset=dataset,
        pick_exclude_marked_bads=_config_bool(deep_config.get("pick_exclude_marked_bads"), False),
        filter_l_freq=_optional_float(deep_config.get("filter_l_freq")),
        filter_h_freq=_optional_float(deep_config.get("filter_h_freq")),
        resample_sfreq=_optional_float(deep_config.get("resample_sfreq")),
        run_bad_segments=_config_bool(deep_config.get("run_bad_segments"), True),
        run_bad_channels=_config_bool(deep_config.get("run_bad_channels"), True),
    )

    bad_channels = [
        ch_name
        for ch_name, is_bad in zip(pred.ch_names, np.asarray(pred.bad_channel_pred).reshape(-1))
        if int(is_bad) == 1
    ]

    annotation_offset_sec = float(getattr(raw, "first_time", 0.0) or 0.0)
    annots = mne.Annotations(
        onset=[float(start) + annotation_offset_sec for start, _ in pred.bad_intervals],
        duration=[max(0.0, float(stop) - float(start)) for start, stop in pred.bad_intervals],
        description=["BAD_deepreject"] * len(pred.bad_intervals),
        orig_time=raw.annotations.orig_time,
    )

    summary = {
        "enabled": True,
        "backend": pred.backend,
        "badsegnet_weights_dir": str(getattr(predictor, "badsegnet_weights_dir", "")),
        "badchnnet_weights_dir": str(getattr(predictor, "badchnnet_weights_dir", "")),
        "artifact_folds": np.asarray(pred.artifact_folds).astype(int).tolist(),
        "bad_channel_folds": np.asarray(pred.bad_channel_folds).astype(int).tolist(),
        "fold_workers": getattr(predictor, "fold_workers", None),
        "cache_models": getattr(predictor, "cache_models", None),
        "cpu_threads": getattr(predictor, "cpu_threads", None),
        "cpu_interop_threads": getattr(predictor, "cpu_interop_threads", None),
        "runtime_cpus": runtime_cpus,
        "mode": deepreject_mode,
        "mode_preset_parameters": deepreject_mode_preset,
        "category": category,
        "dataset": dataset,
        "input_preprocessing": input_preprocessing_summary,
        "artifact_window_count": int(np.asarray(pred.artifact_probs).size),
        "badsegnet_hysteresis_high": getattr(predictor, "badsegnet_hysteresis_high", None),
        "badsegnet_hysteresis_low": getattr(predictor, "badsegnet_hysteresis_low", None),
        "badsegnet_merge_gap_sec": getattr(predictor, "badsegnet_merge_gap_sec", None),
        "badsegnet_min_duration_sec": getattr(predictor, "badsegnet_min_duration_sec", None),
        "badsegnet_short_keep_threshold": getattr(predictor, "badsegnet_short_keep_threshold", None),
        "badchnnet_lambda_lcb": getattr(predictor, "badchnnet_lambda_lcb", None),
        "badchnnet_floor": getattr(predictor, "badchnnet_floor", None),
        "badchnnet_z": getattr(predictor, "badchnnet_z", None),
        "badchnnet_min_type_channels": getattr(predictor, "badchnnet_min_type_channels", None),
        "bad_interval_count": len(pred.bad_intervals),
        "annotation_onset_offset_sec": annotation_offset_sec,
        "bad_intervals": [{"onset_sec": float(s), "stop_sec": float(e), "duration_sec": float(e - s)} for s, e in pred.bad_intervals],
        "bad_channel_count": len(bad_channels),
        "bad_channels": bad_channels,
    }
    summary.update(input_summary)
    if pred.bad_channel_probs is not None and pred.ch_names:
        summary["bad_channel_probs"] = {
            ch_name: float(prob)
            for ch_name, prob in zip(pred.ch_names, np.asarray(pred.bad_channel_probs).reshape(-1))
        }
    with open(output_dir / "deepreject_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.info(
        "DeepReject detected %d bad channels and %d bad intervals using backend=%s",
        len(bad_channels),
        len(pred.bad_intervals),
        pred.backend,
    )
    if temporary_input_path is not None and not _config_bool(deep_config.get("keep_meg_only_input"), False):
        try:
            temporary_input_path.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("Could not remove temporary DeepReject MEG-only file %s: %s", temporary_input_path, exc)
    return bad_channels, annots, summary
    
def main(args):
    logger.info("args.input: %s", args.input)

    # Parse YAML configuration
    config = yaml.safe_load(args.config) or {}

    base_name = Path(args.input).stem
    output_bad_segments_file = f"{args.output}/{base_name}_bad_segments.txt"
    output_bad_channels_file = f"{args.output}/{base_name}_bad_channels.txt"
    output_bad_channel_description_file = f"{args.output}/{base_name}_bad_channels_description.json"
    check_imgs_output_dir = Path(output_bad_channels_file).parent / "check_imgs"
    heatmap_img_out = check_imgs_output_dir / "artifact_mask_heatmap.jpg"
    artifact_images_enabled = _config_bool(config.get('artifact_images_enabled'), False)
    runtime_cpus = _runtime_cpu_budget(config.get("runtime_cpus"))
    artifact_image_n_jobs = _resolve_artifact_image_n_jobs(
        requested=config.get("artifact_image_n_jobs", "auto"),
        runtime_cpus=runtime_cpus,
    )

    if os.path.exists(output_bad_segments_file) and os.path.exists(output_bad_channels_file):
        logger.info(f"The file {output_bad_segments_file}/{output_bad_channels_file} already exists, and the data will not be overwritten.")
        ensure_artifact_mask_heatmap(
            input_file=args.input,
            bad_channels_file=output_bad_channels_file,
            bad_segments_file=output_bad_segments_file,
            heatmap_output=heatmap_img_out,
            force=True,
        )
    else:
        raw = mne.io.read_raw(args.input, preload=True)
        artifact_vendor = infer_artifact_vendor(raw, config.get('meg_vendor', 'auto'))
        if artifact_vendor:
            logger.info("Resolved MEG artifact vendor for plots: %s", artifact_vendor)
        else:
            logger.warning("Could not infer MEG artifact vendor; using generic MNE scaling for plots.")

        bad_channel_sources = {}
        _record_bad_channel_sources(bad_channel_sources, raw.info.get("bads", []), "Pre-existing raw.info['bads']")

        # Detect bad channels
        bad_channels, bad_channel_sources = find_bad_channels(
            raw,
            config.get('find_bad_channels', {}),
            return_sources=True,
            source_map=bad_channel_sources,
        )
        raw.info['bads'].extend(bad_channels)
        current_bad_channels = set(raw.info['bads'])
        raw.info['bads'] = sorted(current_bad_channels)
        logger.info(f"raw.info['bads']:{raw.info['bads']}")

        # Detect bad segments
        raw = find_bad_segments(raw, config.get('find_bad_segments', {}))

        deep_config = config.get("deepreject") or {}
        if deep_config.get("enabled", False):
            try:
                deep_bad_channels, deep_annots, _ = run_deepreject_detection(
                    raw=raw,
                    input_path=args.input,
                    config=config,
                    output_dir=args.output,
                )
                _record_bad_channel_sources(bad_channel_sources, deep_bad_channels, "DeepReject BadChnNet")
                raw.info["bads"] = sorted(set(list(raw.info.get("bads", [])) + list(deep_bad_channels)))
                raw.set_annotations(_merge_annotations(raw.annotations, deep_annots))
            except Exception as exc:
                on_error = str(deep_config.get("on_error", "warn")).strip().lower()
                logger.exception("DeepReject detection failed: %s", exc)
                if on_error in {"raise", "error", "fail"}:
                    raise

        if not os.path.exists(f"{args.output}"):
            os.makedirs(f"{args.output}")

        # Save results
        raw.annotations.save(output_bad_segments_file, overwrite=True)
        logger.info(f"raw.annotations[bad segments]:{raw.annotations}")

        interpolated_bads = False
        if config.get('interpolate_bads', False) and raw.info['bads']:
            logger.info(f"Interpolating bad channels: {raw.info['bads']}")
            raw.interpolate_bads(reset_bads=True)
            interpolated_bads = True
            logger.info("Bad channels were interpolated and reset in raw.info['bads'].")

        bad_channels = list(raw.info['bads'])
        with open(output_bad_channels_file, 'w') as f:
            for bad_channel in bad_channels:
                f.write(f"{bad_channel}\n")
        with open(output_bad_channel_description_file, "w", encoding="utf-8") as f:
            json.dump(
                _bad_channel_description_payload(bad_channels, bad_channel_sources),
                f,
                ensure_ascii=False,
                indent=2,
            )

        try:
            if (args.annot and (raw.info['bads'] or raw.annotations)) or interpolated_bads:
                logger.info(f"Adding artifact information into {args.input}")
                raw.save(f"{args.input}", overwrite=True)
        except Exception as e:
            logger.error(f"Error overwriting:{args.input}...,\n {e}")

        ensure_artifact_mask_heatmap(
            input_file=args.input,
            bad_channels_file=output_bad_channels_file,
            bad_segments_file=output_bad_segments_file,
            heatmap_output=heatmap_img_out,
            force=True,
        )

        if artifact_images_enabled:
            # Generate detailed artifacts check images.
            device_type = artifact_vendor
            seg_fname_img_out = Path(f"{check_imgs_output_dir}/waveform/chn.#/seg_$.jpg")
            seg_fname_chn_out = Path(f"{check_imgs_output_dir}/waveform/channels.jl")
            summary_fname_img_out = Path(f"{check_imgs_output_dir}/overview/chn.#/seg_$.jpg")
            summary_fname_chn_out = Path(f"{check_imgs_output_dir}/overview/channels.jl")

            try:
                logger.info("Generating summary anv waveform...")
                # plot segments
                plot_snippets(
                    fname_fif=args.input,
                    fname_bad_chn=output_bad_channels_file,
                    fname_bad_seg=output_bad_segments_file,
                    fname_img_out=seg_fname_img_out,
                    fname_chn_out=seg_fname_chn_out,
                    device_type=device_type,
                    segment_type="segment",
                    n_chans=30,
                    duration=60,
                    n_jobs=artifact_image_n_jobs,
                )

                # plot summary
                plot_snippets(
                    fname_fif=args.input,
                    fname_bad_chn=output_bad_channels_file,
                    fname_bad_seg=output_bad_segments_file,
                    fname_img_out=summary_fname_img_out,
                    fname_chn_out=summary_fname_chn_out,
                    device_type=device_type,
                    segment_type="summary",
                    duration=200,
                    n_jobs=artifact_image_n_jobs,
                )
            except Exception as e:
                logger.error(e)



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Artifact Detection for MEG Data")
    parser.add_argument("--input", required=True, help="Path to input MEG data file")
    parser.add_argument("--output", required=True, default='.', help="Output directory for results")
    parser.add_argument("--annot", action="store_true", help="Enable annotation saving with MEG raw data")
    parser.add_argument('--config', type=str, default="{}", help='Path to the YAML configuration file')

    args = parser.parse_args()

    # debug
    # args.config =  """
    #     find_bad_channels:
    #         pyprep:
    #             deviation:
    #                 deviation_threshold: 5.0
    #             snr: {}
    #             nan_flat: {}
    #         psd:
    #             std_multiplier: 6
    #         osl:
    #             ref_meg: auto
    #             significance_level: 0.05
    #
    #     find_bad_segments:
    #         osl:
    #             segment_len: 1000 # detect_badsegments
    #         mne:
    #             annotate_muscle_zscore:
    #                 ch_type: mag
    #                 threshold: 12
    #
    #     artifact_images_enabled: true
    #     meg_vendor: auto # auto, 'ctf', 'elekta', '4d', 'kit', 'opm', ''
    # """

    main(args)
