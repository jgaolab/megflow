# -*- coding: utf-8 -*-
"""Workflow diagram + provenance for MEGFlow static HTML reports."""

from __future__ import annotations

import html
import json
import re
import secrets
from pathlib import Path
from typing import Any

WORKFLOW_SECTION_TITLE = "Workflow"

# Run-details params: paths + format always; source/covariance only when meg_stage >= 3 (see _params_keys_for_manifest).
_PARAMS_ALWAYS_KEYS: tuple[str, ...] = (
    "dataset_dir",
    "preproc_dir",
    "output_dir",
    "dataset_format",
    "is_bids",
)
_PARAMS_PATH_KEYS: tuple[str, ...] = (
    "dataset_dir",
    "preproc_dir",
    "output_dir",
)
_PARAMS_DATA_KEYS: tuple[str, ...] = (
    "dataset_format",
    "is_bids",
)
_PARAMS_MEGQC_KEYS: tuple[str, ...] = (
    "megqc_enabled",
    "megqc_min_score",
    "megqc_alarm_score",
    "megqc_meg_vendor",
    "megqc_category",
    "megqc_reference_scope",
    "megqc_preproc_config",
    "megqc_keep_bad_annotations",
    "megqc_omit_bad_channels",
)
_PARAMS_SOURCE_STAGE_KEYS: tuple[str, ...] = (
    "covar_type",
    "src_type",
)
_PARAMS_ANATOMY_KEYS: tuple[str, ...] = (
    "fs_subjects_dir",
    "anatomy_preprocess_method",
)
# Omit run_name (opaque Nextflow label); meg_stage is internal — use steps + primary only.
_WORKFLOW_META_KEYS: tuple[str, ...] = (
    "start",
    "nextflow_version",
)

_RUN_DETAIL_LABELS: dict[str, str] = {
    "steps": "Steps",
    "primary": "Mode",
    "skip_ica": "Skip ICA",
    "run_anatomy": "Structural MRI in this run",
    "dataset_dir": "Dataset",
    "preproc_dir": "Preprocessed",
    "output_dir": "Output",
    "fs_subjects_dir": "FreeSurfer subjects",
    "anatomy_preprocess_method": "Anatomy method",
    "dataset_format": "Format",
    "covar_type": "Covariance",
    "src_type": "Source localization",
    "is_bids": "BIDS",
    "megqc_enabled": "Normative QC scoring",
    "megqc_min_score": "QC processing minimum",
    "megqc_alarm_score": "QC warning threshold",
    "megqc_meg_vendor": "QC MEG vendor",
    "megqc_category": "QC reference category",
    "megqc_reference_scope": "QC reference scope",
    "megqc_preproc_config": "QC preprocessing",
    "megqc_keep_bad_annotations": "QC keeps BAD spans",
    "megqc_omit_bad_channels": "QC omits bad channels",
    "start": "Started",
    "nextflow_version": "Nextflow",
}

_RUN_DETAIL_HELP: dict[str, str] = {
    "megqc_enabled": "Scores each imported recording before main MEG preprocessing.",
    "megqc_min_score": "Processing gate. Recordings below this score skip downstream MEG steps.",
    "megqc_alarm_score": "Report warning only. It flags low scores without blocking processing.",
    "megqc_meg_vendor": "MEG vendor used to select the Normative Reference; auto infers from channels and metadata.",
    "megqc_category": "Normative reference category, usually auto, rest, task, or ALL.",
    "megqc_reference_scope": "Reference pool priority used for scoring, for example device plus category.",
    "megqc_preproc_config": "Reference-aligned scoring preprocessing. Keep the 1-100 Hz band-pass and 250 Hz sampling rate fixed.",
    "megqc_keep_bad_annotations": "Yes keeps BAD annotations during scoring to match the reference.",
    "megqc_omit_bad_channels": "No keeps raw.info['bads'] during scoring; omit only for diagnostics.",
}

_RUN_MODE_LABELS: dict[str, str] = {
    "report": "Report only",
    "anatomy": "Anatomy only",
    "all": "MEG + anatomy",
    "meg_all": "MEG full",
    "meg_artifacts": "Artifacts QC",
    "meg_ica": "ICA",
    "meg_epochs": "Epochs",
}

_STATUS_LABELS: dict[str, str] = {
    "done": "Complete",
    "partial": "Partially complete",
    "missing": "Missing expected outputs",
}


