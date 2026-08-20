import inspect
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import mne
import numpy as np


MEGFLOW_DIR = Path(__file__).resolve().parents[1] / "megflow"
if str(MEGFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(MEGFLOW_DIR))

autoreject = types.ModuleType("autoreject")
autoreject.AutoReject = object
autoreject.get_rejection_threshold = lambda epochs: {}
sys.modules.setdefault("autoreject", autoreject)

import compute_covariance
import epochs as epochs_module
import meg_preproc_osl
import run_ica as run_ica_module
import source_localization


mne.set_log_level("ERROR")


def _synthetic_raw(sfreq=200.0, duration=6.0, seed=17):
    rng = np.random.default_rng(seed)
    n_times = int(round(sfreq * duration))
    times = np.arange(n_times) / sfreq
    data = np.zeros((3, n_times), dtype=float)
    data[0] = 2e-12 * np.sin(2 * np.pi * 10.0 * times)
    data[0] += rng.standard_normal(n_times) * 1e-13
    data[1] = 1.5e-12 * np.sin(2 * np.pi * 18.0 * times)
    data[1] += rng.standard_normal(n_times) * 1e-13
    for second, value in ((1, 1), (2, 2), (3, 1), (4, 2)):
        sample = int(second * sfreq)
        data[2, sample : sample + 3] = value
    info = mne.create_info(
        ["MEG001", "MEG002", "STI 014"],
        sfreq,
        ch_types=["mag", "mag", "stim"],
    )
    return mne.io.RawArray(data, info, verbose=False)


