#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normative Reference MEG quality scoring entrypoint.

This wrapper calls the deployment scorer under ``tools/megqc`` and normalizes
its outputs for the Nextflow pipeline and static HTML report.  It is deliberately
fail-soft: unreadable or unsupported files still produce machine-readable output
with a null score so cohort runs can continue and surface the failure in QC.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

MEGQC_DIR = Path(__file__).resolve().parent / "tools" / "megqc"
if str(MEGQC_DIR) not in sys.path:
    sys.path.insert(0, str(MEGQC_DIR))

try:  # noqa: E402
    from .utils import infer_reference_device_type
except ImportError:  # pragma: no cover - script execution path
    from utils import infer_reference_device_type  # type: ignore
from score_meg_reference_quota_standalone import (  # noqa: E402
    DEFAULT_MODEL,
    apply_reference_preprocessing,
    compute_metric_values,
    draw_reference_position_plot,
    load_optional_mne,
    score_metrics,
)


def str_to_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def fnum(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if hasattr(value, "item"):
        try:
            return json_ready(value.item())
        except Exception:
            pass
    return value


def write_summary_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(json_ready(payload), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def input_stem(path: Path) -> str:
    name = path.name
    for suffix in (".fif.gz", ".fif"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def infer_category(path: Path, requested: str) -> str:
    value = str(requested or "").strip().lower()
    if value and value != "auto":
        return value
    text = path.name.lower()
    if any(token in text for token in ("rest", "resting", "emptyroom", "empty-room")):
        return "rest"
    return "task"


def read_raw_meg(path: Path) -> Any:
    """Read common MEG raw inputs with MNE's generic reader when available."""
    mne = load_optional_mne()
    generic_reader = getattr(mne.io, "read_raw", None)
    if generic_reader is not None:
        try:
            return generic_reader(str(path), preload=True, verbose="error")
        except Exception:
            if not str(path).lower().endswith((".fif", ".fif.gz")):
                raise
    return mne.io.read_raw_fif(str(path), preload=True, verbose="error")


def load_config(config_path: Path, model: str) -> dict[str, Any]:
    config_all = json.loads(config_path.read_text(encoding="utf-8"))
    models = config_all.get("models", {})
    if model not in models:
        raise ValueError(f"Unknown MEG QC model {model}. Available models: {', '.join(models)}")
    return models[model]


def write_placeholder_png(path: Path, message: str) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (1100, 360), "white")
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 24)
        except Exception:
            font = ImageFont.load_default()
        draw.text((40, 48), "MEG QC score unavailable", fill="#111827", font=font)
        draw.text((40, 100), message[:500], fill="#B42318", font=font)
        image.save(path)
    except Exception:
        # Last resort: create a tiny valid PNG from a known byte sequence.
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00"
            b"\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
        )


def write_failure_outputs(
    *,
    args: argparse.Namespace,
    stem: str,
    summary_path: Path,
    component_path: Path,
    figure_path: Path,
    error: Exception,
) -> None:
    component = pd.DataFrame(
        [
            {
                "family": "",
                "domain": "",
                "metric": "",
                "raw_value": "",
                "mode": "",
                "direction": "",
                "reference_scope_used": "",
                "reference_device": "",
                "reference_category": "",
                "q05": "",
                "q50": "",
                "q95": "",
                "reference_position_q05_0_q95_1": "",
                "component_score_0_1": "",
                "status": "scoring_failed",
                "interpretation": str(error),
            }
        ]
    )
    component.to_csv(component_path, index=False)
    write_placeholder_png(figure_path, str(error))
    summary = {
        "model": args.model,
        "raw_file": str(args.input),
        "score_0_100": None,
        "score_scale": "0-100; higher is better",
        "score_higher_is_better": True,
        "status": "scoring_failed",
        "error": str(error),
        "traceback": traceback.format_exc(limit=8),
        "device_type": str(args.meg_vendor),
        "meg_vendor_requested": str(args.meg_vendor),
        "category": infer_category(args.input, args.category),
        "reference_scope": args.reference_scope,
        "reference_preprocessing": [],
        "bad_channel_policy": "omit raw.info['bads']" if str_to_bool(getattr(args, "omit_bad_channels", "false")) else "keep raw.info['bads']",
        "bad_annotation_policy": "keep BAD annotations" if str_to_bool(getattr(args, "keep_bad_annotations", "true")) else "omit BAD annotations",
        "processing_min_score": args.min_score,
        "alarm_score_threshold": args.alarm_score,
        "passed_processing_threshold": False,
        "quality_alarm": True,
        "component_scores_file": str(component_path),
        "reference_position_plot": str(figure_path),
        "output_stem": stem,
    }
    write_summary_json(summary_path, summary)


