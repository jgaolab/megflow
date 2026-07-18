import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np


MEGFLOW_DIR = Path(__file__).resolve().parents[1] / "megflow"
if str(MEGFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(MEGFLOW_DIR))

import run_ica_label


class ComponentScoreMergeTests(unittest.TestCase):
    def test_duplicate_component_score_keeps_maximum(self):
        scores = defaultdict(list, {"eog": [], "eog_indices": []})

        run_ica_label.append_component_score(scores, "eog", 3, 0.61)
        run_ica_label.append_component_score(scores, "eog", 3, 0.84)
        run_ica_label.append_component_score(scores, "eog", 3, 0.72)

        self.assertEqual(scores["eog_indices"], [3])
        self.assertEqual(scores["eog"], [0.84])

    def test_normalize_score_dict_sorts_indices_and_preserves_methods(self):
        scores = {
            "ecg_indices": [4, 1],
            "ecg": [0.6, 0.8],
            "eog_indices": [3, 2],
            "eog": [0.7, 0.9],
            "methods": {"megnet_retrained": {"status": "succeeded"}},
        }

        normalized = run_ica_label.normalize_score_dict(scores, n_components=5)

        self.assertEqual(normalized["ecg_indices"], [1, 4])
        self.assertEqual(normalized["ecg"], [0.8, 0.6])
        self.assertEqual(normalized["eog_indices"], [2, 3])
        self.assertEqual(normalized["eog"], [0.9, 0.7])
        self.assertEqual(normalized["methods"], scores["methods"])


