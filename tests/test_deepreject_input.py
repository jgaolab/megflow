import tempfile
import unittest
import sys
import types
from argparse import Namespace
from pathlib import Path
from unittest import mock

import mne
import numpy as np
from mne.io import RawArray

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
pyprep_find_noisy = types.ModuleType("tools.pyprep.find_noisy_channels")
pyprep_find_noisy.NoisyChannels = object
pyprep = types.ModuleType("tools.pyprep")
pyprep.find_noisy_channels = pyprep_find_noisy
with mock.patch.dict(
    sys.modules,
    {
        "osl_ephys": osl_ephys,
        "osl_ephys.preprocessing": osl_preprocessing,
        "osl_ephys.preprocessing.osl_wrappers": osl_wrappers,
        "tools.pyprep": pyprep,
        "tools.pyprep.find_noisy_channels": pyprep_find_noisy,
    },
):
    import meg_detect_artifacts as detect_artifacts_module
    from meg_detect_artifacts import (
        _deepreject_input_preprocessing_summary,
        main as detect_artifacts_main,
    )


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


class DeepRejectRuntimeParallelismTests(unittest.TestCase):
    def _resolve_parallelism(self, runtime_cpus, fold_workers="auto", cpu_threads="auto", folds=None):
        resolver = getattr(detect_artifacts_module, "_resolve_deepreject_parallelism", None)
        self.assertIsNotNone(resolver, "DeepReject runtime parallelism resolver is required")
        return resolver(
            runtime_cpus=runtime_cpus,
            fold_workers=fold_workers,
            cpu_threads=cpu_threads,
            folds=folds,
        )

    def _resolve_image_jobs(self, requested, runtime_cpus):
        resolver = getattr(detect_artifacts_module, "_resolve_artifact_image_n_jobs", None)
        self.assertIsNotNone(resolver, "Artifact image worker resolver is required")
        return resolver(requested=requested, runtime_cpus=runtime_cpus)

    def test_auto_parallelism_uses_representative_cpu_budgets(self):
        expected = {
            4: (1, 4),
            8: (2, 4),
            16: (4, 4),
            20: (5, 4),
            24: (4, 6),
        }
        for runtime_cpus, pair in expected.items():
            with self.subTest(runtime_cpus=runtime_cpus):
                self.assertEqual(self._resolve_parallelism(runtime_cpus), pair)

    def test_explicit_preferences_are_preserved_or_scaled_under_budget(self):
        cases = (
            (16, 2, 3, (2, 3)),
            (8, 5, 4, (2, 4)),
            (4, 5, 4, (1, 4)),
            (8, "auto", 4, (2, 4)),
            (8, 2, "auto", (2, 4)),
        )
        for runtime_cpus, workers, threads, expected in cases:
            with self.subTest(
                runtime_cpus=runtime_cpus,
                fold_workers=workers,
                cpu_threads=threads,
            ):
                resolved = self._resolve_parallelism(
                    runtime_cpus,
                    fold_workers=workers,
                    cpu_threads=threads,
                )
                self.assertEqual(resolved, expected)
                self.assertLessEqual(resolved[0] * resolved[1], runtime_cpus)

    def test_fold_workers_never_exceed_selected_folds(self):
        workers, threads = self._resolve_parallelism(
            16,
            fold_workers="auto",
            cpu_threads="auto",
            folds=[0, 1, 2],
        )
        self.assertEqual((workers, threads), (2, 8))
        self.assertLessEqual(workers, 3)
        self.assertLessEqual(workers * threads, 16)

    def test_artifact_image_workers_are_capped_by_runtime_cpus(self):
        cases = (
            ("auto", 4, 4),
            (8, 4, 4),
            (2, 4, 2),
            (None, 3, 3),
        )
        for requested, runtime_cpus, expected in cases:
            with self.subTest(requested=requested, runtime_cpus=runtime_cpus):
                self.assertEqual(
                    self._resolve_image_jobs(requested, runtime_cpus),
                    expected,
                )


class ArtifactMaskGenerationTests(unittest.TestCase):
    def test_mask_is_generated_when_detailed_artifact_images_are_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            output_dir = tmpdir / "artifact_report"
            output_dir.mkdir()
            raw_file = tmpdir / "synthetic_raw.fif"
            info = mne.create_info(["MEG 001", "MEG 002"], 100.0, ch_types=["mag", "mag"])
            raw = RawArray(np.zeros((2, 1000)), info, verbose=False)
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
