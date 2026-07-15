#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import mne
import logging
import matplotlib.pyplot as plt
import numpy as np
import re
from mne.minimum_norm import apply_inverse, make_inverse_operator
from mne.minimum_norm import apply_inverse_raw
from mne.beamformer import apply_lcmv_raw
from mne.beamformer import apply_lcmv, make_lcmv
from mne.viz.ui_events import VertexSelect, publish
import argparse
from utils import (
    MegflowConfigurationError,
    RANK_NOT_SET,
    RankConfigurationError,
    handle_yaml_scientific_notation,
    normalize_mne_rank,
    normalize_source_methods,
    ranked_mne_kwargs,
    resolve_rank_policy,
    stop_xvfb,
    start_xvfb,
    set_random_seed,
    str2bool,
)
import yaml
from pathlib import Path
import gc
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

set_random_seed(2025)


ROI_ALIASES = {
    "temporal": [
        "bankssts",
        "entorhinal",
        "fusiform",
        "inferiortemporal",
        "middletemporal",
        "parahippocampal",
        "superiortemporal",
        "temporalpole",
        "transversetemporal",
    ],
    "auditory": [
        "superiortemporal",
        "transversetemporal",
    ],
    "occipital": [
        "cuneus",
        "lateraloccipital",
        "lingual",
        "pericalcarine",
    ],
    "visual": [
        "cuneus",
        "lateraloccipital",
        "lingual",
        "pericalcarine",
    ],
    "parietal": [
        "inferiorparietal",
        "precuneus",
        "superiorparietal",
        "supramarginal",
    ],
    "frontal": [
        "caudalmiddlefrontal",
        "frontalpole",
        "lateralorbitofrontal",
        "medialorbitofrontal",
        "parsopercularis",
        "parsorbitalis",
        "parstriangularis",
        "precentral",
        "rostralmiddlefrontal",
        "superiorfrontal",
    ],
    "motor": [
        "precentral",
        "postcentral",
    ],
}

VENTRAL_VIEW_LABELS = {
    "entorhinal",
    "fusiform",
    "lateralorbitofrontal",
    "lingual",
    "medialorbitofrontal",
    "parahippocampal",
    "temporalpole",
}

MEDIAL_VIEW_LABELS = {
    "cuneus",
    "paracentral",
    "pericalcarine",
    "posteriorcingulate",
    "precuneus",
    "rostralanteriorcingulate",
    "caudalanteriorcingulate",
}


def _safe_slug(value):
    value = "" if value is None else str(value)
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    value = value.strip("_.-")
    return value or "source_view"


def _as_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _normalize_hemi_list(value):
    if value is None:
        return ["lh", "rh"]
    if isinstance(value, str):
        hemi = value.strip().lower()
        if hemi in {"both", "all"}:
            return ["lh", "rh"]
        if hemi in {"lh", "left"}:
            return ["lh"]
        if hemi in {"rh", "right"}:
            return ["rh"]
        logger.warning("Unknown hemi value '%s'; using both hemispheres.", value)
        return ["lh", "rh"]
    if isinstance(value, (list, tuple, set)):
        hemis = []
        for item in value:
            hemis.extend(_normalize_hemi_list(item))
        return [h for h in ["lh", "rh"] if h in hemis]
    return ["lh", "rh"]


def _infer_visualization_mode(selection):
    mode = selection.get("mode")
    if mode:
        mode = str(mode).strip().lower().replace("-", "_")
        if mode in {"roi", "label", "region", "label_time", "time_label", "time_roi", "roi_time"}:
            return "label"
        if mode in {"vertex", "vertex_time", "time_vertex"}:
            logger.warning(
                "Numeric vertex source visualization is not exposed as a user-facing option; using peak mode."
            )
            return "peak"
        if mode in {"peak", "time"}:
            return mode
        logger.warning("Unknown source visualization mode '%s'; using peak mode.", mode)
        return "peak"

    if selection.get("label") is not None or selection.get("roi") is not None or selection.get("region") is not None:
        return "label"
    if selection.get("time") is not None:
        return "time"
    return "peak"


