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

    def test_score_payload_derives_automatic_union_from_categories(self):
        payload = run_ica_label.finalize_score_payload(
            {
                "ecg_indices": [3],
                "ecg": [0.9],
                "eog_indices": [],
                "eog": [],
                "methods": {},
            },
            category_indices={"ecg": [3], "eog": [], "outlier": [7]},
            written_indices=[3, 7],
            marked_output_mode="auto",
            n_components=10,
        )

        self.assertEqual(payload["ecg_indices"], [3])
        self.assertEqual(payload["eog_indices"], [])
        self.assertEqual(payload["outlier_indices"], [7])
        self.assertEqual(payload["marked_components"]["auto_indices"], [3, 7])
        self.assertEqual(
            payload["marked_components"]["written_indices"],
            [3, 7],
        )

    def test_score_payload_records_preserved_manual_text_contents(self):
        payload = run_ica_label.finalize_score_payload(
            {
                "ecg_indices": [3],
                "ecg": [0.9],
                "eog_indices": [],
                "eog": [],
            },
            category_indices={"ecg": [3], "eog": [], "outlier": []},
            written_indices=[3, 9],
            marked_output_mode="preserved_manual",
            n_components=10,
        )

        self.assertEqual(payload["marked_components"]["auto_indices"], [3])
        self.assertEqual(
            payload["marked_components"]["written_indices"],
            [3, 9],
        )
        self.assertNotIn(9, payload["ecg_indices"])
        self.assertNotIn(9, payload["eog_indices"])
        self.assertNotIn(9, payload["outlier_indices"])


class CategoryMasterSwitchTests(unittest.TestCase):
    def test_category_switches_use_repository_defaults(self):
        self.assertEqual(
            run_ica_label.resolve_category_switches({}),
            {"ecg": True, "eog": True, "outlier": False},
        )

    def test_category_switch_rejects_non_boolean_value(self):
        with self.assertRaisesRegex(TypeError, "ic_eog must be a boolean"):
            run_ica_label.resolve_category_switches({"ic_eog": "false"})

    def test_category_switches_gate_all_eight_combinations(self):
        category_indices = {
            "ic_ecg": [1],
            "ic_eog": [2],
            "ic_outlier": [3],
        }

        for mask in range(8):
            with self.subTest(mask=mask):
                config = {
                    "ic_ecg": bool(mask & 1),
                    "ic_eog": bool(mask & 2),
                    "ic_outlier": bool(mask & 4),
                }
                expected = [
                    index
                    for bit, index in ((1, 1), (2, 2), (4, 3))
                    if mask & bit
                ]

                self.assertEqual(
                    run_ica_label.collect_exclude_indices(
                        config,
                        n_components=4,
                        **category_indices,
                    ),
                    expected,
                )

    def test_method_artifact_union_cannot_bypass_disabled_categories(self):
        with self.assertRaises(TypeError):
            run_ica_label.collect_exclude_indices(
                {
                    "ic_ecg": False,
                    "ic_eog": False,
                    "ic_outlier": False,
                    "mne_icalabel": True,
                },
                n_components=4,
                mne_icalabel_artifacts=[0],
                ic_ecg=[0],
                ic_eog=[1],
                ic_outlier=[2, 3],
            )


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

    def test_detector_outcome_is_filtered_to_enabled_categories(self):
        probabilities = np.asarray(
            [
                [0.1, 0.8, 0.05, 0.05],
                [0.1, 0.2, 0.6, 0.1],
            ],
            dtype=np.float32,
        )
        outcome = run_ica_label.detector_outcome_from_probabilities(
            "mne_icalabel",
            probabilities,
        )

        filtered = run_ica_label.filter_detector_outcome(
            outcome,
            {"ecg": True, "eog": False, "outlier": False},
        )

        self.assertEqual(filtered.artifact_indices, [0])
        self.assertEqual(filtered.ecg_indices, [0])
        self.assertEqual(filtered.eog_indices, [])
        self.assertNotIn("labels", filtered.detail)
        self.assertNotIn("probabilities", filtered.detail)
        self.assertEqual(
            filtered.detail["detections"],
            {
                "ecg": [
                    {
                        "index": 0,
                        "label": "heart_beat",
                        "score": float(probabilities[0, 1]),
                    }
                ]
            },
        )

    def test_disabled_winning_class_is_not_reclassified(self):
        probabilities = np.asarray(
            [[0.05, 0.4, 0.5, 0.05]],
            dtype=np.float32,
        )
        outcome = run_ica_label.detector_outcome_from_probabilities(
            "mne_icalabel",
            probabilities,
        )

        filtered = run_ica_label.filter_detector_outcome(
            outcome,
            {"ecg": True, "eog": False, "outlier": False},
        )

        self.assertEqual(filtered.artifact_indices, [])
        self.assertEqual(filtered.ecg_indices, [])
        self.assertEqual(filtered.detail["detections"], {})

    def test_all_enabled_megnet_categories_keep_full_model_detail(self):
        probabilities = np.asarray(
            [[0.1, 0.8, 0.05, 0.05]],
            dtype=np.float32,
        )
        outcome = run_ica_label.detector_outcome_from_probabilities(
            "mne_icalabel",
            probabilities,
        )

        filtered = run_ica_label.filter_detector_outcome(
            outcome,
            {"ecg": True, "eog": True, "outlier": False},
        )

        self.assertEqual(filtered.detail["labels"], ["heart_beat"])
        np.testing.assert_allclose(
            filtered.detail["probabilities"],
            probabilities,
        )


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

    def test_megnet_is_skipped_when_ecg_and_eog_are_disabled(self):
        mne_predictor = mock.Mock(side_effect=AssertionError("must not run"))
        retrained_predictor = mock.Mock(side_effect=AssertionError("must not run"))

        outcomes = run_ica_label.run_configured_megnet_detectors(
            {
                "mne_icalabel": True,
                "megnet_retrained": True,
                "ic_ecg": False,
                "ic_eog": False,
            },
            mock.sentinel.raw,
            mock.sentinel.ica,
            mne_predictor=mne_predictor,
            retrained_predictor=retrained_predictor,
        )

        self.assertEqual(outcomes, {})
        mne_predictor.assert_not_called()
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
            },
            n_components=4,
            ic_eog=[2],
        )

        self.assertEqual(excluded, [2])


if __name__ == "__main__":
    unittest.main()