def score_file(args: argparse.Namespace) -> Path:
    args.input = Path(args.input)
    args.output_dir = Path(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    stem = input_stem(args.input)
    out_prefix = args.output_dir / f"{stem}.{args.model}"
    summary_path = Path(f"{out_prefix}.summary.json")
    component_path = Path(f"{out_prefix}.component_scores.csv")
    figure_path = Path(f"{out_prefix}.reference_position.png")

    try:
        config = load_config(Path(args.config), args.model)
        ref_df = pd.read_csv(args.reference_csv, low_memory=False)
        raw = read_raw_meg(args.input)
        device_type = infer_reference_device_type(raw, args.meg_vendor)
        category = infer_category(args.input, args.category)
        scorer_args = SimpleNamespace(
            omit_bad_annotations=not str_to_bool(args.keep_bad_annotations),
            omit_bad_channels=str_to_bool(args.omit_bad_channels),
            freq_max_samples=int(args.freq_max_samples),
            dfa_max_samples=int(args.dfa_max_samples),
            dfa_method=args.dfa_method,
            skip_dfa=str_to_bool(args.skip_dfa),
            n_jobs=int(args.n_jobs),
            seg_length=int(args.seg_length),
            preproc_config=args.preproc_config,
        )
        raw, preprocessing_steps = apply_reference_preprocessing(raw, scorer_args)
        metrics = compute_metric_values(raw, scorer_args)
        summary, detail = score_metrics(
            metrics,
            config,
            ref_df,
            device_type,
            category,
            args.reference_scope,
            int(args.min_reference_n),
        )

        detail.to_csv(component_path, index=False)
        score = fnum(summary.get("score_0_100"))
        draw_reference_position_plot(
            detail,
            figure_path,
            title=f"Normative Reference MEG QC score: {score:.1f} / 100" if score is not None else "Normative Reference MEG QC score: unavailable",
            subtitle=f"Model {args.model}  ·  Reference scope: {args.reference_scope}  ·  Category: {category}",
        )

        summary.update(
            {
                "raw_file": str(args.input),
                "meg_vendor_requested": str(args.meg_vendor),
                "score_scale": "0-100; higher is better",
                "score_higher_is_better": True,
                "status": "ok" if score is not None else "missing_score",
                "reference_preprocessing": preprocessing_steps,
                "bad_channel_policy": "omit raw.info['bads']" if scorer_args.omit_bad_channels else "keep raw.info['bads']",
                "bad_annotation_policy": "omit BAD annotations" if scorer_args.omit_bad_annotations else "keep BAD annotations",
                "processing_min_score": float(args.min_score),
                "alarm_score_threshold": float(args.alarm_score),
                "passed_processing_threshold": bool(score is not None and score >= float(args.min_score)),
                "quality_alarm": bool(score is None or score < float(args.alarm_score)),
                "component_scores_file": str(component_path),
                "reference_position_plot": str(figure_path),
                "output_stem": stem,
            }
        )
        write_summary_json(summary_path, summary)
    except Exception as exc:
        write_failure_outputs(
            args=args,
            stem=stem,
            summary_path=summary_path,
            component_path=component_path,
            figure_path=figure_path,
            error=exc,
        )

    print(summary_path)
    return summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score a MEG file against bundled Normative Reference metrics.")
    parser.add_argument("--input", required=True, type=Path, help="Input MEG raw file or directory.")
    parser.add_argument("--output_dir", required=True, type=Path, help="Directory for QC score outputs.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--config", type=Path, default=MEGQC_DIR / "metric_config_reference_quota.json")
    parser.add_argument("--reference_csv", type=Path, default=MEGQC_DIR / "reference_intervals_reference_quota.csv")
    parser.add_argument(
        "--meg_vendor",
        default="auto",
        help="Case-insensitive MEG vendor/reference device: auto, all, elekta/neuromag, ctf, kit, 4d, quanmag, or quspin.",
    )
    parser.add_argument("--category", default="auto", help="Reference category: rest, task, ALL, or auto from filename.")
    parser.add_argument("--reference_scope", default="device_category", choices=["device_category", "category", "global"])
    parser.add_argument("--min_reference_n", type=int, default=20)
    parser.add_argument("--min_score", type=float, default=0.0, help="Minimum score required for downstream processing.")
    parser.add_argument("--alarm_score", type=float, default=70.0, help="Static-report alarm threshold.")
    parser.add_argument("--freq_max_samples", type=int, default=0)
    parser.add_argument("--dfa_max_samples", type=int, default=20000)
    parser.add_argument("--dfa_method", choices=["msqms", "sampled"], default="msqms")
    parser.add_argument("--skip_dfa", default="false")
    parser.add_argument(
        "--preproc_config",
        default="",
        help="Explicit YAML preprocessing config applied before scoring. No default is applied by the scorer.",
    )
    parser.add_argument(
        "--keep_bad_annotations",
        default="true",
        help="Keep BAD spans (process_1 default). Set false to omit BAD-annotated segments.",
    )
    parser.add_argument(
        "--omit_bad_channels",
        default="false",
        help="Exclude raw.info['bads'] channels. Reference uses all MEG channels (process_1).",
    )
    parser.add_argument(
        "--n_jobs",
        type=int,
        default=-1,
        help="Parallel workers for MEGQC metric computation. Nextflow passes task.cpus; standalone default uses all available cores.",
    )
    parser.add_argument("--seg_length", type=int, default=100)
    return parser.parse_args()


def main() -> None:
    score_file(parse_args())


if __name__ == "__main__":
    main()