def _source_visualization_selections(config):
    visualization = {}
    if isinstance(config, dict):
        visualization = config.get("visualization") or {}

    if isinstance(visualization, list):
        selections = visualization
        defaults = {}
    elif isinstance(visualization, dict):
        defaults = {k: v for k, v in visualization.items() if k != "selections"}
        selections = visualization.get("selections")
        if selections is None:
            selections = [defaults] if defaults else [{"mode": "peak"}]
    else:
        defaults = {}
        selections = [{"mode": "peak"}]

    if not isinstance(selections, list):
        selections = [selections]

    normalized = []
    for item in selections:
        if item is None:
            continue
        if isinstance(item, str):
            item = {"mode": item}
        if not isinstance(item, dict):
            logger.warning("Ignoring invalid source visualization selection: %s", item)
            continue
        merged = dict(defaults)
        merged.update(item)
        merged["mode"] = _infer_visualization_mode(merged)
        merged.pop("vertex", None)
        normalized.append(merged)

    return normalized or [{"mode": "peak"}]


def _nearest_time_index(stc, requested_time):
    if requested_time is None:
        return None, None
    requested_time = float(requested_time)
    idx = int(np.argmin(np.abs(stc.times - requested_time)))
    return idx, float(stc.times[idx])


def _hemi_data(stc, hemi):
    if hemi == "lh":
        return stc.lh_data, np.asarray(stc.vertices[0], dtype=int)
    return stc.rh_data, np.asarray(stc.vertices[1], dtype=int)


def _label_name_key(label_name):
    key = label_name.lower()
    key = re.sub(r"-(lh|rh)$", "", key)
    key = key.replace("_", "")
    key = key.replace("-", "")
    return key


def _candidate_vertices_from_roi(subject, subjects_dir, hemi, roi_name, parc):
    if not roi_name:
        return None

    roi_key = _label_name_key(str(roi_name))
    target_names = ROI_ALIASES.get(roi_key, [roi_key])
    target_names = {_label_name_key(name) for name in target_names}

    try:
        labels = mne.read_labels_from_annot(
            subject=subject,
            parc=parc,
            hemi=hemi,
            subjects_dir=subjects_dir,
            verbose=False,
        )
    except Exception as exc:
        logger.warning(
            "Could not read %s labels for subject %s (%s); source visualization will use the full %s hemisphere.",
            parc,
            subject,
            exc,
            hemi,
        )
        return None

    matched_vertices = []
    matched_labels = []
    for label in labels:
        label_key = _label_name_key(label.name)
        if label_key in target_names:
            matched_vertices.extend(label.vertices.tolist())
            matched_labels.append(label.name)

    if not matched_vertices:
        logger.warning(
            "No %s labels matched ROI '%s' for subject %s; source visualization will use the full %s hemisphere.",
            parc,
            roi_name,
            subject,
            hemi,
        )
        return None

    logger.info("Source visualization ROI '%s' matched labels for %s: %s", roi_name, hemi, ", ".join(matched_labels))
    return np.asarray(sorted(set(matched_vertices)), dtype=int)


def _vertex_anatomical_label(subject, subjects_dir, hemi, vertex, parc):
    try:
        labels = mne.read_labels_from_annot(
            subject=subject,
            parc=parc,
            hemi=hemi,
            subjects_dir=subjects_dir,
            verbose=False,
        )
    except Exception as exc:
        logger.warning("Could not identify the anatomical label for %s vertex %s: %s", hemi, vertex, exc)
        return None

    for label in labels:
        if np.any(label.vertices == int(vertex)):
            return label.name
    return None


def _default_surface_view(anatomical_label):
    if not anatomical_label:
        return "lateral"
    label_key = _label_name_key(anatomical_label)
    if label_key in VENTRAL_VIEW_LABELS:
        return "ventral"
    if label_key in MEDIAL_VIEW_LABELS:
        return "medial"
    return "lateral"


def _selection_display_name(selection):
    if selection.get("name"):
        return str(selection["name"])

    mode = selection.get("mode", "peak")
    parts = [mode]
    roi_name = selection.get("roi") or selection.get("label") or selection.get("region")
    if roi_name:
        parts.append(str(roi_name))
    if selection.get("time") is not None:
        parts.append(f"{float(selection['time']) * 1000:.0f}ms")
    return "_".join(parts)


def _is_default_peak_selection(selection):
    custom_keys = set(selection) - {"mode", "hemi", "hemis", "time_viewer", "show_traces", "clim", "views",
                                    "smoothing_steps", "foci_color", "foci_scale_factor", "foci_alpha"}
    return selection.get("mode") == "peak" and not custom_keys


