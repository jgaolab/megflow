import tempfile
import unittest
import sys
import types
from copy import deepcopy
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
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
    from meg_detect_artifacts import main as detect_artifacts_main
    import tools.deepreject.preprocessing as deepreject_preprocessing


DEFAULT_DEEPREJECT_PREPROC = [
    {
        "filter": {
            "l_freq": 1.0,
            "h_freq": 100.0,
            "method": "iir",
            "iir_params": {"order": 5, "ftype": "butter"},
        }
    },
    {"notch_filter": {"freqs": 50}},
    {"resample": {"sfreq": 250}},
]


class DeepRejectModelInputPreprocessingTests(unittest.TestCase):
    @staticmethod
    def _raw(sfreq=1000.0, duration=2.0, lowpass=None):
        rng = np.random.default_rng(2025)
        n_times = int(round(sfreq * duration))
        info = mne.create_info(
            ["MEG 001", "MEG 002", "EOG 001"],
            sfreq=sfreq,
            ch_types=["mag", "grad", "eog"],
        )
        raw = RawArray(rng.standard_normal((3, n_times)) * 1e-12, info, verbose=False)
        if lowpass is not None:
            raw.filter(
                l_freq=None,
                h_freq=float(lowpass),
                method="iir",
                iir_params={"order": 2, "ftype": "butter"},
                verbose=False,
            )
        return raw

    def _resolver(self):
        resolver = getattr(deepreject_preprocessing, "resolve_deepreject_preproc", None)
        self.assertIsNotNone(resolver, "DeepReject preprocessing resolver is required")
        return resolver

    def _applier(self):
        applier = getattr(deepreject_preprocessing, "apply_deepreject_preproc", None)
        self.assertIsNotNone(applier, "DeepReject model-input preprocessing applier is required")
        return applier

    def test_missing_null_and_empty_preproc_use_isolated_defaults(self):
        resolver = self._resolver()
        for value in (None, []):
            with self.subTest(value=value):
                resolved = resolver(value)
                self.assertEqual(resolved, DEFAULT_DEEPREJECT_PREPROC)
                self.assertIsNot(resolved, DEFAULT_DEEPREJECT_PREPROC)
                resolved[0]["filter"]["l_freq"] = 9.0
                self.assertEqual(resolver(None)[0]["filter"]["l_freq"], 1.0)

    def test_false_and_off_disable_internal_preprocessing(self):
        resolver = self._resolver()
        for value in (False, "false", "off"):
            with self.subTest(value=value):
                self.assertEqual(resolver(value), [])

    def test_nonempty_user_recipe_fully_replaces_default(self):
        custom = [{"resample": {"sfreq": 300}}]
        resolved = self._resolver()(custom)
        self.assertEqual(resolved, custom)
        self.assertIsNot(resolved, custom)
        self.assertNotIn("filter", resolved[0])

    def test_malformed_recipe_is_an_error(self):
        resolver = self._resolver()
        for value in (
            "filter",
            [{"filter": {}, "resample": {"sfreq": 250}}],
            [{"unknown": {}}],
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    resolver(value)

    def test_default_recipe_upsamples_200_hz_before_frequency_steps(self):
        raw = self._raw(sfreq=200.0, duration=4.0)
        before = raw.get_data().copy()

        with self.assertLogs(level="INFO") as captured:
            model_raw, provenance = self._applier()(raw, None)

        self.assertEqual(raw.info["sfreq"], 200.0)
        np.testing.assert_array_equal(raw.get_data(), before)
        self.assertEqual(model_raw.info["sfreq"], 250.0)
        self.assertEqual(provenance["recipe_source"], "default")
        self.assertEqual(provenance["resolved_recipe"], DEFAULT_DEEPREJECT_PREPROC)
        self.assertTrue(provenance["default_recipe_match"])
        self.assertEqual(
            [step["step"] for step in provenance["applied_steps"]],
            ["resample", "filter", "notch_filter"],
        )
        self.assertTrue(
            any(step["step"] == "notch_filter" for step in provenance["applied_steps"])
        )
        self.assertIn("source sampling rate is below 250 Hz", provenance["source_limitations"])
        self.assertIn(
            "DeepReject model input resampled from 200.0 Hz to 250.0 Hz "
            "(model-only; main FIF unchanged).",
            "\n".join(captured.output),
        )

    def test_narrow_source_bandwidth_continues_and_records_limitation(self):
        raw = self._raw(sfreq=500.0, duration=4.0, lowpass=30.0)

        model_raw, provenance = self._applier()(raw, None)

        self.assertEqual(model_raw.info["sfreq"], 250.0)
        self.assertIn("source low-pass is below 100 Hz", provenance["source_limitations"])
        self.assertEqual(provenance["source_before"]["lowpass_hz"], 30.0)
        self.assertEqual(provenance["model_input_after"]["sfreq_hz"], 250.0)

    def test_filter_skips_only_inadmissible_frequency_part_with_reason(self):
        raw = self._raw(sfreq=100.0, duration=4.0)
        recipe = [{"filter": {"l_freq": 1.0, "h_freq": 100.0, "method": "iir"}}]

        model_raw, provenance = self._applier()(raw, recipe)

        self.assertEqual(raw.info["highpass"], 0.0)
        self.assertEqual(model_raw.info["highpass"], 1.0)
        step = provenance["applied_steps"][0]
        self.assertEqual(step["status"], "applied")
        self.assertEqual(step["l_freq"], 1.0)
        self.assertIsNone(step["h_freq"])
        self.assertIn("h_freq=100 Hz", step.get("reason", ""))

    def test_notch_uses_mne_design_domain_to_resample_before_filtering(self):
        raw = self._raw(sfreq=101.0, duration=10.0)
        recipe = [
            {"notch_filter": {"freqs": 50}},
            {"resample": {"sfreq": 250}},
        ]

        try:
            model_raw, provenance = self._applier()(raw, recipe)
        except ValueError as exc:
            self.fail(f"future resample should make the MNE notch design valid: {exc}")

        self.assertEqual(model_raw.info["sfreq"], 250.0)
        self.assertEqual(
            [step["step"] for step in provenance["applied_steps"]],
            ["resample", "notch_filter"],
        )
        self.assertEqual(provenance["applied_steps"][1]["status"], "applied")

    def test_notch_without_admissible_future_resample_is_skipped(self):
        raw = self._raw(sfreq=101.0, duration=10.0)

        try:
            model_raw, provenance = self._applier()(
                raw,
                [{"notch_filter": {"freqs": 50}}],
            )
        except ValueError as exc:
            self.fail(f"inadmissible MNE notch design should be skipped: {exc}")

        self.assertEqual(model_raw.info["sfreq"], 101.0)
        step = provenance["applied_steps"][0]
        self.assertEqual(step["step"], "notch_filter")
        self.assertEqual(step["status"], "skipped")
        self.assertIn("MNE notch design", step.get("reason", ""))

    def test_notch_preserves_per_frequency_widths_when_partially_skipping(self):
        raw = self._raw(sfreq=101.0, duration=10.0)
        recipe = [
            {
                "notch_filter": {
                    "freqs": [10, 50],
                    "notch_widths": [0.1, 0.25],
                }
            }
        ]

        try:
            _, provenance = self._applier()(raw, recipe)
        except ValueError as exc:
            self.fail(f"valid per-frequency notch widths must remain aligned: {exc}")

        step = provenance["applied_steps"][0]
        self.assertEqual(step["status"], "applied")
        self.assertEqual(step["freqs"], [10.0])
        self.assertIn("50 Hz", step.get("reason", ""))

    def test_enabled_preprocessing_writes_model_only_fif_even_without_meg_pick(self):
        raw = self._raw(sfreq=200.0, duration=4.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "source_raw.fif"
            raw.save(source_path, overwrite=True, verbose=False)

            prediction_path, temporary_path, summary = (
                detect_artifacts_module._prepare_deepreject_input(
                    raw,
                    source_path,
                    tmpdir,
                    {"pick_meg_only": False},
                )
            )

            self.assertNotEqual(prediction_path, source_path)
            self.assertEqual(prediction_path, temporary_path)
            self.assertEqual(raw.info["sfreq"], 200.0)
            model_raw = mne.io.read_raw_fif(prediction_path, preload=False, verbose=False)
            self.assertEqual(model_raw.info["sfreq"], 250.0)
            self.assertEqual(model_raw.ch_names, raw.ch_names)
            self.assertEqual(summary["input_preprocessing"]["recipe_source"], "default")

    def test_legacy_scalar_fields_are_ignored_and_not_forwarded_to_predictor(self):
        raw = self._raw(sfreq=200.0, duration=4.0)
        prediction_call = {}

        class FakePredictor:
            def __init__(self, **kwargs):
                self.fold_workers = kwargs["fold_workers"]
                self.cpu_threads = kwargs["cpu_threads"]
                self.cpu_interop_threads = kwargs["cpu_interop_threads"]
                self.cache_models = True

            def predict_fif(self, path, **kwargs):
                prediction_call["kwargs"] = deepcopy(kwargs)
                prediction_call["sfreq"] = mne.io.read_raw_fif(
                    path, preload=False, verbose=False
                ).info["sfreq"]
                return SimpleNamespace(
                    backend="fake",
                    artifact_folds=np.array([], dtype=int),
                    bad_channel_folds=np.array([], dtype=int),
                    artifact_probs=np.array([]),
                    bad_intervals=[],
                    ch_names=[],
                    bad_channel_pred=np.array([], dtype=int),
                    bad_channel_probs=None,
                )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            detect_artifacts_module, "DeepRejectPredictor", FakePredictor
        ):
            source_path = Path(tmpdir) / "source_raw.fif"
            raw.save(source_path, overwrite=True, verbose=False)
            _, _, summary = detect_artifacts_module.run_deepreject_detection(
                raw,
                source_path,
                {
                    "runtime_cpus": 4,
                    "deepreject": {
                        "enabled": True,
                        "pick_meg_only": False,
                        "filter_l_freq": 9,
                        "filter_h_freq": 20,
                        "resample_sfreq": 50,
                    },
                },
                tmpdir,
            )

        self.assertEqual(prediction_call["sfreq"], 250.0)
        for legacy_field in ("filter_l_freq", "filter_h_freq", "resample_sfreq"):
            self.assertNotIn(legacy_field, prediction_call["kwargs"])
        self.assertEqual(summary["input_preprocessing"]["recipe_source"], "default")

    def test_temporary_model_input_is_removed_after_successful_prediction(self):
        raw = self._raw(sfreq=200.0, duration=4.0)

        class SuccessfulPredictor:
            def __init__(self, **kwargs):
                self.fold_workers = kwargs["fold_workers"]
                self.cpu_threads = kwargs["cpu_threads"]
                self.cpu_interop_threads = kwargs["cpu_interop_threads"]
                self.cache_models = True

            def predict_fif(self, path, **kwargs):
                return SimpleNamespace(
                    backend="fake",
                    artifact_folds=np.array([], dtype=int),
                    bad_channel_folds=np.array([], dtype=int),
                    artifact_probs=np.array([]),
                    bad_intervals=[],
                    ch_names=[],
                    bad_channel_pred=np.array([], dtype=int),
                    bad_channel_probs=None,
                )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            detect_artifacts_module, "DeepRejectPredictor", SuccessfulPredictor
        ):
            source_path = Path(tmpdir) / "source_raw.fif"
            raw.save(source_path, overwrite=True, verbose=False)
            detect_artifacts_module.run_deepreject_detection(
                raw,
                source_path,
                {
                    "runtime_cpus": 4,
                    "deepreject": {"enabled": True, "pick_meg_only": False},
                },
                tmpdir,
            )
            self.assertEqual(
                list(Path(tmpdir).glob("*_deepreject_model_input_raw.fif")),
                [],
            )

    def test_temporary_model_input_is_removed_when_prediction_fails(self):
        raw = self._raw(sfreq=200.0, duration=4.0)
        prediction_state = {}

        class FailingPredictor:
            def __init__(self, **kwargs):
                pass

            def predict_fif(self, path, **kwargs):
                prediction_state["created"] = Path(path).is_file()
                raise RuntimeError("synthetic prediction failure")

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            detect_artifacts_module, "DeepRejectPredictor", FailingPredictor
        ):
            source_path = Path(tmpdir) / "source_raw.fif"
            raw.save(source_path, overwrite=True, verbose=False)
            with self.assertRaisesRegex(RuntimeError, "synthetic prediction failure"):
                detect_artifacts_module.run_deepreject_detection(
                    raw,
                    source_path,
                    {
                        "runtime_cpus": 4,
                        "deepreject": {"enabled": True, "pick_meg_only": False},
                    },
                    tmpdir,
                )
            self.assertTrue(prediction_state["created"])
            self.assertEqual(
                list(Path(tmpdir).glob("*_deepreject_model_input_raw.fif")),
                [],
            )

    def test_partial_model_input_is_removed_when_save_fails(self):
        raw = self._raw(sfreq=250.0, duration=4.0)

        def partial_save_then_fail(instance, path, **kwargs):
            Path(path).write_bytes(b"partial-fif")
            raise RuntimeError("synthetic save failure")

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            mne.io.BaseRaw,
            "save",
            partial_save_then_fail,
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic save failure"):
                detect_artifacts_module._prepare_deepreject_input(
                    raw,
                    Path(tmpdir) / "source_raw.fif",
                    tmpdir,
                    {"pick_meg_only": False},
                )
            self.assertEqual(
                list(Path(tmpdir).rglob("*deepreject_model_input*")),
                [],
            )

    @staticmethod
    def _simulated_split_save(instance, path, **kwargs):
        path = Path(path)
        path.write_bytes(b"base-fif")
        path.with_name(f"{path.stem}-1{path.suffix}").write_bytes(b"split-1")
        path.with_name(f"{path.stem}-2{path.suffix}").write_bytes(b"split-2")

    @staticmethod
    def _empty_prediction():
        return SimpleNamespace(
            backend="fake",
            artifact_folds=np.array([], dtype=int),
            bad_channel_folds=np.array([], dtype=int),
            artifact_probs=np.array([]),
            bad_intervals=[],
            ch_names=[],
            bad_channel_pred=np.array([], dtype=int),
            bad_channel_probs=None,
        )

    def _run_with_simulated_split(self, tmpdir, *, fail_prediction=False, keep=False):
        raw = self._raw(sfreq=250.0, duration=4.0)

        prediction = self._empty_prediction()

        class SplitPredictor:
            def __init__(self, **kwargs):
                self.fold_workers = kwargs["fold_workers"]
                self.cpu_threads = kwargs["cpu_threads"]
                self.cpu_interop_threads = kwargs["cpu_interop_threads"]
                self.cache_models = True

            def predict_fif(self, path, **kwargs):
                if fail_prediction:
                    raise RuntimeError("synthetic split prediction failure")
                return prediction

        source_path = Path(tmpdir) / "source_raw.fif"
        with mock.patch.object(
            detect_artifacts_module,
            "DeepRejectPredictor",
            SplitPredictor,
        ), mock.patch.object(
            mne.io.BaseRaw,
            "save",
            self._simulated_split_save,
        ):
            config = {
                "runtime_cpus": 4,
                "deepreject": {
                    "enabled": True,
                    "pick_meg_only": False,
                    "keep_meg_only_input": keep,
                },
            }
            if fail_prediction:
                with self.assertRaisesRegex(
                    RuntimeError,
                    "synthetic split prediction failure",
                ):
                    detect_artifacts_module.run_deepreject_detection(
                        raw,
                        source_path,
                        config,
                        tmpdir,
                    )
            else:
                detect_artifacts_module.run_deepreject_detection(
                    raw,
                    source_path,
                    config,
                    tmpdir,
                )
        return sorted(Path(tmpdir).rglob("*deepreject_model_input*"))

    def test_all_split_model_input_files_are_removed_after_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(self._run_with_simulated_split(tmpdir), [])

    def test_all_split_model_input_files_are_removed_after_prediction_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(
                self._run_with_simulated_split(tmpdir, fail_prediction=True),
                [],
            )

    def test_explicit_keep_preserves_all_split_model_input_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            retained = self._run_with_simulated_split(tmpdir, keep=True)
            self.assertEqual(len(retained), 3)


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
