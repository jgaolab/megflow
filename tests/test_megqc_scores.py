import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image


MEGQC_DIR = Path(__file__).resolve().parents[1] / "megflow" / "tools" / "megqc"
if str(MEGQC_DIR) not in sys.path:
    sys.path.insert(0, str(MEGQC_DIR))

import score_meg_reference_quota_standalone as scorer


class NormativeQualityScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = json.loads(
            (MEGQC_DIR / "metric_config_reference_quota.json").read_text(encoding="utf-8")
        )
        cls.model = config["models"][config["default_model"]]
        cls.reference = pd.read_csv(
            MEGQC_DIR / "reference_intervals_reference_quota.csv",
            low_memory=False,
        )

    def metrics_at_global_median(self, component_types=None):
        component_types = set(component_types or {"MAG", "GRAD"})
        metrics = {}
        for family in self.model["families"]:
            for metric in family["metrics"]:
                if scorer.metric_component_type(metric) not in component_types:
                    continue
                reference_rows = self.reference[
                    (self.reference["metric"].astype(str) == metric)
                    & (self.reference["scope"].astype(str) == "global")
                ]
                if not reference_rows.empty:
                    metrics[metric] = float(reference_rows.iloc[0]["q50"])
        return metrics

    def score(self, component_types=None):
        return scorer.score_metrics(
            self.metrics_at_global_median(component_types),
            self.model,
            self.reference,
            "ALL",
            "ALL",
            "global",
            1,
        )

    def test_family_scores_preserve_display_labels_and_overall_mean(self):
        summary, detail = self.score()

        family_scores = summary["family_scores"]
        self.assertEqual(len(family_scores), 8)
        self.assertEqual(family_scores[0]["display_label"], "Max absolute difference, absolute Q95")
        self.assertEqual(family_scores[6]["display_label"], "Peak-to-peak amplitude, absolute Q95")
        self.assertEqual(family_scores[6]["domain"], "Statistical")
        self.assertEqual(family_scores[0]["components"], ["MAG", "GRAD"])
        self.assertIn("family_display_label", detail.columns)
        self.assertIn("component_type", detail.columns)

        available = [item["score_0_100"] for item in family_scores if np.isfinite(item["score_0_100"])]
        self.assertAlmostEqual(summary["score_0_100"], float(np.mean(available)), places=12)

    def test_mag_only_components_produce_mag_only_family_scores(self):
        summary, _ = self.score({"MAG"})

        self.assertEqual(summary["n_families_available"], 8)
        for family in summary["family_scores"]:
            self.assertEqual(family["components"], ["MAG"])
            self.assertEqual(family["n_components"], 1)

    def test_plot_uses_family_domain_order_and_writes_png(self):
        summary, _ = self.score()
        rows = scorer._family_score_plot_rows(summary)
        domains = [row["domain"] for row in rows]
        self.assertEqual(
            domains,
            ["Temporal"] * 4 + ["Statistical"] + ["Spectral"] * 2 + ["Fractal"],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "normative_quality_score.png"
            scorer.draw_quality_score_plot(summary, output_path)
            self.assertTrue(output_path.is_file())
            with Image.open(output_path) as image:
                self.assertEqual(image.format, "PNG")
                self.assertGreater(image.width, 1500)
                self.assertGreater(image.height, 800)
                self.assertGreater(np.asarray(image.convert("RGB")).std(), 5.0)


if __name__ == "__main__":
    unittest.main()
