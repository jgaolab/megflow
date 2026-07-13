import tempfile
import unittest
import sys
import types
from argparse import Namespace
from pathlib import Path

import mne
import numpy as np

MEGFLOW_DIR = Path(__file__).resolve().parents[1] / "megflow"
if str(MEGFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(MEGFLOW_DIR))

osl_wrappers = types.ModuleType("osl_ephys.preprocessing.osl_wrappers")
osl_wrappers.detect_badchannels = lambda *args, **kwargs: None
osl_wrappers.detect_badsegments = lambda *args, **kwargs: None
osl_preprocessing = types.ModuleType("osl_ephys.preprocessing")
osl_preprocessing.osl_wrappers = osl_wrappers
osl_ephys = types.ModuleType("osl_ephys")
osl_ephys.preprocessing = osl_preprocessing
sys.modules.setdefault("osl_ephys", osl_ephys)
sys.modules.setdefault("osl_ephys.preprocessing", osl_preprocessing)
sys.modules.setdefault("osl_ephys.preprocessing.osl_wrappers", osl_wrappers)

from meg_detect_artifacts import _deepreject_input_preprocessing_summary, main as detect_artifacts_main


class _RawInfoOnly:
    def __init__(self, highpass, lowpass, sfreq):
        self.info = {
            "highpass": highpass,
            "lowpass": lowpass,
            "sfreq": sfreq,
        }


class DeepRejectInputWarningTests(unittest.TestCase):
    def test_recommended_input_matches_without_warning(self):
        raw = _RawInfoOnly(1.0, 100.0, 250.0)
        with self.assertNoLogs("meg_detect_artifacts", level="WARNING"):
            summary = _deepreject_input_preprocessing_summary(raw, {})
        self.assertTrue(summary["recommended_input_match"])
        self.assertEqual(summary["irreversible_mismatches"], [])

    def test_narrow_lowpass_warns_as_irreversible(self):
        raw = _RawInfoOnly(0.5, 30.0, 250.0)
        with self.assertLogs("meg_detect_artifacts", level="WARNING") as captured:
            summary = _deepreject_input_preprocessing_summary(raw, {})
        self.assertFalse(summary["recommended_input_match"])
        self.assertIn("input low-pass is below 100 Hz", summary["irreversible_mismatches"])
        self.assertIn("lowpass=30 Hz", " ".join(captured.output))

    def test_internal_filter_can_narrow_broad_input(self):
        raw = _RawInfoOnly(0.1, 125.0, 1000.0)
        config = {
            "filter_l_freq": 1.0,
            "filter_h_freq": 100.0,
            "resample_sfreq": 250.0,
        }
        with self.assertNoLogs("meg_detect_artifacts", level="WARNING"):
            summary = _deepreject_input_preprocessing_summary(raw, config)
        self.assertTrue(summary["recommended_input_match"])
        self.assertEqual(
            summary["effective"],
            {"highpass_hz": 1.0, "lowpass_hz": 100.0, "sfreq_hz": 250.0},
        )


class ArtifactMaskGenerationTests(unittest.TestCase):
    def test_mask_is_generated_when_detailed_artifact_images_are_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            output_dir = tmpdir / "artifact_report"
            output_dir.mkdir()
            raw_file = tmpdir / "synthetic_raw.fif"
            info = mne.create_info(["MEG 001", "MEG 002"], 100.0, ch_types=["mag", "mag"])
            raw = mne.io.RawArray(np.zeros((2, 1000)), info, verbose=False)
            raw.save(raw_file, overwrite=True, verbose=False)

            (output_dir / "synthetic_raw_bad_channels.txt").write_text("MEG 002\n")
            annotations = mne.Annotations(
                onset=[2.0],
                duration=[1.0],
                description=["BAD_test"],
            )
            annotations.save(output_dir / "synthetic_raw_bad_segments.txt", overwrite=True)

            detect_artifacts_main(
                Namespace(
                    input=str(raw_file),
                    output=str(output_dir),
                    config="artifact_images_enabled: false",
                )
            )

            mask_file = output_dir / "check_imgs" / "artifact_mask_heatmap.jpg"
            self.assertTrue(mask_file.is_file())
            self.assertGreater(mask_file.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
