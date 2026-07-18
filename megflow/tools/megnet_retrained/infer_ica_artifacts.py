#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import numpy as np

if __package__:
    from .inference import (
        CLASS_NAMES,
        DISPLAY_NAMES,
        default_cpu_threads,
        predict_components,
    )
    from .runtime.preprocessing import read_ica, read_raw_fif
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from megflow.tools.megnet_retrained.inference import (
        CLASS_NAMES,
        DISPLAY_NAMES,
        default_cpu_threads,
        predict_components,
    )
    from megflow.tools.megnet_retrained.runtime.preprocessing import (
        read_ica,
        read_raw_fif,
    )


LOG = logging.getLogger("megnet_onnx_inference")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Identify ECG, EOG-blink, and EOG-movement ICA components with "
            "the retrained MEGNet ONNX model."
        )
    )
    parser.add_argument("--raw-file", type=Path, required=True)
    parser.add_argument("--ica-file", type=Path, required=True)
    parser.add_argument("--ica-sources-file", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--device",
        default="cpu",
        help="cpu (recommended), cuda, cuda:N, or auto. auto uses CPU.",
    )
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument(
        "--max-flat-windows",
        type=int,
        default=128,
        help="Cap components per batch so batch_size * temporal_windows stays bounded.",
    )
    parser.add_argument("--intra-op-threads", type=int, default=default_cpu_threads())
    parser.add_argument("--ch-type", default="auto")
    parser.add_argument("--save-topomaps", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    return parser.parse_args()


def ensure_output_dir(output_dir: Path, *, overwrite: bool) -> Path:
    output_dir = output_dir.expanduser().resolve()
    known_outputs = (
        "component_predictions.csv",
        "ica_labels.json",
        "artifact_ics.txt",
        "prediction_metadata.json",
    )
    existing = [output_dir / name for name in known_outputs if (output_dir / name).exists()]
    if existing and not overwrite:
        raise FileExistsError(
            f"Output files already exist under {output_dir}; pass --overwrite: "
            + ", ".join(path.name for path in existing)
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def write_predictions(output_dir: Path, result) -> Dict[str, list[int]]:
    fields = [
        "component_idx",
        "pred_label",
        "pred_class",
        "pred_display_name",
        "is_artifact",
        *[f"prob_{name}" for name in CLASS_NAMES],
    ]
    class_to_index = {name: index for index, name in enumerate(CLASS_NAMES)}
    with (output_dir / "component_predictions.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for component_idx, class_name in enumerate(result.labels):
            label_index = class_to_index[class_name]
            row: Dict[str, Any] = {
                "component_idx": component_idx,
                "pred_label": label_index,
                "pred_class": class_name,
                "pred_display_name": DISPLAY_NAMES[label_index],
                "is_artifact": int(label_index != 0),
            }
            for class_idx, name in enumerate(CLASS_NAMES):
                row[f"prob_{name}"] = float(
                    result.probabilities[component_idx, class_idx]
                )
            writer.writerow(row)

    labels = np.asarray([class_to_index[label] for label in result.labels], dtype=int)
    labels_json = {
        "eog_saccade_indices": np.flatnonzero(labels == 3).astype(int).tolist(),
        "eog_blink_indices": np.flatnonzero(labels == 2).astype(int).tolist(),
        "ecg_indices": np.flatnonzero(labels == 1).astype(int).tolist(),
    }
    (output_dir / "ica_labels.json").write_text(
        json.dumps(labels_json, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "artifact_ics.txt").write_text(
        "".join(f"{index}\n" for index in result.artifact_indices),
        encoding="utf-8",
    )
    return labels_json


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    output_dir = ensure_output_dir(args.output_dir, overwrite=bool(args.overwrite))
    raw_file = args.raw_file.expanduser().resolve()
    ica_file = args.ica_file.expanduser().resolve()
    raw = read_raw_fif(raw_file, preload=True)
    ica = read_ica(ica_file)
    result = predict_components(
        raw,
        ica,
        ica_sources_file=args.ica_sources_file,
        device=str(args.device),
        batch_size=int(args.batch_size),
        max_flat_windows=int(args.max_flat_windows),
        intra_op_threads=int(args.intra_op_threads),
        ch_type=str(args.ch_type),
        save_topomaps_dir=(output_dir / "clean_topomaps") if args.save_topomaps else None,
    )
    labels_json = write_predictions(output_dir, result)
    metadata = {
        "schema_version": 2,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "raw_file": str(raw_file),
            "ica_file": str(ica_file),
            "ica_sources_file": (
                str(args.ica_sources_file.expanduser().resolve())
                if args.ica_sources_file is not None
                else None
            ),
        },
        "inference": result.metadata,
        "results": {
            "num_components": len(result.labels),
            "num_artifact_components": len(result.artifact_indices),
            "ica_labels": labels_json,
            "mean_max_probability": float(result.probabilities.max(axis=1).mean()),
        },
    }
    (output_dir / "prediction_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {
        "output_dir": str(output_dir),
        "backend": result.metadata["backend"],
        "device": result.metadata["resolved_device"],
        "original_sfreq_hz": result.original_sfreq,
        "effective_sfreq_hz": result.effective_sfreq,
        "num_components": len(result.labels),
        "num_artifact_components": len(result.artifact_indices),
        "class_counts": result.metadata["class_counts"],
        "elapsed_seconds": round(float(result.metadata["elapsed_seconds"]), 3),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
