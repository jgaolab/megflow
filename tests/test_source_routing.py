import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MEGFLOW_DIR = Path(__file__).resolve().parents[1] / "megflow"
if str(MEGFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(MEGFLOW_DIR))

import source_localization


class SourceInputRoutingTests(unittest.TestCase):
    def test_explicit_files_override_legacy_directory_lookup(self):
        covariance, forward = source_localization.resolve_source_input_files(
            "/epochs/dataset-a/sub-01_task-a/sub-01_task-a-epo.fif",
            "task_a",
            "ico4",
            noise_covariance_file="/routed/covariance-a.fif",
            forward_file="/routed/forward-a.fif",
            noise_covariance_dir="/wrong/covariance",
            forward_dir="/wrong/forward",
        )

        self.assertEqual(covariance, Path("/routed/covariance-a.fif"))
        self.assertEqual(forward, Path("/routed/forward-a.fif"))

    def test_legacy_directory_lookup_remains_available(self):
        covariance, forward = source_localization.resolve_source_input_files(
            "/epochs/dataset-a/sub-01_task-b/sub-01_task-b-epo.fif",
            "task_b",
            "oct6",
            noise_covariance_dir="/legacy/covariance",
            forward_dir="/legacy/forward",
        )

        self.assertEqual(
            covariance,
            Path("/legacy/covariance/sub-01_task-b/bl-cov.fif"),
        )
        self.assertEqual(
            forward,
            Path("/legacy/forward/sub-01_task-b/task_b_oct6-fwd.fif"),
        )

    def test_missing_routed_and_legacy_inputs_fail_early(self):
        with self.assertRaisesRegex(ValueError, "noise_covariance"):
            source_localization.resolve_source_input_files(
                "/epochs/sub-01/sub-01-epo.fif",
                "task",
                "ico4",
            )

    def test_none_mode_requires_no_noise_covariance_file(self):
        covariance, forward = source_localization.resolve_source_input_files(
            "/raw/sub-01/sub-01_raw.fif",
            "continuous",
            "ico4",
            noise_covariance_mode="none",
            forward_file="/routed/forward-a.fif",
        )

        self.assertIsNone(covariance)
        self.assertEqual(forward, Path("/routed/forward-a.fif"))

    def test_none_mode_rejects_an_accidental_noise_covariance_file(self):
        with self.assertRaisesRegex(ValueError, "must not be provided"):
            source_localization.resolve_source_input_files(
                "/raw/sub-01/sub-01_raw.fif",
                "continuous",
                "ico4",
                noise_covariance_mode="none",
                noise_covariance_file="/wrong/bl-cov.fif",
                forward_file="/routed/forward-a.fif",
            )

    def test_source_failure_is_not_swallowed(self):
        config = {
            "spacing": "ico4",
            "epoch_label": "auditory",
            "source_methods": ["dSPM"],
            "data_type": "meg",
        }
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            source_localization.mne,
            "read_epochs",
            return_value=mock.sentinel.epochs,
        ), mock.patch.object(
            source_localization,
            "_pick_source_data",
            return_value=mock.sentinel.selected_epochs,
        ), mock.patch.object(
            source_localization.mne,
            "read_cov",
            side_effect=RuntimeError("bad covariance"),
        ) as read_cov:
            with self.assertRaisesRegex(RuntimeError, "bad covariance"):
                source_localization.process_subject(
                    "/epochs/sub-01_task-a/sub-01_task-a-epo.fif",
                    "/subjects",
                    None,
                    None,
                    tmpdir,
                    config,
                    False,
                    noise_covariance_file="/routed/a-cov.fif",
                    forward_file="/routed/a-fwd.fif",
                )

        read_cov.assert_called_once_with(Path("/routed/a-cov.fif"))


if __name__ == "__main__":
    unittest.main()