def _select_source_vertex_and_time(stc, subject, subjects_dir, hemi, selection):
    mode = selection.get("mode", "peak")
    requested_time = selection.get("time")
    roi_name = selection.get("roi") or selection.get("label") or selection.get("region")
    parc = selection.get("parc", "aparc")

    if mode == "peak":
        vertex, peak_time = stc.get_peak(hemi=hemi)
        return int(vertex), float(peak_time), "peak"

    data, vertices = _hemi_data(stc, hemi)
    if data.size == 0 or len(vertices) == 0:
        raise RuntimeError(f"No source data found for {hemi}.")

    time_idx, actual_time = _nearest_time_index(stc, requested_time)

    candidate_mask = np.ones(len(vertices), dtype=bool)
    if mode == "label":
        roi_vertices = _candidate_vertices_from_roi(subject, subjects_dir, hemi, roi_name, parc)
        if roi_vertices is not None:
            candidate_mask = np.isin(vertices, roi_vertices)
            if not candidate_mask.any():
                logger.warning(
                    "ROI '%s' labels contain no vertices used by the %s source space; using the full hemisphere.",
                    roi_name,
                    hemi,
                )
                candidate_mask = np.ones(len(vertices), dtype=bool)

    candidate_indices = np.where(candidate_mask)[0]
    if time_idx is not None:
        local_idx = int(np.nanargmax(np.abs(data[candidate_indices, time_idx])))
        vertex_idx = int(candidate_indices[local_idx])
        return int(vertices[vertex_idx]), actual_time, "configured time"

    local_flat_idx = int(np.nanargmax(np.abs(data[candidate_indices, :])))
    local_vertex_idx, time_idx = np.unravel_index(local_flat_idx, (len(candidate_indices), data.shape[1]))
    vertex_idx = int(candidate_indices[local_vertex_idx])
    return int(vertices[vertex_idx]), float(stc.times[time_idx]), "configured ROI"


def _set_time_viewer_vertex(brain, hemi, vertex):
    """Replace MNE's automatic full-brain pick with the configured vertex."""
    if not getattr(brain, "time_viewer", False) or not getattr(brain, "show_traces", False):
        return False

    vertex = int(vertex)
    try:
        rms_line = getattr(brain, "rms", None)
        rms_data = None
        if rms_line is not None:
            rms_data = {
                "x": np.asarray(rms_line.get_xdata()).copy(),
                "y": np.asarray(rms_line.get_ydata()).copy(),
                "label": rms_line.get_label(),
                "lw": rms_line.get_linewidth(),
                "color": rms_line.get_color(),
                "alpha": rms_line.get_alpha(),
                "ls": rms_line.get_linestyle(),
                "zorder": rms_line.get_zorder(),
            }
        brain.clear_glyphs()
        if rms_data is not None:
            brain.rms = brain.mpl_canvas.plot(
                rms_data.pop("x"),
                rms_data.pop("y"),
                update=False,
                **rms_data,
            )
        publish(brain, VertexSelect(hemi=hemi, vertex_id=vertex))
        picked_points = brain.get_picked_points() or {}
        if vertex not in picked_points.get(hemi, []):
            raise RuntimeError("MNE time viewer did not retain the configured vertex")
    except Exception as exc:
        logger.warning(
            "Could not set the MNE time viewer to %s vertex %s (%s); using a static focus marker.",
            hemi,
            vertex,
            exc,
        )
        return False

    return True


class SourceConfigurationError(MegflowConfigurationError):
    """Raised for deterministic source configuration or routing errors."""


def _mapping(value, config_name):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SourceConfigurationError(f"{config_name} must be a mapping.")
    return dict(value)


def _pick_source_data(inst, data_type):
    selected = inst.copy().pick(data_type or "meg")
    bads = set(selected.info.get("bads", []))
    good_channels = [name for name in selected.ch_names if name not in bads]
    if not good_channels:
        raise SourceConfigurationError(
            f"Source input has no usable {data_type or 'meg'} channels."
        )
    selected.pick(good_channels)
    selected.info["bads"] = []
    return selected


def _covariance_channel_names(covariance):
    names = getattr(covariance, "ch_names", None)
    if names is None:
        names = covariance.get("names", [])
    return list(names)