class OslPreprocessingConfigContractTests(unittest.TestCase):
    def test_megflow_only_digitization_is_removed_without_narrowing_osl_recipe(self):
        recipe = {
            "meta": {"event_codes": {"stimulus": 1}, "versions": None},
            "preproc": [
                {
                    "filter": {
                        "l_freq": 2.0,
                        "h_freq": 40.0,
                        "method": "iir",
                        "iir_params": {"order": 3, "ftype": "butter"},
                        "phase": "zero",
                    }
                },
                {"pick": {"picks": "meg"}},
            ],
            "group": [{"group_average": {"metric": "median"}}],
            "version_warn": {"mne": "1.8.0"},
            "digitization": {"enabled": False},
        }

        osl_recipe = meg_preproc_osl._osl_preprocessing_config(recipe)

        self.assertNotIn("digitization", osl_recipe)
        self.assertEqual(osl_recipe["meta"], recipe["meta"])
        self.assertEqual(osl_recipe["preproc"], recipe["preproc"])
        self.assertEqual(osl_recipe["group"], recipe["group"])
        self.assertEqual(osl_recipe["version_warn"], recipe["version_warn"])
        self.assertIn("digitization", recipe)

    def test_run_meg_preprocessing_passes_the_complete_recipe_to_osl(self):
        recipe = {
            "meta": {"event_codes": None, "versions": None},
            "preproc": [{"filter": {"l_freq": 1.5, "h_freq": 45.0}}],
            "group": None,
            "version_warn": {"mne": "1.8.0"},
            "digitization": {"enabled": False},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_path = Path(temp_dir) / "synthetic_raw.fif"
            raw_path.touch()
            with mock.patch.object(
                meg_preproc_osl.preprocessing, "run_proc_batch"
            ) as run_proc_batch, mock.patch.object(
                meg_preproc_osl, "restore_embedded_headshape_if_missing"
            ):
                meg_preproc_osl.run_meg_preprocessing(
                    raw_path, temp_dir, recipe, random_seed=2025
                )

        passed = run_proc_batch.call_args.kwargs["config"]
        self.assertEqual(passed["meta"], recipe["meta"])
        self.assertEqual(passed["preproc"], recipe["preproc"])
        self.assertEqual(passed["group"], recipe["group"])
        self.assertEqual(passed["version_warn"], recipe["version_warn"])
        self.assertNotIn("digitization", passed)

    def test_osl_filter_and_resample_recipe_runs_on_real_mne_raw(self):
        recipe = {
            "meta": {"event_codes": None, "versions": None},
            "preproc": [
                {
                    "filter": {
                        "l_freq": 2.0,
                        "h_freq": 40.0,
                        "method": "iir",
                        "iir_params": {"order": 3, "ftype": "butter"},
                        "phase": "zero",
                        "pad": "reflect_limited",
                    }
                },
                {"resample": {"sfreq": 100.0, "npad": "auto", "window": "boxcar"}},
            ],
            "group": None,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_path = Path(temp_dir) / "synthetic_raw.fif"
            _synthetic_raw().save(raw_path, overwrite=True, verbose=False)
            dataset = meg_preproc_osl.preprocessing.run_proc_chain(
                recipe,
                str(raw_path),
                ret_dataset=True,
                gen_report=False,
                random_seed=2025,
                verbose="ERROR",
                mneverbose="ERROR",
            )

        self.assertTrue(dataset)
        self.assertAlmostEqual(dataset["raw"].info["highpass"], 2.0)
        self.assertAlmostEqual(dataset["raw"].info["lowpass"], 40.0)
        self.assertAlmostEqual(dataset["raw"].info["sfreq"], 100.0)

    def test_osl_notch_wrapper_accepts_mne_style_frequency_lists(self):
        for freqs in ([50.0], np.asarray([50.0]), "50", 50.0):
            with self.subTest(freqs=freqs):
                dataset = {"raw": _synthetic_raw()}
                meg_preproc_osl.preprocessing.mne_wrappers.run_mne_notch_filter(
                    dataset,
                    {
                        "freqs": freqs,
                        "method": "iir",
                        "iir_params": {"order": 2, "ftype": "butter"},
                    },
                )
                self.assertEqual(dataset["raw"].n_times, _synthetic_raw().n_times)


class EpochConfigContractTests(unittest.TestCase):
    def test_all_nested_epoch_kwargs_reach_mne_epochs_unchanged(self):
        epoch_kwargs = {
            "event_id": 7,
            "tmin": -0.15,
            "tmax": 0.45,
            "baseline": [None, 0.0],
            "picks": "meg",
            "preload": True,
            "reject": {"mag": 6e-12},
            "flat": {"mag": 1e-15},
            "proj": False,
            "decim": 2,
            "reject_tmin": -0.1,
            "reject_tmax": 0.3,
            "detrend": 1,
            "on_missing": "ignore",
            "reject_by_annotation": False,
            "event_repeated": "merge",
            "verbose": "ERROR",
        }
        config = {"epochs": epoch_kwargs}
        raw = mock.sentinel.raw
        events = np.array([[100, 0, 7]], dtype=int)
        result = mock.Mock()

        with mock.patch.object(
            epochs_module.mne.io, "read_raw_fif", return_value=raw
        ), mock.patch.object(
            epochs_module,
            "prepare_epoching_raw_and_events",
            return_value=(raw, events, False),
        ), mock.patch.object(
            epochs_module.mne, "Epochs", return_value=result
        ) as mne_epochs, mock.patch.object(
            epochs_module, "save_rejected_epochs"
        ), mock.patch.object(epochs_module, "plot_epochs"):
            returned = epochs_module.epochs(
                "input_raw.fif", "output-epo.fif", ".", "", config
            )

        self.assertIs(returned, result)
        mne_epochs.assert_called_once_with(raw=raw, events=events, **epoch_kwargs)

    def test_nondefault_epoch_kwargs_run_on_real_mne_raw(self):
        config = {
            "task_type": "task",
            "event_source": "find_events",
            "find_events": {"stim_channel": "STI 014", "shortest_event": 1},
            "epochs": {
                "event_id": 1,
                "tmin": -0.1,
                "tmax": 0.3,
                "baseline": [None, 0.0],
                "picks": "meg",
                "preload": True,
                "reject": {"mag": 1e-9},
                "proj": False,
                "decim": 2,
                "reject_tmin": -0.05,
                "reject_tmax": 0.2,
                "detrend": 1,
                "on_missing": "ignore",
                "reject_by_annotation": False,
                "event_repeated": "merge",
                "verbose": "ERROR",
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            raw_path = temp_dir / "synthetic_raw.fif"
            _synthetic_raw().save(raw_path, overwrite=True, verbose=False)
            with mock.patch.object(epochs_module, "plot_epochs"):
                result = epochs_module.epochs(
                    raw_path,
                    "synthetic-epo.fif",
                    temp_dir,
                    "",
                    config,
                )

            self.assertTrue((temp_dir / "synthetic-epo.fif").is_file())

        self.assertAlmostEqual(result.info["sfreq"], 100.0)
        self.assertAlmostEqual(result.tmin, -0.1)
        self.assertAlmostEqual(result.tmax, 0.3)
        self.assertEqual(result.baseline, (-0.1, 0.0))
        self.assertFalse(result.proj)
        self.assertAlmostEqual(result.reject_tmin, -0.05)
        self.assertAlmostEqual(result.reject_tmax, 0.2)


class CovarianceConfigContractTests(unittest.TestCase):
    def test_raw_covariance_kwargs_reach_real_mne_call(self):
        raw_kwargs = {
            "tmin": 0.2,
            "tmax": 5.0,
            "tstep": 0.4,
            "reject": None,
            "flat": None,
            "method": "empirical",
            "cv": 2,
            "n_jobs": 1,
            "return_estimators": False,
            "reject_by_annotation": False,
            "verbose": "ERROR",
        }
        original_compute = mne.compute_raw_covariance
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            target_path = temp_dir / "target_raw.fif"
            noise_path = temp_dir / "noise_raw.fif"
            _synthetic_raw(seed=21).save(target_path, overwrite=True, verbose=False)
            _synthetic_raw(seed=22).save(noise_path, overwrite=True, verbose=False)
            with mock.patch.object(
                compute_covariance.mne,
                "compute_raw_covariance",
                wraps=original_compute,
            ) as compute_raw_covariance:
                compute_covariance.compute_covariances(
                    noise_path,
                    target_path,
                    "raw",
                    "",
                    temp_dir / "covariance",
                    "raw",
                    {"compute_raw_covariance": raw_kwargs},
                    {
                        "source_methods": ["dSPM"],
                        "data_type": "meg",
                        "rank_policy": "auto",
                    },
                    visualize=False,
                )

        passed = compute_raw_covariance.call_args.kwargs
        self.assertEqual({key: passed[key] for key in raw_kwargs}, raw_kwargs)
        self.assertEqual(passed["rank"], {"mag": 2})

    def test_epoch_and_covariance_kwargs_reach_their_mne_apis(self):
        epoch_kwargs = {
            "event_id": 1,
            "tmin": 0.0,
            "tmax": 0.5,
            "baseline": None,
            "picks": "meg",
            "preload": True,
            "proj": False,
            "decim": 2,
            "reject_by_annotation": False,
            "verbose": "ERROR",
        }
        config = {
            "task_type": "resting",
            "resting": {"fixed_length_duration": 1.0},
            "epochs": epoch_kwargs,
        }
        raw = _synthetic_raw()
        original_epochs = mne.Epochs
        with mock.patch.object(
            compute_covariance.mne, "Epochs", wraps=original_epochs
        ) as mne_epochs:
            _, prepared = compute_covariance.prepare_covariance_epochs(raw, "", config)

        self.assertGreater(len(prepared), 0)
        passed_epoch_kwargs = dict(mne_epochs.call_args.kwargs)
        passed_events = passed_epoch_kwargs.pop("events")
        self.assertIs(passed_epoch_kwargs.pop("raw"), raw)
        self.assertEqual(passed_epoch_kwargs, epoch_kwargs)
        np.testing.assert_array_equal(passed_events, prepared.events)

        covariance_kwargs = {
            "keep_sample_mean": False,
            "tmin": 0.0,
            "tmax": 0.2,
            "method": "empirical",
            "cv": 2,
            "n_jobs": 1,
            "return_estimators": False,
            "on_mismatch": "warn",
            "verbose": "ERROR",
        }
        passed = compute_covariance._noise_covariance_kwargs(
            "epochs", {"covariance": covariance_kwargs}, {"mag": 2}
        )
        self.assertEqual({key: passed[key] for key in covariance_kwargs}, covariance_kwargs)
        self.assertEqual(passed["rank"], {"mag": 2})


class SourceConfigContractTests(unittest.TestCase):
    def test_representative_kwargs_match_pinned_mne_signatures(self):
        inspect.signature(mne.minimum_norm.make_inverse_operator).bind(
            None,
            None,
            None,
            loose=0.2,
            depth=None,
            fixed=False,
            rank={"mag": 2},
            use_cps=False,
            verbose="ERROR",
        )
        inspect.signature(mne.minimum_norm.apply_inverse).bind(
            None,
            None,
            lambda2=0.0625,
            method="dSPM",
            pick_ori="normal",
            prepared=False,
            use_cps=False,
            verbose="ERROR",
        )
        inspect.signature(mne.minimum_norm.apply_inverse_raw).bind(
            None,
            None,
            lambda2=0.0625,
            method="dSPM",
            start=10,
            stop=200,
            nave=2,
            pick_ori="normal",
            buffer_size=100,
            use_cps=False,
            verbose="ERROR",
        )
        inspect.signature(mne.beamformer.make_lcmv).bind(
            None,
            None,
            None,
            reg=0.1,
            noise_cov=None,
            pick_ori="max-power",
            rank={"mag": 2},
            weight_norm="nai",
            reduce_rank=True,
            depth=0.8,
            inversion="single",
            verbose="ERROR",
        )
        inspect.signature(mne.beamformer.apply_lcmv_raw).bind(
            None, None, start=10, stop=200, verbose="ERROR"
        )

    def test_minimum_norm_kwargs_reach_make_and_apply_inverse(self):
        config = {
            "dSPM": {
                "make_inverse_operator": {
                    "loose": 0.2,
                    "depth": None,
                    "fixed": False,
                    "use_cps": False,
                    "verbose": "ERROR",
                },
                "apply_inverse": {
                    "lambda2": 0.0625,
                    "method": "dSPM",
                    "pick_ori": "normal",
                    "prepared": False,
                    "use_cps": False,
                    "verbose": "ERROR",
                },
            }
        }
        evoked = mock.Mock()
        evoked.info = mock.sentinel.info
        inverse_operator = mock.sentinel.inverse_operator
        stc = mock.Mock()
        with mock.patch.object(
            source_localization,
            "make_inverse_operator",
            return_value=inverse_operator,
        ) as make_inverse_operator, mock.patch.object(
            source_localization, "apply_inverse", return_value=stc
        ) as apply_inverse:
            source_localization.compute_minimum_norm(
                "dSPM",
                evoked,
                mock.sentinel.forward,
                mock.sentinel.noise_cov,
                "/output",
                "sub-01",
                "/subjects",
                "event",
                "ico4",
                config,
                False,
                {"mag": 2},
            )

        self.assertEqual(
            make_inverse_operator.call_args.kwargs,
            {
                "info": evoked.info,
                "forward": mock.sentinel.forward,
                "noise_cov": mock.sentinel.noise_cov,
                "loose": 0.2,
                "depth": None,
                "fixed": False,
                "use_cps": False,
                "verbose": "ERROR",
                "rank": {"mag": 2},
            },
        )
        apply_inverse.assert_called_once_with(
            evoked,
            inverse_operator,
            lambda2=0.0625,
            method="dSPM",
            pick_ori="normal",
            prepared=False,
            use_cps=False,
            verbose="ERROR",
        )

    def test_raw_minimum_norm_and_lcmv_apply_kwargs_reach_mne(self):
        raw = _synthetic_raw().copy().pick("meg")
        config = {
            "spacing": "ico4",
            "epoch_label": "continuous",
            "source_methods": ["dSPM", "LCMV"],
            "data_type": "meg",
            "rank_policy": "auto",
            "dSPM": {
                "make_inverse_operator": {"use_cps": False},
                "apply_inverse_raw": {
                    "lambda2": 0.04,
                    "method": "dSPM",
                    "start": 10,
                    "stop": 200,
                    "nave": 2,
                    "pick_ori": "normal",
                    "buffer_size": 100,
                    "use_cps": False,
                    "verbose": "ERROR",
                },
            },
            "LCMV": {
                "make_lcmv": {
                    "reg": 0.1,
                    "pick_ori": "max-power",
                    "weight_norm": "nai",
                    "inversion": "single",
                },
                "apply_lcmv_raw": {"start": 10, "stop": 200, "verbose": "ERROR"},
            },
        }
        noise_cov = mock.sentinel.noise_cov
        data_cov = mock.sentinel.data_cov
        forward = mock.sentinel.forward
        inverse_operator = mock.sentinel.inverse_operator
        filters = mock.sentinel.filters
        minimum_norm_stc = mock.Mock()
        lcmv_stc = mock.Mock()

        with mock.patch.object(
            source_localization.mne, "read_cov", side_effect=[noise_cov, data_cov]
        ), mock.patch.object(
            source_localization.mne.io, "read_raw_fif", return_value=raw
        ), mock.patch.object(
            source_localization.mne, "read_forward_solution", return_value=forward
        ), mock.patch.object(
            source_localization,
            "_align_source_inputs",
            return_value=(raw, forward, noise_cov, data_cov),
        ), mock.patch.object(
            source_localization, "resolve_rank_policy", return_value={"mag": 2}
        ), mock.patch.object(
            source_localization,
            "make_inverse_operator",
            return_value=inverse_operator,
        ) as make_inverse_operator, mock.patch.object(
            source_localization,
            "apply_inverse_raw",
            return_value=minimum_norm_stc,
        ) as apply_inverse_raw, mock.patch.object(
            source_localization, "make_lcmv", return_value=filters
        ) as make_lcmv, mock.patch.object(
            source_localization, "apply_lcmv_raw", return_value=lcmv_stc
        ) as apply_lcmv_raw:
            source_localization.process_raw(
                "/raw/sub-01/sub-01_raw.fif",
                "/subjects",
                None,
                None,
                "/output",
                config,
                False,
                noise_covariance_file="/cov/bl-cov.fif",
                data_covariance_file="/cov/lcmv-data-cov.fif",
                forward_file="/fwd/continuous_ico4-fwd.fif",
            )

        self.assertEqual(make_inverse_operator.call_args.kwargs["rank"], {"mag": 2})
        apply_inverse_raw.assert_called_once_with(
            raw,
            inverse_operator,
            lambda2=0.04,
            method="dSPM",
            start=10,
            stop=200,
            nave=2,
            pick_ori="normal",
            buffer_size=100,
            use_cps=False,
            verbose="ERROR",
        )
        self.assertEqual(make_lcmv.call_args.kwargs["rank"], {"mag": 2})
        apply_lcmv_raw.assert_called_once_with(
            raw, filters, start=10, stop=200, verbose="ERROR"
        )

    def test_lcmv_evoked_apply_kwargs_are_configurable(self):
        config = {
            "LCMV": {
                "make_lcmv": {"reg": 0.07, "weight_norm": "nai"},
                "apply_lcmv": {"verbose": "ERROR"},
            }
        }
        evoked = mock.Mock()
        evoked.info = mock.sentinel.info
        filters = mock.sentinel.filters
        stc = mock.Mock()
        with mock.patch.object(
            source_localization, "make_lcmv", return_value=filters
        ) as make_lcmv, mock.patch.object(
            source_localization, "apply_lcmv", return_value=stc
        ) as apply_lcmv:
            source_localization.compute_LCMV(
                evoked,
                mock.sentinel.forward,
                mock.sentinel.data_cov,
                mock.sentinel.noise_cov,
                "/output",
                "sub-01",
                "/subjects",
                "event",
                "ico4",
                config,
                False,
                {"mag": 2},
            )

        self.assertEqual(make_lcmv.call_args.kwargs["reg"], 0.07)
        self.assertEqual(make_lcmv.call_args.kwargs["weight_norm"], "nai")
        self.assertEqual(make_lcmv.call_args.kwargs["rank"], {"mag": 2})
        apply_lcmv.assert_called_once_with(evoked, filters, verbose="ERROR")


class IcaNumComponentsContractTests(unittest.TestCase):
    def _run_main_with_num_components(self, value):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            args = types.SimpleNamespace(
                raw_file=str(temp_path / "sub-01_raw.fif"),
                num_IC=float(value),
                output_dir=str(temp_path / "output"),
                fname_bad_channels=str(temp_path / "bad_channels.txt"),
                fname_bad_segments=str(temp_path / "bad_segments.txt"),
                seed=2025,
                compute_explained_variance=False,
            )
            with mock.patch.object(
                run_ica_module, "parse_arguments", return_value=args
            ), mock.patch.object(run_ica_module, "run_ica") as run_ica:
                run_ica_module.main()
        return run_ica.call_args.kwargs["n_IC"]

    def test_explained_variance_threshold_remains_float(self):
        value = self._run_main_with_num_components(0.9999)

        self.assertIsInstance(value, float)
        self.assertEqual(value, 0.9999)

    def test_integer_component_count_remains_supported(self):
        value = self._run_main_with_num_components(60)

        self.assertIsInstance(value, int)
        self.assertEqual(value, 60)


class IcaInputPreflightTests(unittest.TestCase):
    def _write_ica_inputs(
        self,
        directory,
        *,
        sfreq=10.0,
        n_times=100,
        annotations=(),
        bad_channels=(),
    ):
        directory = Path(directory)
        raw_path = directory / "synthetic_raw.fif"
        bad_channel_path = directory / "bad_channels.txt"
        bad_segment_path = directory / "bad_segments.txt"
        info = mne.create_info(
            ["MEG001", "MEG002", "STI 014"],
            sfreq,
            ch_types=["mag", "mag", "stim"],
        )
        raw = mne.io.RawArray(
            np.zeros((3, n_times), dtype=float), info, verbose=False
        )
        raw.save(raw_path, overwrite=True, verbose=False)
        bad_channel_path.write_text(
            "".join(f"{name}\n" for name in bad_channels), encoding="utf-8"
        )
        annotation_list = list(annotations)
        saved_annotations = mne.Annotations(
            onset=[item[0] for item in annotation_list],
            duration=[item[1] for item in annotation_list],
            description=[item[2] for item in annotation_list],
        )
        saved_annotations.save(bad_segment_path, overwrite=True)
        return raw_path, bad_channel_path, bad_segment_path

    def _prepare(self, directory, *, n_components=2, **input_kwargs):
        paths = self._write_ica_inputs(directory, **input_kwargs)
        validation_path = Path(directory) / "ica_input_validation.json"
        raw, validation = run_ica_module.prepare_ica_input(
            fn_data=paths[0],
            n_components=n_components,
            modality="meg",
            fname_bad_channels=paths[1],
            fname_bad_segments=paths[2],
            validation_path=validation_path,
        )
        return raw, validation, paths, validation_path

    def test_empty_annotations_validate_without_preloading_or_reading_signal(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            mne.io.BaseRaw,
            "load_data",
            side_effect=AssertionError("preflight must not read signal samples"),
        ):
            raw, validation, _, validation_path = self._prepare(temp_dir)
            saved_validation = json.loads(validation_path.read_text())

        self.assertFalse(raw.preload)
        self.assertEqual(validation["status"], "passed")
        self.assertEqual(validation["total_samples"], 100)
        self.assertEqual(validation["bad_samples"], 0)
        self.assertEqual(validation["usable_samples"], 100)
        self.assertEqual(validation["eligible_channel_count"], 2)
        self.assertEqual(validation["bad_channel_count"], 0)
        self.assertEqual(saved_validation, validation)

    def test_overlapping_adjacent_bad_annotations_are_merged_by_sample(self):
        annotations = (
            (1.0, 2.0, "BAD_motion"),
            (2.0, 2.0, "bad_overlap"),
            (4.0, 1.0, "Bad_adjacent"),
            (5.0, 0.0, "BAD_zero_duration"),
            (6.0, 1.0, "notbad"),
            (7.0, 1.0, "EDGE boundary"),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            _, validation, _, _ = self._prepare(
                temp_dir, annotations=annotations
            )

        self.assertEqual(validation["bad_samples"], 40)
        self.assertEqual(validation["usable_samples"], 60)
        self.assertAlmostEqual(validation["bad_seconds"], 4.0)
        self.assertAlmostEqual(validation["bad_coverage_fraction"], 0.4)

    def test_bad_annotations_are_cropped_to_recording_boundaries(self):
        annotations = (
            (-1.0, 2.0, "BAD_before_start"),
            (9.5, 2.0, "BAD_after_end"),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            _, validation, _, _ = self._prepare(
                temp_dir, annotations=annotations
            )

        self.assertEqual(validation["bad_samples"], 15)
        self.assertEqual(validation["usable_samples"], 85)

    def test_all_meg_channels_bad_has_stable_actionable_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._write_ica_inputs(
                temp_dir, bad_channels=("MEG001", "MEG002")
            )
            validation_path = Path(temp_dir) / "ica_input_validation.json"
            with self.assertRaises(run_ica_module.ICAInputValidationError) as raised:
                run_ica_module.prepare_ica_input(
                    fn_data=paths[0],
                    n_components=2,
                    modality="meg",
                    fname_bad_channels=paths[1],
                    fname_bad_segments=paths[2],
                    validation_path=validation_path,
                )

            error = raised.exception
            self.assertEqual(error.code, "no_eligible_meg_channels")
            self.assertIn(str(paths[2]), str(error))
            self.assertIn("bad-channel", str(error).lower())
            self.assertEqual(
                json.loads(validation_path.read_text())["error_code"], error.code
            )

    def test_all_samples_bad_has_named_error_and_coverage_statistics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._write_ica_inputs(
                temp_dir, annotations=((0.0, 10.0, "BAD_everything"),)
            )
            validation_path = Path(temp_dir) / "ica_input_validation.json"
            with self.assertRaises(run_ica_module.ICAInputValidationError) as raised:
                run_ica_module.prepare_ica_input(
                    fn_data=paths[0],
                    n_components=2,
                    modality="meg",
                    fname_bad_channels=paths[1],
                    fname_bad_segments=paths[2],
                    validation_path=validation_path,
                )

            error = raised.exception
            self.assertEqual(
                error.code, "no_usable_samples_after_bad_annotations"
            )
            self.assertIn("ICA_INPUT_ALL_BAD", str(error))
            self.assertIn("100/100", str(error))
            self.assertIn(str(paths[2]), str(error))
            validation = json.loads(validation_path.read_text())
            self.assertEqual(validation["bad_samples"], 100)
            self.assertEqual(validation["usable_samples"], 0)
            self.assertEqual(validation["bad_coverage_fraction"], 1.0)

    def test_integer_components_cannot_exceed_channels_or_usable_samples(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._write_ica_inputs(temp_dir)
            with self.assertRaises(run_ica_module.ICAInputValidationError) as raised:
                run_ica_module.prepare_ica_input(
                    fn_data=paths[0],
                    n_components=3,
                    modality="meg",
                    fname_bad_channels=paths[1],
                    fname_bad_segments=paths[2],
                )

        self.assertEqual(
            raised.exception.code,
            "requested_components_exceed_available_input",
        )
        self.assertIn("2 eligible", str(raised.exception))

    def test_float_components_require_at_least_two_usable_samples(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._write_ica_inputs(temp_dir, n_times=1)
            with self.assertRaises(run_ica_module.ICAInputValidationError) as raised:
                run_ica_module.prepare_ica_input(
                    fn_data=paths[0],
                    n_components=0.999,
                    modality="meg",
                    fname_bad_channels=paths[1],
                    fname_bad_segments=paths[2],
                )

        self.assertEqual(
            raised.exception.code,
            "requested_components_exceed_available_input",
        )
        self.assertIn("at least 2 usable samples", str(raised.exception))

    def test_float_components_are_not_rejected_from_header_rank_guessing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _, validation, _, _ = self._prepare(
                temp_dir, n_components=0.9999
            )

        self.assertEqual(validation["status"], "passed")
        self.assertEqual(validation["requested_components"], 0.9999)

    def test_misaligned_annotation_sidecar_has_stable_error_and_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._write_ica_inputs(
                temp_dir,
                annotations=((1000.0, 1.0, "BAD_from_another_recording"),),
            )
            validation_path = Path(temp_dir) / "ica_input_validation.json"
            with self.assertRaises(run_ica_module.ICAInputValidationError) as raised:
                run_ica_module.prepare_ica_input(
                    fn_data=paths[0],
                    n_components=2,
                    modality="meg",
                    fname_bad_channels=paths[1],
                    fname_bad_segments=paths[2],
                    validation_path=validation_path,
                )

            error = raised.exception
            self.assertEqual(error.code, "invalid_bad_segment_sidecar")
            self.assertIn(str(paths[2]), str(error))
            self.assertIn("regenerate", str(error).lower())
            self.assertEqual(
                json.loads(validation_path.read_text())["error_code"], error.code
            )

    def test_run_ica_writes_failed_validation_before_loading_signal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            paths = self._write_ica_inputs(
                temp_dir, annotations=((0.0, 10.0, "BAD_everything"),)
            )
            result_dir = temp_dir / "result"
            with mock.patch.object(
                mne.io.BaseRaw,
                "load_data",
                side_effect=AssertionError("failed preflight loaded signal"),
            ), self.assertRaises(run_ica_module.ICAInputValidationError):
                run_ica_module.run_ica(
                    subj_tag="synthetic",
                    subj_res_path=result_dir,
                    subj_res_path_ica=result_dir / "ica_results",
                    fn_data=paths[0],
                    fn_ica="synthetic-ica.fif",
                    n_IC=2,
                    modality="meg",
                    fname_bad_channels=paths[1],
                    fname_bad_segments=paths[2],
                    random_seed=2025,
                )

            validation_path = result_dir / "ica_input_validation.json"
            self.assertTrue(validation_path.is_file())
            self.assertEqual(
                json.loads(validation_path.read_text())["error_code"],
                "no_usable_samples_after_bad_annotations",
            )


if __name__ == "__main__":
    unittest.main()
