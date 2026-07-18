import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np


MEGFLOW_DIR = Path(__file__).resolve().parents[1] / "megflow"
if str(MEGFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(MEGFLOW_DIR))

import run_ica_label
from tools.ica_classify import ICs_classification


class CategoryIndexFilteringTests(unittest.TestCase):
    def test_filter_category_indices_clears_disabled_categories(self):
        self.assertEqual(
            run_ica_label.filter_category_indices(
                {"ecg": [1], "eog": [2], "outlier": [3]},
                {"ecg": False, "eog": True, "outlier": False},
                n_components=4,
            ),
            {"ecg": [], "eog": [2], "outlier": []},
        )


class IcaLabelMainCategoryGateTests(unittest.TestCase):
    def test_all_disabled_categories_produce_no_detector_or_output_results(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            recording_name = "sub-01_task-rest_meg"
            raw_path = temp_path / "input" / recording_name / "raw.fif"
            output_dir = temp_path / "ica_report"
            ica_file = temp_path / "ica" / "fit-ica.fif"
            args = SimpleNamespace(
                raw_data_path=str(raw_path),
                ica_file=str(ica_file),
                ica_sources_file=None,
                output_dir=str(output_dir),
                overwrite_existing=True,
                refresh_existing=False,
                config="{}",
            )
            config = {
                "ic_ecg": False,
                "ic_eog": False,
                "ic_outlier": False,
                "mne_icalabel": True,
                "megnet_retrained": True,
                "mne_algorithm": True,
                "rules_algorithm": True,
                "find_bads_eog": {"ch_name": None},
                "find_bads_ecg": {"ch_name": None},
                "find_bads_muscle": {},
                "ICA_classify": {},
            }
            raw = SimpleNamespace(filenames=[str(raw_path)])
            ica = SimpleNamespace(
                n_components_=4,
                find_bads_ecg=mock.Mock(return_value=([], np.zeros(4))),
                find_bads_eog=mock.Mock(return_value=([], np.zeros(4))),
                find_bads_muscle=mock.Mock(return_value=([], np.zeros(4))),
            )

            with (
                mock.patch.object(run_ica_label, "parse_arguments", return_value=args),
                mock.patch.object(run_ica_label.yaml, "safe_load", return_value=config),
                mock.patch.object(run_ica_label.mne.io, "read_raw", return_value=raw),
                mock.patch.object(
                    run_ica_label.mne.preprocessing,
                    "read_ica",
                    return_value=ica,
                ),
                mock.patch.object(
                    run_ica_label,
                    "classify_ics",
                    return_value=([], {}),
                ) as classify_mock,
                mock.patch.object(
                    run_ica_label,
                    "run_mne_megnet_detector",
                    side_effect=AssertionError("MEGNet must not run"),
                ) as megnet_mock,
                mock.patch.object(
                    run_ica_label,
                    "run_retrained_detector",
                    side_effect=AssertionError("retrained MEGNet must not run"),
                ) as retrained_mock,
            ):
                run_ica_label.main()

            ica.find_bads_ecg.assert_not_called()
            ica.find_bads_eog.assert_not_called()
            ica.find_bads_muscle.assert_not_called()
            classify_mock.assert_not_called()
            megnet_mock.assert_not_called()
            retrained_mock.assert_not_called()

            result_dir = output_dir / recording_name
            self.assertEqual(
                (result_dir / "marked_components.txt").read_text(encoding="utf-8"),
                "",
            )
            payload = json.loads(
                (result_dir / "ecg_eog_scores.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["ecg_indices"], [])
            self.assertEqual(payload["eog_indices"], [])
            self.assertEqual(payload["outlier_indices"], [])
            self.assertEqual(
                payload["category_switches"],
                {"ecg": False, "eog": False, "outlier": False},
            )
            self.assertEqual(payload["marked_components"]["auto_indices"], [])
            self.assertEqual(payload["marked_components"]["written_indices"], [])

    def test_enabled_mne_eog_uses_automatic_channel_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            recording_name = "sub-01_task-rest_meg"
            raw_path = temp_path / "input" / recording_name / "raw.fif"
            output_dir = temp_path / "ica_report"
            args = SimpleNamespace(
                raw_data_path=str(raw_path),
                ica_file=str(temp_path / "ica" / "fit-ica.fif"),
                ica_sources_file=None,
                output_dir=str(output_dir),
                overwrite_existing=True,
                refresh_existing=False,
                config="{}",
            )
            config = {
                "ic_ecg": False,
                "ic_eog": True,
                "ic_outlier": False,
                "mne_icalabel": False,
                "megnet_retrained": False,
                "mne_algorithm": True,
                "rules_algorithm": False,
                "find_bads_eog": {"ch_name": None},
            }
            raw = SimpleNamespace(filenames=[str(raw_path)])
            eog_scores = np.asarray([0.1, 0.2, 0.9, 0.3])
            ica = SimpleNamespace(
                n_components_=4,
                find_bads_ecg=mock.Mock(),
                find_bads_eog=mock.Mock(return_value=([2], eog_scores)),
                find_bads_muscle=mock.Mock(),
            )

            with (
                mock.patch.object(run_ica_label, "parse_arguments", return_value=args),
                mock.patch.object(run_ica_label.yaml, "safe_load", return_value=config),
                mock.patch.object(run_ica_label.mne.io, "read_raw", return_value=raw),
                mock.patch.object(
                    run_ica_label.mne.preprocessing,
                    "read_ica",
                    return_value=ica,
                ),
            ):
                run_ica_label.main()

            ica.find_bads_eog.assert_called_once_with(raw, ch_name=None)
            ica.find_bads_ecg.assert_not_called()
            ica.find_bads_muscle.assert_not_called()

            result_dir = output_dir / recording_name
            self.assertEqual(
                (result_dir / "marked_components.txt").read_text(encoding="utf-8"),
                "2\n",
            )
            payload = json.loads(
                (result_dir / "ecg_eog_scores.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["ecg_indices"], [])
            self.assertEqual(payload["eog_indices"], [2])
            self.assertEqual(payload["eog"], [0.9])
            self.assertEqual(
                payload["category_switches"],
                {"ecg": False, "eog": True, "outlier": False},
            )
            self.assertEqual(payload["marked_components"]["auto_indices"], [2])


class RuleClassifierCategoryGateTests(unittest.TestCase):
    def test_all_disabled_rule_categories_skip_detection_branches(self):
        raw = mock.sentinel.raw
        config = {
            "collect_ecg_rules": False,
            "collect_eog_rules": False,
            "collect_outlier_rules": False,
        }

        with (
            mock.patch.object(
                ICs_classification.mne.io,
                "read_raw_fif",
                return_value=raw,
            ),
            mock.patch.object(
                ICs_classification,
                "find_ecg_ics",
                side_effect=AssertionError("ECG rules must not run"),
            ) as ecg_mock,
            mock.patch.object(
                ICs_classification,
                "find_abnormal_psd_ics",
                side_effect=AssertionError("PSD rules must not run"),
            ) as psd_mock,
            mock.patch.object(
                ICs_classification,
                "ics_topomap_distribution",
                side_effect=AssertionError("EOG rules must not run"),
            ) as eog_mock,
        ):
            _, categories = ICs_classification.classify_ics(
                "sources.fif",
                "fit-ica.fif",
                config=config,
            )

        ecg_mock.assert_not_called()
        psd_mock.assert_not_called()
        eog_mock.assert_not_called()
        self.assertEqual(dict(categories), {})


if __name__ == "__main__":
    unittest.main()
