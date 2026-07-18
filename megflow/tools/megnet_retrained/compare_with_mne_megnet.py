#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import importlib
import json
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Dict, Sequence

import numpy as np

if __package__:
    from .inference import (
        CLASS_NAMES,
        canonical_labels,
        predict_components,
        sha256_file,
    )
    from .runtime.preprocessing import read_ica, read_raw_fif
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from megflow.tools.megnet_retrained.inference import (
        CLASS_NAMES,
        canonical_labels,
        predict_components,
        sha256_file,
    )
    from megflow.tools.megnet_retrained.runtime.preprocessing import (
        read_ica,
        read_raw_fif,
    )


MNE_NATIVE_CLASS_NAMES = (
    "brain_or_other",
    "eye_movement",
    "heart_beat",
    "eye_blink",
)


def reorder_mne_probabilities(probabilities: np.ndarray) -> np.ndarray:
    probabilities = np.asarray(probabilities, dtype=np.float32)
    if probabilities.ndim != 2 or probabilities.shape[1] != len(CLASS_NAMES):
        raise ValueError("MNE MEGNet probabilities must contain four class columns")
    native_index = {
        class_name: index for index, class_name in enumerate(MNE_NATIVE_CLASS_NAMES)
    }
    return probabilities[
        :,
        [native_index[class_name] for class_name in CLASS_NAMES],
    ]


def comparison_metrics(
    original_labels: Sequence[str],
    retrained_labels: Sequence[str],
) -> Dict[str, Any]:
    original_labels = list(original_labels)
    retrained_labels = list(retrained_labels)
    if len(original_labels) != len(retrained_labels):
        raise ValueError("Models must return the same component count")

    component_count = len(original_labels)
    disagreement_indices = [
        index
        for index, (original, retrained) in enumerate(
            zip(original_labels, retrained_labels)
        )
        if original != retrained
    ]
    original_artifacts = {
        index
        for index, label in enumerate(original_labels)
        if label != "brain_or_other"
    }
    retrained_artifacts = {
        index
        for index, label in enumerate(retrained_labels)
        if label != "brain_or_other"
    }
    artifact_union = original_artifacts | retrained_artifacts
    artifact_intersection = original_artifacts & retrained_artifacts
    component_agreement = (
        (component_count - len(disagreement_indices)) / component_count
        if component_count
        else 1.0
    )
    artifact_jaccard = (
        len(artifact_intersection) / len(artifact_union)
        if artifact_union
        else 1.0
    )
    return {
        "component_count": component_count,
        "matching_component_count": component_count - len(disagreement_indices),
        "component_agreement": float(component_agreement),
        "artifact_jaccard": float(artifact_jaccard),
        "original_artifact_indices": sorted(original_artifacts),
        "retrained_artifact_indices": sorted(retrained_artifacts),
        "artifact_intersection_indices": sorted(artifact_intersection),
        "artifact_union_indices": sorted(artifact_union),
        "disagreement_indices": disagreement_indices,
    }


def component_rows(
    original_probabilities: np.ndarray,
    retrained_probabilities: np.ndarray,
) -> list[Dict[str, Any]]:
    original_probabilities = np.asarray(original_probabilities, dtype=np.float32)
    retrained_probabilities = np.asarray(retrained_probabilities, dtype=np.float32)
    if original_probabilities.shape != retrained_probabilities.shape:
        raise ValueError("Models must return probability arrays with the same shape")
    original_labels = canonical_labels(original_probabilities)
    retrained_labels = canonical_labels(retrained_probabilities)
    rows = []
    for component_idx, (original_label, retrained_label) in enumerate(
        zip(original_labels, retrained_labels)
    ):
        row: Dict[str, Any] = {
            "component_idx": component_idx,
            "original_label": original_label,
            "retrained_label": retrained_label,
            "disagrees": original_label != retrained_label,
            "original_is_artifact": original_label != "brain_or_other",
            "retrained_is_artifact": retrained_label != "brain_or_other",
        }
        for class_idx, class_name in enumerate(CLASS_NAMES):
            row[f"original_prob_{class_name}"] = float(
                original_probabilities[component_idx, class_idx]
            )
            row[f"retrained_prob_{class_name}"] = float(
                retrained_probabilities[component_idx, class_idx]
            )
        rows.append(row)
    return rows