def _align_source_inputs(inst, fwd, noise_cov, data_cov=None):
    """Restrict source inputs to the ordered noise-covariance channel contract."""
    noise_channels = _covariance_channel_names(noise_cov)
    if not noise_channels:
        raise SourceConfigurationError("Noise covariance contains no channels.")

    missing_data = [name for name in noise_channels if name not in inst.ch_names]
    if missing_data:
        raise SourceConfigurationError(
            "Noise covariance contains channels absent from the target source input: "
            + ", ".join(missing_data)
        )
    inst.pick(noise_channels)
    if inst.ch_names != noise_channels:
        raise SourceConfigurationError(
            "Target source input could not be ordered like the noise covariance."
        )

    forward_channels = set(fwd["info"]["ch_names"])
    missing_forward = [name for name in noise_channels if name not in forward_channels]
    if missing_forward:
        raise SourceConfigurationError(
            "Noise covariance contains channels absent from the forward solution: "
            + ", ".join(missing_forward)
        )
    fwd = mne.pick_channels_forward(
        fwd, include=noise_channels, ordered=True, copy=True
    )
    noise_cov = mne.pick_channels_cov(
        noise_cov, include=noise_channels, ordered=True, copy=True
    )

    if data_cov is not None:
        data_channels = _covariance_channel_names(data_cov)
        if data_channels != noise_channels:
            raise SourceConfigurationError(
                "LCMV data covariance channels/order do not match the noise covariance. "
                f"noise={noise_channels}, data={data_channels}"
            )
        data_cov = mne.pick_channels_cov(
            data_cov, include=noise_channels, ordered=True, copy=True
        )
    return inst, fwd, noise_cov, data_cov