class ExistingLabelOutputTests(unittest.TestCase):
    def test_existing_labels_are_preserved_without_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "marked_components.txt"
            output_file.write_text("3\n", encoding="utf-8")

            self.assertFalse(
                run_ica_label.should_generate_labels(
                    output_file,
                    overwrite_existing=False,
                    refresh_existing=False,
                )
            )

    def test_nextflow_can_explicitly_recompute_existing_labels(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "marked_components.txt"
            output_file.write_text("3\n", encoding="utf-8")

            self.assertTrue(
                run_ica_label.should_generate_labels(
                    output_file,
                    overwrite_existing=True,
                    refresh_existing=False,
                )
            )

    def test_refresh_replaces_an_unchanged_previous_automatic_result(self):
        written, mode = run_ica_label.resolve_marked_component_output(
            auto_indices=[3, 17, 22],
            existing_indices=[3],
            previous_metadata={
                "mode": "auto",
                "auto_indices": [3],
                "written_indices": [3],
            },
            refresh_existing=True,
        )

        self.assertEqual(written, [3, 17, 22])
        self.assertEqual(mode, "auto")

    def test_refresh_preserves_a_manually_edited_component_file(self):
        written, mode = run_ica_label.resolve_marked_component_output(
            auto_indices=[3, 17, 22],
            existing_indices=[3, 9],
            previous_metadata={
                "mode": "auto",
                "auto_indices": [3],
                "written_indices": [3],
            },
            refresh_existing=True,
        )

        self.assertEqual(written, [3, 9])
        self.assertEqual(mode, "preserved_manual")


class MegnetNormalizationTests(unittest.TestCase):
    def test_mne_megnet_probabilities_are_reordered_to_canonical_classes(self):
        native = np.asarray([[0.10, 0.20, 0.30, 0.40]], dtype=np.float32)

        canonical = run_ica_label.canonicalize_mne_megnet_probabilities(native)

        np.testing.assert_allclose(canonical, [[0.10, 0.30, 0.40, 0.20]])

    def test_detector_outcome_maps_ecg_and_both_eog_classes(self):
        probabilities = np.asarray(
            [
                [0.9, 0.05, 0.03, 0.02],
                [0.1, 0.8, 0.05, 0.05],
                [0.1, 0.1, 0.7, 0.1],
                [0.1, 0.1, 0.2, 0.6],
            ],
            dtype=np.float32,
        )

        outcome = run_ica_label.detector_outcome_from_probabilities(
            "megnet_retrained",
            probabilities,
            metadata={"model_sha256": "abc"},
        )

        self.assertEqual(outcome.artifact_indices, [1, 2, 3])
        self.assertEqual(outcome.ecg_indices, [1])
        self.assertEqual(outcome.eog_indices, [2, 3])
        self.assertEqual(outcome.detail["status"], "succeeded")
        self.assertEqual(outcome.detail["labels"], [
            "brain_or_other",
            "heart_beat",
            "eye_blink",
            "eye_movement",
        ])
        self.assertEqual(outcome.detail["metadata"]["model_sha256"], "abc")


class MegnetSwitchAndFailureTests(unittest.TestCase):
    def test_retrained_failure_is_recorded_without_raising(self):
        predictor = mock.Mock(side_effect=RuntimeError("bad model"))

        with self.assertLogs(level="ERROR"):
            result = run_ica_label.run_retrained_detector(
                mock.sentinel.raw,
                mock.sentinel.ica,
                ica_sources_file=None,
                predictor=predictor,
            )

        self.assertEqual(result.artifact_indices, [])
        self.assertEqual(result.detail["status"], "failed")
        self.assertEqual(result.detail["error"]["type"], "RuntimeError")
        self.assertEqual(result.detail["error"]["message"], "bad model")

    def test_disabled_retrained_switch_does_not_call_predictor(self):
        mne_predictor = mock.Mock(
            return_value=np.asarray([[0.9, 0.05, 0.03, 0.02]], dtype=np.float32)
        )
        retrained_predictor = mock.Mock(side_effect=AssertionError("must not run"))

        outcomes = run_ica_label.run_configured_megnet_detectors(
            {"mne_icalabel": True, "megnet_retrained": False},
            mock.sentinel.raw,
            mock.sentinel.ica,
            ica_sources_file=None,
            mne_predictor=mne_predictor,
            retrained_predictor=retrained_predictor,
        )

        self.assertEqual(set(outcomes), {"mne_icalabel"})
        mne_predictor.assert_called_once_with(mock.sentinel.raw, mock.sentinel.ica)
        retrained_predictor.assert_not_called()

    def test_both_megnet_switches_can_run_together(self):
        mne_predictor = mock.Mock(
            return_value=np.asarray([[0.1, 0.1, 0.7, 0.1]], dtype=np.float32)
        )
        retrained_result = SimpleNamespace(
            probabilities=np.asarray([[0.1, 0.1, 0.1, 0.7]], dtype=np.float32),
            metadata={"model_sha256": "abc"},
        )
        retrained_predictor = mock.Mock(return_value=retrained_result)

        outcomes = run_ica_label.run_configured_megnet_detectors(
            {"mne_icalabel": True, "megnet_retrained": True},
            mock.sentinel.raw,
            mock.sentinel.ica,
            ica_sources_file=Path("ica_sources.fif"),
            mne_predictor=mne_predictor,
            retrained_predictor=retrained_predictor,
        )

        self.assertEqual(set(outcomes), {"mne_icalabel", "megnet_retrained"})
        self.assertEqual(outcomes["mne_icalabel"].artifact_indices, [0])
        self.assertEqual(outcomes["megnet_retrained"].artifact_indices, [0])

    def test_retrained_switch_rejects_the_removed_mapping_syntax(self):
        with self.assertRaisesRegex(
            TypeError,
            "megnet_retrained must be a boolean",
        ):
            run_ica_label.run_configured_megnet_detectors(
                {"mne_icalabel": False, "megnet_retrained": {"enabled": False}},
                mock.sentinel.raw,
                mock.sentinel.ica,
            )

    def test_old_ica_label_key_is_not_a_compatibility_alias(self):
        excluded = run_ica_label.collect_exclude_indices(
            {
                "ica_label": False,
                "mne_algorithm": False,
                "rules_algorithm": False,
            },
            n_components=4,
            mne_icalabel_artifacts=[2],
        )

        self.assertEqual(excluded, [2])


if __name__ == "__main__":
    unittest.main()
