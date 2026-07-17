"""Source-estimate selection and visualization helpers."""

import gc
import logging
import os
import re
import time

import mne
import numpy as np
from mne.viz.ui_events import VertexSelect, publish

from utils import start_xvfb, stop_xvfb

logger = logging.getLogger(__name__)


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