def load_resolved_rank(
    resolved_rank_file, expected_channels, expected_source_data_mode=None
):
    """Load and validate the rank artifact produced by compute_covariance.py."""
    try:
        payload = json.loads(Path(resolved_rank_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SourceConfigurationError(
            f"Could not read resolved rank from {resolved_rank_file}: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise SourceConfigurationError("resolved-rank.json must contain a JSON object.")

    channels = payload.get("channels")
    if channels != list(expected_channels):
        raise SourceConfigurationError(
            "Resolved-rank channels/order do not match the aligned source inputs. "
            f"rank={channels}, source={list(expected_channels)}"
        )
    source_data_mode = payload.get("source_data_mode")
    if (
        expected_source_data_mode is not None
        and source_data_mode != expected_source_data_mode
    ):
        raise SourceConfigurationError(
            "Resolved-rank source mode does not match the source input. "
            f"rank={source_data_mode!r}, source={expected_source_data_mode!r}"
        )
    resolved_rank = normalize_mne_rank(
        payload.get("rank"), config_name="resolved-rank.json.rank"
    )
    if not isinstance(resolved_rank, dict):
        raise SourceConfigurationError(
            "resolved-rank.json.rank must be an explicit rank dictionary."
        )
    return resolved_rank


def visualize_source_estimate(stc, subject, subjects_dir, subj_src_path, epoch, method, spacing, config, block):
    """
    Visualize and save the source estimate, showing the peak activation for both hemispheres.

    Parameters
    ----------
    stc : instance of SourceEstimate
        The source estimate to visualize (e.g., from dSPM or LCMV).
    subject : str
        The subject identifier.
    subjects_dir : str or Path
        The FreeSurfer subjects directory.
    subj_src_path : str or Path
        The path where the images should be saved.
    epoch : str
        The current epoch identifier.
    method : str
        The method used to generate the source estimate (e.g., 'dSPM' or 'LCMV').
    spacing : str
        The source space resolution (e.g., 'ico5').
    block : bool
        If True, interactive visualization.

    Returns
    -------
    None
    """
    selections = _source_visualization_selections(config)
    display_number = start_xvfb(interactive=True)
    try:
        fig = mne.viz.create_3d_figure((10, 10))
        fig.plotter.close()
        plot_flag = True
    except Exception as e:
        logger.error(e)
        plot_flag = False
    if plot_flag:
        try:
            logger.info("visualize_source_estimate...")
            for selection in selections:
                display_name = _selection_display_name(selection)
                default_peak = _is_default_peak_selection(selection)
                hemis = _normalize_hemi_list(selection.get("hemis", selection.get("hemi", "both")))

                for hs in hemis:
                    selected_vertex, selected_time, selection_reason = _select_source_vertex_and_time(
                        stc, subject, subjects_dir, hs, selection
                    )
                    parc = selection.get("parc", "aparc")
                    anatomical_label = _vertex_anatomical_label(
                        subject, subjects_dir, hs, selected_vertex, parc
                    )
                    selected_view = selection.get("views")
                    if selected_view is None:
                        selected_view = _default_surface_view(anatomical_label)

                    clim = selection.get("clim", dict(kind="percent", pos_lims=[0, 97.5, 100]))
                    if isinstance(clim, dict) and isinstance(clim.get("pos_lims"), tuple):
                        clim["pos_lims"] = list(clim["pos_lims"])

                    surfer_kwargs = dict(
                        subject=subject,
                        hemi=hs,
                        subjects_dir=subjects_dir,
                        time_viewer=_as_bool(selection.get("time_viewer"), True),
                        show_traces=_as_bool(selection.get("show_traces"), True),
                        clim=clim,
                        views=selected_view,
                        initial_time=selected_time,
                        time_unit="s",
                        size=tuple(selection.get("size", [1000, 800])),
                        smoothing_steps=int(selection.get("smoothing_steps", 10)),
                        brain_kwargs=dict(block=block, show=block)
                    )

                    brain = stc.plot(**surfer_kwargs)
                    logger.info(
                        "visualize_source_estimate, stc.plot: selection=%s, hemi=%s, vertex=%s, label=%s, "
                        "view=%s, time=%.6f",
                        display_name,
                        hs,
                        selected_vertex,
                        anatomical_label or "unlabeled",
                        selected_view,
                        selected_time,
                    )

                    time_viewer_vertex_set = _set_time_viewer_vertex(brain, hs, selected_vertex)
                    if not time_viewer_vertex_set:
                        brain.add_foci(
                            selected_vertex,
                            coords_as_verts=True,
                            hemi=hs,
                            color=selection.get("foci_color", "blue"),
                            scale_factor=float(selection.get("foci_scale_factor", 0.6)),
                            alpha=float(selection.get("foci_alpha", 0.5)),
                        )

                    if default_peak:
                        title = f"{method} (plus location of maximal activation)"
                    else:
                        label_text = f"; {anatomical_label}" if anatomical_label else ""
                        title = f"{method} ({display_name}{label_text}; {selection_reason} at {selected_time:.3f} s)"
                    title_actor_name = f"title_{_safe_slug(display_name)}_{hs}"
                    brain.add_text(0.1, 0.9, title, title_actor_name, font_size=14)

                    if default_peak:
                        output_name = f"{epoch}_evoked_{method}-{spacing}-{hs}.png"
                    else:
                        output_name = f"{epoch}_evoked_{method}-{spacing}-{_safe_slug(display_name)}-{hs}.png"
                    output_file = os.path.join(subj_src_path, output_name)
                    brain.save_image(output_file)
                    brain.close()

                    print(f"Saved {method} brain plot for {hs} hemisphere to {output_file}")
        except Exception as e:
            logger.exception("visualize_source_estimate error: %s", e)

    try:
        mne.viz.close_all_3d_figures()
    except Exception:
        pass
    gc.collect()
    time.sleep(0.5)
    stop_xvfb(display_number)

def compute_minimum_norm(
    method,
    evoked,
    fwd,
    noise_cov,
    subj_src_path,
    subject_id,
    subjects_dir,
    epoch_label,
    spacing,
    config,
    visualize,
    resolved_rank,
):
    """
    Compute the minimum-norm inverse solution and save the results.

    Parameters
    ----------
    method: str
        minimum-norm inverse solution, “MNE” | “dSPM” | “sLORETA” | “eLORETA”
    evoked : instance of Evoked
        The averaged evoked data.
    fwd : instance of Forward
        The forward solution.
    noise_cov : instance of Covariance
        The noise covariance matrix.
    subj_src_path : str
        The directory path to save the results.
    subject_id : str
        The subject identifier.
    subjects_dir : str or Path
        The FreeSurfer subjects directory.
    epoch_label : str
        The epoch label.
    spacing : str
        The source space resolution.
    config : dict
        The configuration dictionary with parameters for processing.
    visualize : bool
        plot source imaging.
    Returns
    -------
    None
    """
    stc_file = os.path.join(subj_src_path, f"{epoch_label}_evoked_{method}-{spacing}")
    method_config = _mapping(config.get(method), f"source.{method}")
    inverse_kwargs = ranked_mne_kwargs(
        _mapping(method_config.get("inverse_operator"), f"source.{method}.inverse_operator"),
        resolved_rank,
        f"source.{method}.inverse_operator",
    )
    apply_kwargs = _mapping(
        method_config.get("apply_inverse"), f"source.{method}.apply_inverse"
    )
    logger.info("%s inverse rank argument: %s", method, inverse_kwargs.get("rank"))
    inverse_operator = make_inverse_operator(
        info=evoked.info, forward=fwd, noise_cov=noise_cov, **inverse_kwargs
    )
    stc = apply_inverse(evoked, inverse_operator, **apply_kwargs)
    stc.save(stc_file, overwrite=True)

    if visualize:
        visualize_source_estimate(stc, subject_id, subjects_dir, subj_src_path, epoch_label, method, spacing, config, block=False)


def compute_LCMV(
    evoked,
    fwd,
    data_cov,
    noise_cov,
    subj_src_path,
    subject_id,
    subjects_dir,
    epoch_label,
    spacing,
    config,
    visualize,
    resolved_rank,
):
    """
    Compute the LCMV beamformer solution and save the results.

    Parameters
    ----------
    evoked : instance of Evoked
        The averaged evoked data.
    fwd : instance of Forward
        The forward solution.
    data_cov : instance of Covariance
        The data covariance matrix.
    noise_cov : instance of Covariance
        The noise covariance matrix.
    subj_src_path : str
        The directory path to save the results.
    subject_id : str
        The subject identifier.
    subjects_dir : str or Path
        The FreeSurfer subjects directory.
    epoch_label : str
        The epoch label.
    spacing : str
        The source space resolution.
    config : dict
        The configuration dictionary with parameters for processing.
    visualize : bool
        plot source imaging.
    Returns
    -------
    None
    """
    stc_file = os.path.join(subj_src_path, f"{epoch_label}_evoked_LCMV-{spacing}")
    lcmv_config = _mapping(config.get("LCMV"), "source.LCMV")
    legacy_rank = lcmv_config.get("n_rank", RANK_NOT_SET)
    make_lcmv_kwargs = ranked_mne_kwargs(
        _mapping(lcmv_config.get("make_lcmv"), "source.LCMV.make_lcmv"),
        resolved_rank,
        "source.LCMV.make_lcmv",
        legacy_rank=legacy_rank,
        legacy_config_name="source.LCMV.n_rank",
    )
    logger.info("LCMV beamformer rank argument: %s", make_lcmv_kwargs.get("rank"))
    filters = make_lcmv(
        evoked.info,
        fwd,
        data_cov,
        noise_cov=noise_cov,
        **make_lcmv_kwargs,
    )
    stc = apply_lcmv(evoked, filters)
    stc.save(stc_file, overwrite=True)
    if visualize:
        visualize_source_estimate(stc, subject_id, subjects_dir, subj_src_path, epoch_label, "LCMV", spacing, config, block=False)


def resolve_source_input_files(
    data_file,
    epoch_label,
    spacing,
    *,
    noise_covariance_file=None,
    forward_file=None,
    noise_covariance_dir=None,
    forward_dir=None,
):
    """Resolve exact routed files, retaining directory lookup for old callers."""
    recording_id = Path(data_file).parent.name

    if noise_covariance_file:
        resolved_covariance = Path(noise_covariance_file)
    elif noise_covariance_dir:
        resolved_covariance = Path(noise_covariance_dir) / recording_id / "bl-cov.fif"
    else:
        raise SourceConfigurationError(
            "Provide --noise_covariance_file (preferred) or --noise_covariance_dir."
        )

    if forward_file:
        resolved_forward = Path(forward_file)
    elif forward_dir:
        resolved_forward = (
            Path(forward_dir)
            / recording_id
            / f"{epoch_label}_{spacing}-fwd.fif"
        )
    else:
        raise SourceConfigurationError("Provide --forward_file (preferred) or --forward_dir.")

    return resolved_covariance, resolved_forward


def process_subject(
    epoch_file,
    fs_subjects_dir,
    noise_cov_path,
    fwd_dir,
    output_dir,
    config,
    visualize,
    noise_covariance_file=None,
    forward_file=None,
    data_covariance_file=None,
    resolved_rank_file=None,
):
    """Process one epoched recording for source localization."""
    subject_id = Path(epoch_file).stem.split('_')[0]
    epoch_label = config.get("epoch_label", "")
    spacing = config.get('spacing')
    noise_cov_file, resolved_forward_file = resolve_source_input_files(
        epoch_file,
        epoch_label,
        spacing,
        noise_covariance_file=noise_covariance_file,
        forward_file=forward_file,
        noise_covariance_dir=noise_cov_path,
        forward_dir=fwd_dir,
    )

    methods = normalize_source_methods(config.get("source_methods"))
    needs_lcmv = "LCMV" in methods
    if needs_lcmv and not data_covariance_file:
        raise SourceConfigurationError(
            "LCMV requires --data_covariance_file from compute_covariance.py."
        )

    noise_cov = mne.read_cov(noise_cov_file)
    data_cov = mne.read_cov(data_covariance_file) if needs_lcmv else None
    epochs = _pick_source_data(
        mne.read_epochs(epoch_file, preload=True), config.get("data_type", "meg")
    )
    fwd = mne.read_forward_solution(resolved_forward_file)
    epochs, fwd, noise_cov, data_cov = _align_source_inputs(
        epochs, fwd, noise_cov, data_cov
    )
    resolved_rank = (
        load_resolved_rank(resolved_rank_file, epochs.ch_names, "epochs")
        if resolved_rank_file
        else resolve_rank_policy(
            epochs, config.get("rank_policy", "auto"), config_name="rank_policy"
        )
    )
    logger.info("Resolved target rank for source imaging: %s", resolved_rank)
    evoked = epochs.average()

    for method in methods:
        if method in ["MNE", "dSPM", "sLORETA", "eLORETA"]:
            compute_minimum_norm(
                method, evoked, fwd, noise_cov, output_dir, subject_id,
                fs_subjects_dir, epoch_label, spacing, config, visualize,
                resolved_rank,
            )

    if needs_lcmv:
        compute_LCMV(
            evoked, fwd, data_cov, noise_cov, output_dir, subject_id,
            fs_subjects_dir, epoch_label, spacing, config, visualize,
            resolved_rank,
        )


def process_raw(
    raw_file,
    fs_subjects_dir,
    noise_cov_path,
    fwd_dir,
    output_dir,
    config,
    visualize,
    noise_covariance_file=None,
    forward_file=None,
    data_covariance_file=None,
    resolved_rank_file=None,
):
    """Process one continuous recording for source localization."""
    subject_id = Path(raw_file).stem.split('_')[0]
    spacing = config.get('spacing')
    epoch_label = config.get("epoch_label", "")
    noise_cov_file, resolved_forward_file = resolve_source_input_files(
        raw_file,
        epoch_label,
        spacing,
        noise_covariance_file=noise_covariance_file,
        forward_file=forward_file,
        noise_covariance_dir=noise_cov_path,
        forward_dir=fwd_dir,
    )

    methods = normalize_source_methods(config.get("source_methods"))
    needs_lcmv = "LCMV" in methods
    if needs_lcmv and not data_covariance_file:
        raise SourceConfigurationError(
            "LCMV requires --data_covariance_file from compute_covariance.py."
        )

    noise_cov = mne.read_cov(noise_cov_file)
    data_cov = mne.read_cov(data_covariance_file) if needs_lcmv else None
    raw = _pick_source_data(
        mne.io.read_raw_fif(raw_file, preload=True), config.get("data_type", "meg")
    )
    fwd = mne.read_forward_solution(resolved_forward_file)
    raw, fwd, noise_cov, data_cov = _align_source_inputs(
        raw, fwd, noise_cov, data_cov
    )
    resolved_rank = (
        load_resolved_rank(resolved_rank_file, raw.ch_names, "raw")
        if resolved_rank_file
        else resolve_rank_policy(
            raw, config.get("rank_policy", "auto"), config_name="rank_policy"
        )
    )
    logger.info("Resolved target rank for source imaging: %s", resolved_rank)

    for method in methods:
        if method in ["MNE", "dSPM", "sLORETA", "eLORETA"]:
            method_config = _mapping(config.get(method), f"source.{method}")
            inverse_kwargs = ranked_mne_kwargs(
                _mapping(
                    method_config.get("inverse_operator"),
                    f"source.{method}.inverse_operator",
                ),
                resolved_rank,
                f"source.{method}.inverse_operator",
            )
            apply_kwargs = _mapping(
                method_config.get("apply_inverse"),
                f"source.{method}.apply_inverse",
            )
            logger.info("%s inverse rank argument: %s", method, inverse_kwargs.get("rank"))
            inverse_operator = make_inverse_operator(
                info=raw.info,
                forward=fwd,
                noise_cov=noise_cov,
                **inverse_kwargs,
            )
            stc = apply_inverse_raw(raw, inverse_operator, **apply_kwargs)
            stc.save(
                os.path.join(output_dir, f"{epoch_label}_raw_{method}-{spacing}"),
                overwrite=True,
            )
            if visualize:
                visualize_source_estimate(
                    stc, subject_id, fs_subjects_dir, output_dir, epoch_label,
                    method, spacing, config, block=False,
                )

    if needs_lcmv:
        lcmv_config = _mapping(config.get("LCMV"), "source.LCMV")
        legacy_rank = lcmv_config.get("n_rank", RANK_NOT_SET)
        make_lcmv_kwargs = ranked_mne_kwargs(
            _mapping(lcmv_config.get("make_lcmv"), "source.LCMV.make_lcmv"),
            resolved_rank,
            "source.LCMV.make_lcmv",
            legacy_rank=legacy_rank,
            legacy_config_name="source.LCMV.n_rank",
        )
        logger.info("LCMV beamformer rank argument: %s", make_lcmv_kwargs.get("rank"))
        filters = make_lcmv(
            raw.info, fwd, data_cov, noise_cov=noise_cov,
            **make_lcmv_kwargs,
        )
        stc = apply_lcmv_raw(raw, filters)
        stc.save(
            os.path.join(output_dir, f"{epoch_label}_raw_LCMV-{spacing}"),
            overwrite=True,
        )
        if visualize:
            visualize_source_estimate(
                stc, subject_id, fs_subjects_dir, output_dir, epoch_label,
                "LCMV", spacing, config, block=False,
            )


def parse_arguments():
    """
    Parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        The parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description="Process source localization for MEG data.")
    parser.add_argument('--data_mode', type=str, default="epochs", choices=["raw", "epochs"],
                        help="Data mode: 'raw' for continuous data, 'epochs' for event-based epochs.")
    parser.add_argument('--data_file', type=str, required=True, help="Path to the epochs or raw file.")
    parser.add_argument('--fs_subjects_dir', type=str, required=True,
                        help="Path to the MRI subject directory (Freesurfer subjects dir).")
    parser.add_argument('--noise_covariance_file', type=str,
                        help="Exact routed noise covariance file (preferred).")
    parser.add_argument('--data_covariance_file', type=str,
                        help="Exact LCMV data covariance file; required only for LCMV.")
    parser.add_argument('--resolved_rank_file', type=str,
                        help="Resolved target-rank JSON produced by covariance.")
    parser.add_argument('--forward_file', type=str,
                        help="Exact routed forward solution file (preferred).")
    parser.add_argument('--noise_covariance_dir', type=str,
                        help="Legacy directory lookup for the noise covariance file.")
    parser.add_argument('--forward_dir', type=str,
                        help="Legacy directory lookup for the forward solution.")
    parser.add_argument('--output_dir', type=str, required=True, help="Subject output directory.")
    parser.add_argument('--config', type=str, help="Configuration parameters.")
    parser.add_argument('--visualize', type=str2bool, nargs='?', const=True, default=True, help="Whether to visualize the source imaging (default: True)")

    return parser.parse_args()


def main():
    """
    Main function to run the source localization for a single subject.
    """
    # os.environ["MESA_GLSL_VERSION_OVERRIDE"] = "150"
    # os.environ["MESA_GL_VERSION_OVERRIDE"] = "3.2"
    # os.environ['DISPLAY'] = ':99'  # Set environment for pyvista backend drawing.
    # os.environ["QT_QPA_PLATFORM"] = "xcb"

    args = parse_arguments()
    handle_yaml_scientific_notation()

    Path(args.output_dir).mkdir(exist_ok=True, parents=True)

    # Example configuration (this should be loaded from a file in a real scenario)
#     args.config = """
# source_methods:
#     - dSPM
#     # - LCMV
#
# data_type: meg  # mag
# spacing: ico4
# epoch_label: wdonset
# dSPM:
#     inverse_operator:
#         loose: auto
#         depth: 0.8
#         fixed: auto
#     apply_inverse:
#         lambda2: 0.111111111111
#         method: dSPM
#         pick_ori: normal
#
# LCMV:
#     data_covariance:
#         tmin: 0.01
#         tmax: 0.4
#         method: auto
#     make_lcmv:
#         reg: 0.05
#         pick_ori: null
#         weight_norm: unit-noise-gain-invariant
# """
    config = yaml.safe_load(args.config)
    if not isinstance(config, dict):
        raise SourceConfigurationError("--config must decode to a mapping.")
    if args.data_mode == "raw":
        process_raw(args.data_file,
                    args.fs_subjects_dir,
                    args.noise_covariance_dir,
                    args.forward_dir,
                    args.output_dir,
                    config,
                    args.visualize,
                    noise_covariance_file=args.noise_covariance_file,
                    forward_file=args.forward_file,
                    data_covariance_file=args.data_covariance_file,
                    resolved_rank_file=args.resolved_rank_file)
    elif args.data_mode == "epochs":
        process_subject(args.data_file,
                        args.fs_subjects_dir,
                        args.noise_covariance_dir,
                        args.forward_dir,
                        args.output_dir,
                        config,
                        args.visualize,
                        noise_covariance_file=args.noise_covariance_file,
                        forward_file=args.forward_file,
                        data_covariance_file=args.data_covariance_file,
                        resolved_rank_file=args.resolved_rank_file)
    else:
        raise ValueError("Unspported data mode: {}".format(args.data_mode))
    print("Finished source recon processing...")

if __name__ == "__main__":
    try:
        main()
    except (
        MegflowConfigurationError,
        RankConfigurationError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as error:
        logger.error("Source configuration or processing error: %s", error)
        raise SystemExit(2) from error