def _mne_predictor_and_metadata():
    module = importlib.import_module("mne_icalabel.megnet.label_components")
    predictor = module.megnet_label_components
    model_path_value = getattr(module, "_MODEL_PATH", None)
    model_path = Path(model_path_value).resolve() if model_path_value else None
    try:
        package_version = version("mne-icalabel")
    except PackageNotFoundError:
        package_version = None
    metadata = {
        "backend": "mne_icalabel.megnet",
        "mne_icalabel_version": package_version,
        "native_class_order": list(MNE_NATIVE_CLASS_NAMES),
        "canonical_class_order": list(CLASS_NAMES),
        "model_file": str(model_path) if model_path else None,
        "model_sha256": (
            sha256_file(model_path) if model_path and model_path.is_file() else None
        ),
    }
    return predictor, metadata


def run_comparison(
    raw,
    ica,
    *,
    ica_sources_file: Path | None = None,
    device: str = "cpu",
    mne_predictor=None,
    retrained_predictor=None,
):
    if mne_predictor is None:
        mne_predictor, original_metadata = _mne_predictor_and_metadata()
    else:
        original_metadata = {
            "backend": "injected_mne_megnet_predictor",
            "native_class_order": list(MNE_NATIVE_CLASS_NAMES),
            "canonical_class_order": list(CLASS_NAMES),
        }
    native_original_probabilities = mne_predictor(raw, ica)
    original_probabilities = reorder_mne_probabilities(
        native_original_probabilities
    )

    retrained_predictor = retrained_predictor or predict_components
    retrained_result = retrained_predictor(
        raw,
        ica,
        ica_sources_file=ica_sources_file,
        device=device,
    )
    retrained_probabilities = np.asarray(
        retrained_result.probabilities,
        dtype=np.float32,
    )
    if original_probabilities.shape != retrained_probabilities.shape:
        raise ValueError(
            "Original and retrained models returned different probability shapes: "
            f"{original_probabilities.shape} vs {retrained_probabilities.shape}"
        )

    original_labels = canonical_labels(original_probabilities)
    retrained_labels = canonical_labels(retrained_probabilities)
    metrics = comparison_metrics(original_labels, retrained_labels)
    rows = component_rows(original_probabilities, retrained_probabilities)
    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "description": "Model agreement without human ground-truth labels",
        "class_order": list(CLASS_NAMES),
        "metrics": metrics,
        "models": {
            "mne_icalabel": original_metadata,
            "megnet_retrained": dict(retrained_result.metadata),
        },
        "predictions": {
            "mne_icalabel": {
                "labels": original_labels,
                "probabilities": original_probabilities.astype(float).tolist(),
            },
            "megnet_retrained": {
                "labels": retrained_labels,
                "probabilities": retrained_probabilities.astype(float).tolist(),
            },
        },
    }
    return payload, rows


def write_comparison(output_dir: Path, payload, rows, *, overwrite: bool) -> None:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "comparison.json"
    csv_path = output_dir / "component_comparison.csv"
    existing = [path for path in (json_path, csv_path) if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "Comparison outputs already exist; pass --overwrite: "
            + ", ".join(str(path) for path in existing)
        )

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fieldnames = list(rows[0]) if rows else ["component_idx"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare original MNE-ICALabel MEGNet and retrained MEGNet on "
            "the same raw/ICA input."
        )
    )
    parser.add_argument("--raw-file", type=Path, required=True)
    parser.add_argument("--ica-file", type=Path, required=True)
    parser.add_argument("--ica-sources-file", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_file = args.raw_file.expanduser().resolve()
    ica_file = args.ica_file.expanduser().resolve()
    raw = read_raw_fif(raw_file, preload=True)
    ica = read_ica(ica_file)
    payload, rows = run_comparison(
        raw,
        ica,
        ica_sources_file=args.ica_sources_file,
        device=str(args.device),
    )
    payload["inputs"] = {
        "raw_file": str(raw_file),
        "ica_file": str(ica_file),
        "ica_sources_file": (
            str(args.ica_sources_file.expanduser().resolve())
            if args.ica_sources_file is not None
            else None
        ),
    }
    write_comparison(
        args.output_dir,
        payload,
        rows,
        overwrite=bool(args.overwrite),
    )
    print(json.dumps(payload["metrics"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