def safe_json(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _extract_params_steps(config_text: str) -> str | None:
    m = re.search(r"^\s*steps\s*=\s*['\"]([^'\"]+)['\"]", config_text, re.MULTILINE)
    return m.group(1).strip() if m else None


def _parsed_value(parsed: dict[str, Any], snake_key: str, default: Any = None) -> Any:
    aliases = {
        "meg_stage": "megStage",
        "run_anatomy": "runAnatomy",
        "run_meg": "runMeg",
        "skip_ica": "skipIca",
    }
    if snake_key in parsed:
        return parsed.get(snake_key)
    camel_key = aliases.get(snake_key)
    if camel_key and camel_key in parsed:
        return parsed.get(camel_key)
    return default


def _parsed_bool(parsed: dict[str, Any], snake_key: str, default: bool = False) -> bool:
    return bool(_parsed_value(parsed, snake_key, default))


def _parsed_int(parsed: dict[str, Any], snake_key: str, default: int) -> int:
    try:
        return int(_parsed_value(parsed, snake_key, default))
    except (TypeError, ValueError):
        return default


def _bool_value(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return default


def _megqc_enabled_from_manifest(
    manifest: dict[str, Any] | None, default: bool = True
) -> bool:
    if not isinstance(manifest, dict):
        return default
    snapshot = manifest.get("params_snapshot")
    if not isinstance(snapshot, dict):
        return default
    if "megqc_enabled" in snapshot:
        return _bool_value(snapshot.get("megqc_enabled"), default)
    effective = snapshot.get("effective_config")
    if isinstance(effective, dict):
        megqc = effective.get("megqc")
        if isinstance(megqc, dict) and "enabled" in megqc:
            return _bool_value(megqc.get("enabled"), default)
    return default


def _ica_category_enabled_from_manifest(
    manifest: dict[str, Any] | None,
    category: str,
    default: bool = True,
) -> bool:
    if not isinstance(manifest, dict):
        return default
    snapshot = manifest.get("params_snapshot")
    if not isinstance(snapshot, dict):
        return default
    key = f"ic_{category}"
    if key in snapshot:
        return _bool_value(snapshot.get(key), default)
    effective = snapshot.get("effective_config")
    if not isinstance(effective, dict):
        return default
    ic_label = effective.get("ic_label")
    if isinstance(ic_label, dict) and key in ic_label:
        return _bool_value(ic_label.get(key), default)
    return default


def _snapshot_with_effective_values(snapshot: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(snapshot)
    effective = snapshot.get("effective_config")
    if not isinstance(effective, dict):
        return normalized

    def add(key: str, *path: str) -> None:
        if key in normalized:
            return
        value: Any = effective
        for part in path:
            if not isinstance(value, dict) or part not in value:
                return
            value = value[part]
        normalized[key] = value

    add("dataset_format", "dataset_format")
    add("is_bids", "is_bids")
    add("anatomy_preprocess_method", "anatomy", "method")
    add("megqc_enabled", "megqc", "enabled")
    add("megqc_min_score", "megqc", "min_score")
    add("megqc_alarm_score", "megqc", "alarm_score")
    add("megqc_meg_vendor", "megqc", "meg_vendor")
    add("megqc_category", "megqc", "category")
    add("megqc_reference_scope", "megqc", "reference_scope")
    add("megqc_preproc_config", "megqc", "preproc")
    add("megqc_keep_bad_annotations", "megqc", "keep_bad_annotations")
    add("megqc_omit_bad_channels", "megqc", "omit_bad_channels")
    add("covar_type", "covariance", "type")
    add("src_type", "source", "type")
    return normalized


def parse_meg_steps_python(steps_raw: str) -> dict[str, Any]:
    """Mirror nextflow parseMegPipelineSteps (subset sufficient for workflow UI)."""
    parts = [p.strip().lower() for p in steps_raw.split(",") if p.strip()]
    if not parts:
        raise ValueError("params.steps is empty")
    aliases = {"meg": "meg_all", "artifacts": "meg_artifacts", "ica": "meg_ica", "epochs": "meg_epochs"}
    primary = aliases.get(parts[0], parts[0])
    mods = set(parts[1:]) if len(parts) > 1 else set()
    allowed = {"skip_ica", "with_anatomy"}
    extra = mods - allowed
    if extra:
        raise ValueError(f"Unknown steps modifier: {extra}")
    if primary == "meg_all" and "with_anatomy" in mods:
        raise ValueError("steps=meg_all cannot be combined with with_anatomy")
    skip_ica = "skip_ica" in mods
    with_anatomy = "with_anatomy" in mods
    meg_stage = -1
    run_anatomy = False
    run_meg = False
    if primary == "report":
        pass
    elif primary == "anatomy":
        run_anatomy = True
    elif primary == "all":
        run_anatomy = True
        run_meg = True
        meg_stage = 3
    elif primary == "meg_all":
        run_meg = True
        meg_stage = 3
    elif primary == "meg_artifacts":
        run_meg = True
        meg_stage = 0
        run_anatomy = with_anatomy
    elif primary == "meg_ica":
        run_meg = True
        meg_stage = 1
        run_anatomy = with_anatomy
    elif primary == "meg_epochs":
        run_meg = True
        meg_stage = 2
        run_anatomy = with_anatomy
    else:
        raise ValueError(f"Unknown steps primary: {primary}")
    if skip_ica and meg_stage != 2:
        raise ValueError("skip_ica is only supported with meg_epochs")
    return {
        "primary": primary,
        "meg_stage": meg_stage,
        "run_anatomy": run_anatomy,
        "run_meg": run_meg,
        "skip_ica": skip_ica,
    }


def qc_completeness_scope_from_manifest(manifest: dict[str, Any] | None) -> dict[str, Any]:
    """Scope for static QC completeness alarms (missing ICA / coreg, etc.).

    Mirrors meg_stage from parse_meg_steps_python / workflow: 0 = through artifacts,
    1 = ICA, 2 = epochs, 3 = covariance / coreg / head model / source.

    If manifest is missing or unparsed, assume a full MEG pipeline (meg_stage 3)
    so older datasets without manifest keep previous strict behaviour.
    """
    default = {
        "meg_stage": 3,
        "skip_ica": False,
        "run_meg": True,
        "megqc_enabled": True,
        "ic_ecg_enabled": True,
        "ic_eog_enabled": True,
    }
    if not manifest:
        return default
    parsed = manifest.get("parsed")
    if not isinstance(parsed, dict):
        return default
    if not _parsed_bool(parsed, "run_meg"):
        ms = _parsed_int(parsed, "meg_stage", -99)
        return {
            "meg_stage": ms,
            "skip_ica": _parsed_bool(parsed, "skip_ica"),
            "run_meg": False,
            "megqc_enabled": False,
            "ic_ecg_enabled": False,
            "ic_eog_enabled": False,
        }
    ms = _parsed_int(parsed, "meg_stage", 3)
    megqc_enabled = _megqc_enabled_from_manifest(manifest)
    return {
        "meg_stage": ms,
        "skip_ica": _parsed_bool(parsed, "skip_ica"),
        "run_meg": True,
        "megqc_enabled": megqc_enabled,
        "ic_ecg_enabled": _ica_category_enabled_from_manifest(
            manifest, "ecg"
        ),
        "ic_eog_enabled": _ica_category_enabled_from_manifest(
            manifest, "eog"
        ),
    }


def expect_ica_outputs_for_qc(scope: dict[str, Any]) -> bool:
    if not scope.get("run_meg"):
        return False
    try:
        ms = int(scope.get("meg_stage", 3))
    except (TypeError, ValueError):
        ms = 3
    return ms >= 1 and not scope.get("skip_ica")


def expect_coregistration_outputs_for_qc(scope: dict[str, Any]) -> bool:
    if not scope.get("run_meg"):
        return False
    try:
        ms = int(scope.get("meg_stage", 3))
    except (TypeError, ValueError):
        ms = 3
    return ms >= 3


def build_workflow_nodes(manifest: dict[str, Any] | None, source: str) -> tuple[list[dict[str, Any]], str]:
    """Return (nodes, footnote). Each node: key, label, lane, plan run|skip|omit."""
    if manifest is None:
        return (
            [],
            "No megflow_run_manifest.json found under preprocessed/logs. "
            "Run a recent MEGFlow Nextflow pipeline to emit the manifest, or mount/copy nextflow.config into the output root.",
        )

    parsed = manifest.get("parsed") or {}
    primary = str(parsed.get("primary", ""))
    steps_raw = str(manifest.get("steps_raw", ""))

    nodes: list[dict[str, Any]] = []

    if primary == "report":
        return (
            [],
            f"steps: {steps_raw} (source: {source}) — report-only: no prior preprocessing manifest "
            "(or prior run was also report-only); no pipeline diagram.",
        )

    if primary == "anatomy":
        nodes.append(
            {
                "key": "anatomy_structural",
                "label": "Structural MRI processing",
                "lane": "model",
                "stage": 0,
                "plan": "run",
                "depends_on": [],
            }
        )
        return nodes, f"steps: {steps_raw} (source: {source})"

    run_anatomy = _parsed_bool(parsed, "run_anatomy")
    if run_anatomy:
        nodes.append(
            {
                "key": "anatomy_structural",
                "label": "Structural MRI",
                "lane": "model",
                "stage": 2,
                "plan": "run",
                "depends_on": [],
            }
        )

    meg_stage = _parsed_int(parsed, "meg_stage", -99)
    run_meg = _parsed_bool(parsed, "run_meg")
    skip_ica = _parsed_bool(parsed, "skip_ica")
    megqc_enabled = _megqc_enabled_from_manifest(manifest)
    snapshot = manifest.get("params_snapshot")
    normalized_snapshot = (
        _snapshot_with_effective_values(snapshot)
        if isinstance(snapshot, dict)
        else {}
    )
    covariance_type = str(normalized_snapshot.get("covar_type", "epochs")).strip().lower()
    source_type = str(normalized_snapshot.get("src_type", "epochs")).strip().lower()

    if run_meg:
        if megqc_enabled:
            nodes.append(
                {
                    "key": "quality_score",
                    "label": "Quality score",
                    "lane": "data",
                    "stage": 0,
                    "plan": "run",
                    "depends_on": [],
                }
            )
        nodes.append(
            {
                "key": "basic_preproc",
                "label": "Basic preprocessing",
                "lane": "data",
                "stage": 1,
                "plan": "run",
                "depends_on": ["quality_score"] if megqc_enabled else [],
            }
        )
        nodes.append(
            {
                "key": "artifacts",
                "label": "Artifacts",
                "lane": "data",
                "stage": 2,
                "plan": "run",
                "depends_on": ["basic_preproc"],
            }
        )
        if meg_stage >= 1 and not skip_ica:
            nodes.append(
                {
                    "key": "ica",
                    "label": "ICA",
                    "lane": "data",
                    "stage": 3,
                    "plan": "run",
                    "depends_on": ["artifacts"],
                }
            )
        signal_predecessor = "artifacts" if skip_ica else "ica"
        if meg_stage >= 2:
            nodes.append(
                {
                    "key": "epochs",
                    "label": "Epochs",
                    "lane": "data",
                    "stage": 4,
                    "plan": "run",
                    "depends_on": [signal_predecessor],
                }
            )
        if meg_stage >= 3:
            covariance_predecessor = (
                "epochs" if covariance_type == "epochs" else signal_predecessor
            )
            anatomy_dependency = ["anatomy_structural"] if run_anatomy else []
            nodes.append(
                {
                    "key": "covariance",
                    "label": "Covariance",
                    "lane": "data",
                    "stage": 5,
                    "plan": "run",
                    "depends_on": [covariance_predecessor],
                }
            )
            nodes.append(
                {
                    "key": "coregistration",
                    "label": "Coregistration",
                    "lane": "model",
                    "stage": 4,
                    "plan": "run",
                    "depends_on": [signal_predecessor, *anatomy_dependency],
                }
            )
            nodes.append(
                {
                    "key": "headmodel",
                    "label": "Head model",
                    "lane": "model",
                    "stage": 5,
                    "plan": "run",
                    "depends_on": ["coregistration", *anatomy_dependency],
                }
            )
            source_predecessor = (
                "epochs" if source_type == "epochs" else signal_predecessor
            )
            nodes.append(
                {
                    "key": "source",
                    "label": "Source localization",
                    "lane": "data",
                    "stage": 6,
                    "plan": "run",
                    "depends_on": [source_predecessor, "covariance", "headmodel"],
                }
            )

    pl_raw = manifest.get("pipeline_steps_raw")
    if manifest.get("report_only") and pl_raw:
        foot = (
            f"Current run: {steps_raw} (source: {source}); "
            f"diagram reflects prior pipeline steps: {pl_raw}"
        )
    else:
        foot = f"steps: {steps_raw} (source: {source})"
    return nodes, foot


def load_workflow_context(meg_root: Path, preprocessed_dir: Path) -> dict[str, Any]:
    manifest_path = preprocessed_dir / "logs" / "megflow_run_manifest.json"
    manifest: dict[str, Any] | None = None
    source = "none"
    steps_raw: str | None = None

    if manifest_path.is_file():
        data = safe_json(manifest_path)
        if data and isinstance(data, dict) and (
            data.get("steps_raw") is not None or data.get("parsed") is not None or data.get("manifest_schema_version") is not None
        ):
            manifest = data
            source = "manifest"
            steps_raw = manifest.get("steps_raw")
            if steps_raw and not manifest.get("parsed"):
                try:
                    manifest["parsed"] = parse_meg_steps_python(str(steps_raw))
                except ValueError:
                    pass

    if manifest is None:
        for cfg_path in (meg_root / "nextflow.config", meg_root / "run_nextflow.config"):
            if cfg_path.is_file():
                try:
                    text = cfg_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                sr = _extract_params_steps(text)
                if sr:
                    try:
                        parsed = parse_meg_steps_python(sr)
                        manifest = {"manifest_schema_version": 0, "steps_raw": sr, "parsed": parsed}
                        source = "config"
                        steps_raw = sr
                        break
                    except ValueError:
                        manifest = {"manifest_schema_version": 0, "steps_raw": sr, "parsed": {}}
                        source = "config"
                        steps_raw = sr
                        break

    nodes, footnote = build_workflow_nodes(manifest, source)
    return {
        "source": source,
        "manifest_path": str(manifest_path) if manifest_path.is_file() else None,
        "manifest": manifest,
        "steps_raw": steps_raw,
        "nodes": nodes,
        "footnote": footnote,
    }


def _node_dataset_status(node: dict[str, Any], summaries: list[dict[str, Any]]) -> str:
    key = node["key"]
    if key == "anatomy_structural":
        return "done"
    if key == "basic_preproc":
        n = sum(
            1
            for s in summaries
            if s.get("steps", {}).get("basic_preproc", s.get("preproc_done"))
        )
        if n == 0:
            return "missing"
        if n == len(summaries):
            return "done"
        return "partial"
    if key == "static_report":
        return "done"
    if key == "artifacts":
        n = sum(1 for s in summaries if s.get("steps", {}).get("artifacts"))
        if n == 0:
            return "missing"
        if n == len(summaries):
            return "done"
        return "partial"
    step_key = key
    n_done = sum(1 for s in summaries if s.get("steps", {}).get(step_key))
    if n_done == 0:
        return "missing"
    if n_done == len(summaries):
        return "done"
    return "partial"


def _status_class(status: str) -> str:
    return {
        "done": "wf-done",
        "partial": "wf-partial",
        "missing": "wf-missing",
    }.get(status, "wf-missing")


def _status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, "Missing expected outputs")


def _run_mode_label(value: Any) -> str:
    raw = str(value).strip()
    return _RUN_MODE_LABELS.get(raw, raw)


def _display_value(key: str, value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if key == "primary":
        return _run_mode_label(value)
    if key == "megqc_preproc_config":
        return _summarize_preproc_config(value)
    return str(value).strip()


def _detail_help(key: str) -> str:
    return _RUN_DETAIL_HELP.get(key, "")


def _summarize_preproc_config(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    flat = re.sub(r"\s+", " ", text)
    parts: list[str] = []
    filter_match = re.search(r"filter:\s*\{[^}]*l_freq:\s*([^,}]+)[^}]*h_freq:\s*([^,}]+)", flat)
    if filter_match:
        parts.append(f"filter {filter_match.group(1).strip()}-{filter_match.group(2).strip()} Hz")
    notch_match = re.search(r"notch_filter:\s*\{[^}]*freqs:\s*([^,}]+)", flat)
    if notch_match:
        parts.append(f"notch {notch_match.group(1).strip()} Hz")
    if parts:
        return "; ".join(parts)
    return flat[:160] + ("..." if len(flat) > 160 else "")


def _node_label_lines(label: str, max_chars: int = 18, max_lines: int = 2) -> list[str]:
    """Compact SVG text wrapping without relying on foreignObject support."""
    words = str(label).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = word
        else:
            lines.append(word[:max_chars])
            current = word[max_chars:]
        if len(lines) >= max_lines:
            break
    if len(lines) < max_lines and current:
        lines.append(current)
    remaining = " ".join(words)
    shown = " ".join(lines)
    if len(lines) == max_lines and len(shown) < len(remaining):
        lines[-1] = (lines[-1][: max(0, max_chars - 3)].rstrip() + "...") if len(lines[-1]) > 3 else "..."
    return lines[:max_lines]


def _meg_stage_for_param_filter(parsed: dict[str, Any] | None) -> int:
    """meg_stage from manifest; used to hide unused param rows."""
    if not isinstance(parsed, dict) or not _parsed_bool(parsed, "run_meg"):
        return -1
    return _parsed_int(parsed, "meg_stage", 3)


def _params_keys_for_manifest(parsed_dict: dict[str, Any] | None) -> list[str]:
    keys = list(_PARAMS_ALWAYS_KEYS)
    if _meg_stage_for_param_filter(parsed_dict) >= 3:
        keys.extend(_PARAMS_SOURCE_STAGE_KEYS)
    return keys


def _show_anatomy_snapshot_fields(parsed: dict[str, Any] | None) -> bool:
    """Only show FS / anatomy method when this run actually included structural preprocessing."""
    if not isinstance(parsed, dict):
        return False
    if str(parsed.get("primary", "")) == "anatomy":
        return True
    return _parsed_bool(parsed, "run_anatomy")


def _snapshot_rows(snap: dict[str, Any], keys: tuple[str, ...] | list[str]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for key in keys:
        if key not in snap:
            continue
        val = snap[key]
        if val is None or str(val).strip() == "":
            continue
        rows.append((key, _display_value(key, val)))
    return rows


def _workflow_detail_groups(manifest: dict[str, Any]) -> list[tuple[str, list[tuple[str, str]]]]:
    """Curated detail groups; each row is (internal_key, display_value)."""
    groups: list[tuple[str, list[tuple[str, str]]]] = []
    mode_rows: list[tuple[str, str]] = []
    runtime_rows: list[tuple[str, str]] = []
    input_rows: list[tuple[str, str]] = []
    path_rows: list[tuple[str, str]] = []
    later_groups: list[tuple[str, list[tuple[str, str]]]] = []
    sr = manifest.get("steps_raw")
    if sr is not None and str(sr).strip() != "":
        mode_rows.append(("steps", str(sr).strip()))
    parsed = manifest.get("parsed")
    parsed_dict = parsed if isinstance(parsed, dict) else None
    if parsed_dict:
        if parsed_dict.get("primary") not in (None, ""):
            mode_rows.append(("primary", _run_mode_label(parsed_dict["primary"])))
        if _parsed_bool(parsed_dict, "skip_ica"):
            mode_rows.append(("skip_ica", "yes"))
        if _parsed_bool(parsed_dict, "run_anatomy"):
            mode_rows.append(("run_anatomy", "yes"))
    if mode_rows:
        groups.append(("Run mode", mode_rows))

    wf = manifest.get("workflow_meta")
    if isinstance(wf, dict):
        for key in _WORKFLOW_META_KEYS:
            if key not in wf:
                continue
            val = wf[key]
            if val is None or str(val).strip() == "":
                continue
            runtime_rows.append((key, str(val).strip()))
    if runtime_rows:
        groups.append(("Runtime", runtime_rows))

    snap = manifest.get("params_snapshot")
    if isinstance(snap, dict):
        snap = _snapshot_with_effective_values(snap)
        input_rows = _snapshot_rows(snap, _PARAMS_DATA_KEYS)
        path_rows = _snapshot_rows(snap, _PARAMS_PATH_KEYS)
        if input_rows:
            groups.append(("Input data", input_rows))
        if _parsed_bool(parsed_dict or {}, "run_meg"):
            megqc_rows = _snapshot_rows(snap, _PARAMS_MEGQC_KEYS)
            if megqc_rows:
                later_groups.append(("Normative QC", megqc_rows))
        if _show_anatomy_snapshot_fields(parsed_dict):
            anatomy_rows = _snapshot_rows(snap, _PARAMS_ANATOMY_KEYS)
            if anatomy_rows:
                later_groups.append(("Anatomy", anatomy_rows))
        if _meg_stage_for_param_filter(parsed_dict) >= 3:
            source_rows = _snapshot_rows(snap, _PARAMS_SOURCE_STAGE_KEYS)
            if source_rows:
                later_groups.append(("Source model", source_rows))

    if path_rows:
        groups.append(("Paths", path_rows))
    groups.extend(later_groups)
    return groups


def _detail_group_class(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"workflow-detail-group workflow-detail-group-{slug or 'details'}"


def _detail_value_class(key: str) -> str:
    path_like = {*_PARAMS_PATH_KEYS, "fs_subjects_dir"}
    if key in path_like:
        return "wf-detail-v wf-detail-path-value"
    return "wf-detail-v"


def _detail_label(key: str) -> str:
    return _RUN_DETAIL_LABELS.get(key, key.replace("_", " ").title())


def _nextflow_config_hint_html(ctx: dict[str, Any]) -> str:
    """Link to bundled data/nextflow.config.txt (plain text; avoids browser XML parse errors)."""
    if ctx.get("nextflow_config_bundled"):
        desc = ctx.get("nextflow_config_source_name") or "nextflow.config"
        return (
            '<p class="small workflow-config-hint">Full Nextflow parameters: '
            '<a href="data/nextflow.config.txt">nextflow.config</a> '
            f'<span class="muted">({html.escape(str(desc))}; opens as plain text).</span></p>'
        )
    return (
        '<p class="small workflow-config-hint workflow-config-hint-missing">No nextflow.config was bundled. '
        "The report checks <code>preprocessed/logs/</code>, the dataset output root, and the manifest "
        "launch directory for <code>run_nextflow.config</code> or <code>nextflow.config</code>. "
        "Docker runs normally copy the runtime config to the output root. Regenerate this report "
        "after retaining a config in one of those locations.</p>"
    )


def _render_svg(nodes: list[dict[str, Any]], status_fn) -> str:
    def semantic_lane(node: dict[str, Any]) -> str:
        return "model" if node.get("lane") in {"model", "anatomy"} else "data"

    data_nodes = [node for node in nodes if semantic_lane(node) == "data"]
    model_nodes = [node for node in nodes if semantic_lane(node) == "model"]
    mid = "wf" + secrets.token_hex(4)

    order_by_key = {node["key"]: index for index, node in enumerate(nodes)}
    stage_by_key: dict[str, int] = {}
    for index, node in enumerate(nodes):
        try:
            stage_by_key[node["key"]] = int(node.get("stage", index))
        except (TypeError, ValueError):
            stage_by_key[node["key"]] = index
    stage_values = sorted(set(stage_by_key.values())) or [0]
    stage_to_column = {stage: index for index, stage in enumerate(stage_values)}
    column_by_key = {
        key: stage_to_column[stage]
        for key, stage in stage_by_key.items()
    }
    n_columns = max(len(stage_values), 1)

    if n_columns <= 2:
        box_w = 220.0
        box_h = 88.0
        gap = 56.0
        min_width = 760.0
    elif n_columns <= 4:
        box_w = 190.0
        box_h = 82.0
        gap = 44.0
        min_width = 860.0
    else:
        box_w = 140.0
        box_h = 80.0
        gap = 22.0
        min_width = 980.0
    pad_x = 28.0
    lane_pad_y = 25.0
    rx = 14.0

    two_rows = bool(data_nodes and model_nodes)
    if two_rows:
        y_data = 66.0
        y_model = 230.0
    elif data_nodes:
        y_data = 66.0
        y_model = 66.0
    else:
        y_data = 66.0
        y_model = 66.0

    graph_width = n_columns * box_w + max(0, n_columns - 1) * gap
    width = max(pad_x * 2 + graph_width, min_width)
    x_offset = (width - graph_width) / 2.0
    last_row_y = max(
        y_data if data_nodes else 0.0,
        y_model if model_nodes else 0.0,
    )
    height = last_row_y + box_h + 58.0

    statuses = {node["key"]: status_fn(node) for node in nodes}

    def positions_for(row_nodes: list[dict[str, Any]], y: float) -> list[tuple[dict[str, Any], float, float]]:
        ordered = sorted(
            row_nodes,
            key=lambda node: (column_by_key[node["key"]], order_by_key[node["key"]]),
        )
        return [
            (
                node,
                x_offset + column_by_key[node["key"]] * (box_w + gap),
                y,
            )
            for node in ordered
        ]

    data_pos = positions_for(data_nodes, y_data)
    model_pos = positions_for(model_nodes, y_model)
    all_positions = [*data_pos, *model_pos]
    pos_by_key = {
        node["key"]: (node, x, y)
        for node, x, y in all_positions
    }

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" class="workflow-svg" '
        f'role="img" aria-label="MEGFlow preprocessing workflow">',
        "<defs>",
        f'<marker id="{mid}-arrow" markerWidth="7" markerHeight="7" refX="6.5" refY="3.5" orient="auto" markerUnits="userSpaceOnUse">',
        '<path d="M0,0 L7,3.5 L0,7 z" class="wf-arrowhead" />',
        "</marker>",
        "</defs>",
    ]

    def draw_lane(row_positions: list[tuple[dict[str, Any], float, float]], label: str) -> None:
        if not row_positions:
            return
        left = min(x for _, x, _ in row_positions) - 12
        right = max(x + box_w for _, x, _ in row_positions) + 12
        y = row_positions[0][2]
        parts.append(
            f'<rect x="{left:.1f}" y="{y - lane_pad_y:.1f}" width="{right - left:.1f}" '
            f'height="{box_h + lane_pad_y * 1.5:.1f}" rx="16" class="wf-lane-bg" />'
            f'<text x="{left + 10:.1f}" y="{y - 7:.1f}" class="wf-lane-label">{html.escape(label)}</text>'
        )

    if data_pos:
        draw_lane(data_pos, "MEG data")
    if model_pos:
        model_label = (
            "Anatomy & modeling"
            if "anatomy_structural" in pos_by_key
            else "Registration & modeling"
        )
        draw_lane(model_pos, model_label)

    ports: set[tuple[float, float]] = set()
    top_route_index = 0
    bottom_route_index = 0
    cross_route_index = 0

    def has_intermediate_node(source_key: str, target_key: str, lane: str) -> bool:
        source_column = column_by_key[source_key]
        target_column = column_by_key[target_key]
        low, high = sorted((source_column, target_column))
        return any(
            semantic_lane(node) == lane
            and low < column_by_key[node["key"]] < high
            for node in nodes
        )

    def append_edge(
        source: dict[str, Any],
        target: dict[str, Any],
        path_data: str,
        class_names: str,
    ) -> None:
        source_key = html.escape(str(source["key"]))
        target_key = html.escape(str(target["key"]))
        title = html.escape(f'{source["label"]} -> {target["label"]}')
        parts.append(
            f'<g class="wf-edge-group" data-from="{source_key}" data-to="{target_key}">'
            f'<title>{title}</title>'
            f'<path d="{path_data}" class="{class_names}" marker-end="url(#{mid}-arrow)" />'
            "</g>"
        )

    for target in nodes:
        if target["key"] not in pos_by_key:
            continue
        target_node, target_x, target_y = pos_by_key[target["key"]]
        for source_key in target.get("depends_on", []):
            if source_key not in pos_by_key:
                continue
            source, source_x, source_y = pos_by_key[source_key]
            source_lane = semantic_lane(source)
            target_lane = semantic_lane(target_node)
            same_lane = source_lane == target_lane
            forward = column_by_key[source_key] < column_by_key[target_node["key"]]
            anatomy_to_coregistration = (
                same_lane
                and source_key == "anatomy_structural"
                and target_node["key"] == "coregistration"
            )
            direct = (
                same_lane
                and forward
                and not anatomy_to_coregistration
                and not has_intermediate_node(source_key, target_node["key"], source_lane)
            )

            if direct:
                start = (source_x + box_w, source_y + box_h / 2.0)
                end = (target_x, target_y + box_h / 2.0)
                ports.update((start, end))
                append_edge(
                    source,
                    target_node,
                    f"M{start[0]:.1f},{start[1]:.1f} H{end[0]:.1f}",
                    "wf-edge wf-edge-direct",
                )
                continue

            source_center_x = source_x + box_w / 2.0
            target_center_x = target_x + box_w / 2.0
            if anatomy_to_coregistration:
                track_y = source_y + box_h + 22.0 + bottom_route_index * 12.0
                bottom_route_index += 1
                start = (source_x + box_w, source_y + box_h / 2.0)
                end = (target_center_x, target_y + box_h)
                ports.update((start, end))
                path_data = (
                    f"M{start[0]:.1f},{start[1]:.1f} V{track_y:.1f} "
                    f"H{end[0]:.1f} V{end[1]:.1f}"
                )
                append_edge(source, target_node, path_data, "wf-edge wf-edge-routed")
                continue

            if (
                not same_lane
                and target_node["key"] == "coregistration"
                and source_key in {"ica", "artifacts"}
            ):
                start = (source_center_x, source_y + box_h)
                end = (target_x, target_y + box_h / 2.0)
                ports.update((start, end))
                append_edge(
                    source,
                    target_node,
                    f"M{start[0]:.1f},{start[1]:.1f} V{end[1]:.1f} H{end[0]:.1f}",
                    "wf-edge wf-edge-routed wf-edge-cross-lane",
                )
                continue

            if (
                not same_lane
                and source_key == "headmodel"
                and target_node["key"] == "source"
            ):
                start = (source_x + box_w, source_y + box_h / 2.0)
                end = (target_center_x, target_y + box_h)
                ports.update((start, end))
                append_edge(
                    source,
                    target_node,
                    f"M{start[0]:.1f},{start[1]:.1f} H{end[0]:.1f} V{end[1]:.1f}",
                    "wf-edge wf-edge-routed wf-edge-cross-lane",
                )
                continue

            if same_lane and source_lane == "data":
                track_y = max(14.0, y_data - 24.0 - top_route_index * 12.0)
                top_route_index += 1
                start = (source_center_x, source_y)
                end = (target_center_x, target_y)
                ports.update((start, end))
                path_data = (
                    f"M{start[0]:.1f},{start[1]:.1f} V{track_y:.1f} "
                    f"H{end[0]:.1f} V{end[1]:.1f}"
                )
                append_edge(source, target_node, path_data, "wf-edge wf-edge-routed")
                continue

            if same_lane:
                track_y = source_y + box_h + 22.0 + bottom_route_index * 12.0
                bottom_route_index += 1
                start = (source_center_x, source_y + box_h)
                end = (target_center_x, target_y + box_h)
                ports.update((start, end))
                path_data = (
                    f"M{start[0]:.1f},{start[1]:.1f} V{track_y:.1f} "
                    f"H{end[0]:.1f} V{end[1]:.1f}"
                )
                append_edge(source, target_node, path_data, "wf-edge wf-edge-routed")
                continue

            if source_lane == "data":
                start = (source_center_x, source_y + box_h)
                end = (target_center_x, target_y)
            else:
                start = (source_center_x, source_y)
                end = (target_center_x, target_y + box_h)
            middle_top = y_data + box_h
            middle_bottom = y_model
            track_y = middle_top + (cross_route_index + 1) * (
                (middle_bottom - middle_top) / 3.0
            )
            cross_route_index = (cross_route_index + 1) % 2
            ports.update((start, end))
            path_data = (
                f"M{start[0]:.1f},{start[1]:.1f} V{track_y:.1f} "
                f"H{end[0]:.1f} V{end[1]:.1f}"
            )
            append_edge(
                source,
                target_node,
                path_data,
                "wf-edge wf-edge-routed wf-edge-cross-lane",
            )

    def draw_node(node: dict[str, Any], x: float, y: float) -> None:
        st = statuses.get(node["key"], "missing")
        cls = _status_class(st)
        status_label = _status_label(st)
        lines = _node_label_lines(str(node["label"]), max_chars=22 if box_w >= 190 else 18)
        title_y = y + (30 if len(lines) == 1 else 24)
        pill_w = max(58.0, 24.0 + len(status_label) * 6.6)
        pill_x = x + box_w - pill_w - 16
        pill_y = y + box_h - 30
        title = f'{node["label"]}: {status_label}'
        parts.append(
            f'<g><title>{html.escape(title)}</title>'
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{box_w:.1f}" height="{box_h:.1f}" rx="{rx:.1f}" '
            f'class="wf-node-card {cls}" />'
            f'<rect x="{x:.1f}" y="{y + 14:.1f}" width="5" height="{box_h - 28:.1f}" rx="2.5" '
            f'class="wf-status-rail {cls}" />'
        )
        for idx, line in enumerate(lines):
            parts.append(
                f'<text x="{x + 22:.1f}" y="{title_y + idx * 15:.1f}" class="wf-text">'
                f"{html.escape(line)}</text>"
            )
        parts.append(
            f'<rect x="{pill_x:.1f}" y="{pill_y:.1f}" width="{pill_w:.1f}" height="21" rx="10.5" '
            f'class="wf-node-pill {cls}" />'
            f'<text x="{pill_x + pill_w / 2:.1f}" y="{pill_y + 14.2:.1f}" text-anchor="middle" '
            f'class="wf-node-status {cls}">{html.escape(status_label)}</text></g>'
        )

    for node, x, y in all_positions:
        draw_node(node, x, y)
    for x, y in sorted(ports):
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" class="wf-port" />')
    parts.append("</svg>")
    return "".join(parts)


def render_workflow_dataset_html(ctx: dict[str, Any], subject_summaries: list[dict[str, Any]]) -> str:
    nodes = ctx.get("nodes") or []
    if not nodes:
        return (
            f'<div class="section workflow-section"><h2>{WORKFLOW_SECTION_TITLE}</h2>'
            '<p class="workflow-subtitle">No preprocessing diagram for this run mode.</p>'
            '<div class="panel workflow-panel">'
            f'<div class="info-note workflow-footnote">{html.escape(ctx.get("footnote", ""))}</div></div></div>'
        )

    svg = _render_svg(nodes, lambda n: _node_dataset_status(n, subject_summaries))
    meta = ctx.get("manifest") if isinstance(ctx.get("manifest"), dict) else {}
    detail_groups = _workflow_detail_groups(meta)
    if detail_groups:
        group_html = []
        for title, rows in detail_groups:
            row_blocks = []
            for k, v in rows:
                help_text = _detail_help(k)
                help_html = f'<div class="wf-detail-help">{html.escape(help_text)}</div>' if help_text else ""
                row_blocks.append(
                    f'<div class="workflow-detail-row"><dt class="wf-detail-k">{html.escape(_detail_label(k))}</dt>'
                    f'<dd class="{_detail_value_class(k)}">{html.escape(v)}{help_html}</dd></div>'
                )
            rows_html = "".join(row_blocks)
            group_class = _detail_group_class(title)
            group_html.append(
                f'<section class="{group_class}">'
                f'<h3 class="workflow-detail-title">{html.escape(title)}</h3>'
                f'<dl class="workflow-detail-list">{rows_html}</dl>'
                "</section>"
            )
        details_block = f'<div class="workflow-details-grid">{"".join(group_html)}</div>'
    else:
        details_block = (
            '<p class="small workflow-details-hint">No curated summary fields in the manifest.</p>'
        )

    manifest_hint = (
        '<p class="small workflow-manifest-hint">Provenance: '
        '<a href="data/megflow_run_manifest.json">megflow_run_manifest.json</a> (bundled run manifest).</p>'
    )
    config_hint = _nextflow_config_hint_html(ctx)

    return f"""
<div class="section workflow-section">
  <h2>{WORKFLOW_SECTION_TITLE}</h2>
  <p class="workflow-subtitle">Planned preprocessing stages and dataset status (from manifest / config).</p>
  <div class="panel workflow-panel">
    <div class="info-note workflow-footnote">{html.escape(ctx.get("footnote", ""))}</div>
    <div class="workflow-svg-wrap">{svg}</div>
    <div class="workflow-legend">
      <span class="wf-legend wf-done">Complete</span>
      <span class="wf-legend wf-partial">Partially complete</span>
      <span class="wf-legend wf-missing">Missing expected outputs</span>
    </div>
    <div class="workflow-link-row">
      {manifest_hint}
      {config_hint}
    </div>
    {details_block}
  </div>
</div>
"""


def workflow_meta_for_json(ctx: dict[str, Any]) -> dict[str, Any]:
    """Small serializable summary for dataset_summary.json."""
    m = ctx.get("manifest") or {}
    snap = m.get("params_snapshot") if isinstance(m, dict) else {}
    wf = m.get("workflow_meta") if isinstance(m, dict) else {}
    return {
        "source": ctx.get("source"),
        "steps_raw": ctx.get("steps_raw"),
        "manifest_path": ctx.get("manifest_path"),
        "node_keys": [n["key"] for n in ctx.get("nodes") or []],
        "workflow_meta": wf,
        "params_snapshot": snap,
        "nextflow_config_bundled": bool(ctx.get("nextflow_config_bundled")),
        "nextflow_config_source_name": ctx.get("nextflow_config_source_name"),
    }
