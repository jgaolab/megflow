#!/usr/bin/env python3
# coding: utf-8
"""Smoke tests for the standalone reference-quota scorer."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
SCORER = SCRIPT_DIR / "score_meg_reference_quota_standalone.py"


def load_scorer():
    spec = importlib.util.spec_from_file_location("score_meg_reference_quota_standalone", SCORER)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load scorer module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    source = SCORER.read_text(encoding="utf-8")
    banned = [
        r"^\s*import\s+tsfel\b",
        r"^\s*from\s+tsfel\b",
        r"^\s*import\s+msqms\b",
        r"^\s*from\s+msqms\b",
    ]
    hits = [pattern for pattern in banned if re.search(pattern, source, flags=re.MULTILINE)]
    if hits:
        raise SystemExit(f"standalone dependency check failed: {hits}")

    scorer = load_scorer()
    config = scorer.json.loads((SCRIPT_DIR / "metric_config_reference_quota.json").read_text(encoding="utf-8"))
    model = config["models"][config["default_model"]]
    ref_df = pd.read_csv(SCRIPT_DIR / "reference_intervals_reference_quota.csv", low_memory=False)

    metrics = {}
    for family in model["families"]:
        for metric in family["metrics"]:
            sub = ref_df[(ref_df["metric"].astype(str) == metric) & (ref_df["scope"].astype(str) == "global")]
            if not sub.empty:
                metrics[metric] = float(sub.iloc[0]["q50"])

    summary, detail = scorer.score_metrics(metrics, model, ref_df, "ALL", "ALL", "global", 1)
    if detail.empty:
        raise SystemExit("component detail is empty")
    if not np.isfinite(float(summary["score_0_100"])):
        raise SystemExit("summary score is not finite")
    if int(summary["n_families_available"]) != int(summary["n_families_expected"]):
        raise SystemExit("not all expected families were scored in reference-table smoke test")
    print(
        {
            "standalone": "ok",
            "score_0_100": round(float(summary["score_0_100"]), 6),
            "n_components": int(detail["component_score_0_1"].notna().sum()),
        }
    )


if __name__ == "__main__":
    main()
