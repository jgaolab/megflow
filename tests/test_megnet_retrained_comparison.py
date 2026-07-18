import unittest

import numpy as np

from megflow.tools.megnet_retrained.compare_with_mne_megnet import (
    comparison_metrics,
    component_rows,
    reorder_mne_probabilities,
)


class MegnetComparisonMetricTests(unittest.TestCase):
    def test_agreement_and_artifact_jaccard(self):
        original = [
            "brain_or_other",
            "heart_beat",
            "eye_blink",
            "brain_or_other",
        ]
        retrained = [
            "brain_or_other",
            "eye_movement",
            "eye_blink",
            "brain_or_other",
        ]

        metrics = comparison_metrics(original, retrained)

        self.assertEqual(metrics["component_agreement"], 0.75)
        self.assertEqual(metrics["artifact_jaccard"], 1.0)
        self.assertEqual(metrics["original_artifact_indices"], [1, 2])
        self.assertEqual(metrics["retrained_artifact_indices"], [1, 2])
        self.assertEqual(metrics["disagreement_indices"], [1])

    def test_empty_artifact_sets_have_unit_jaccard(self):
        metrics = comparison_metrics(
            ["brain_or_other"],
            ["brain_or_other"],
        )

        self.assertEqual(metrics["artifact_jaccard"], 1.0)
        self.assertEqual(metrics["component_agreement"], 1.0)

    def test_different_component_counts_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "same component count"):
            comparison_metrics(
                ["brain_or_other"],
                ["brain_or_other", "heart_beat"],
            )


class MegnetComparisonOutputTests(unittest.TestCase):
    def test_mne_native_probability_order_is_normalized(self):
        native = np.asarray([[0.10, 0.20, 0.30, 0.40]], dtype=np.float32)

        canonical = reorder_mne_probabilities(native)

        np.testing.assert_allclose(canonical, [[0.10, 0.30, 0.40, 0.20]])

    def test_component_rows_include_both_probability_vectors_and_disagreement(self):
        original = np.asarray(
            [[0.1, 0.7, 0.1, 0.1], [0.8, 0.1, 0.05, 0.05]],
            dtype=np.float32,
        )
        retrained = np.asarray(
            [[0.1, 0.1, 0.7, 0.1], [0.8, 0.1, 0.05, 0.05]],
            dtype=np.float32,
        )

        rows = component_rows(original, retrained)

        self.assertEqual(rows[0]["original_label"], "heart_beat")
        self.assertEqual(rows[0]["retrained_label"], "eye_blink")
        self.assertTrue(rows[0]["disagrees"])
        self.assertFalse(rows[1]["disagrees"])
        self.assertAlmostEqual(rows[0]["original_prob_heart_beat"], 0.7, places=6)
        self.assertAlmostEqual(rows[0]["retrained_prob_eye_blink"], 0.7, places=6)


if __name__ == "__main__":
    unittest.main()
