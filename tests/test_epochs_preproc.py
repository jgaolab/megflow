import tempfile
import unittest
import sys
import types
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

import epochs_preproc
import compute_covariance
import epochs as epochs_module


def _make_raw(sfreq=1000.0, duration=4.0, first_samp=0):
    n_times = int(round(sfreq * duration))
    times = np.arange(n_times) / sfreq
    data = np.zeros((2, n_times), dtype=float)
    data[0] = 1e-12 * np.sin(2 * np.pi * 10.0 * times)
    for sample, value in ((int(sfreq), 1), (int(2 * sfreq), 2)):
        data[1, sample : sample + max(2, int(0.01 * sfreq))] = value
    info = mne.create_info(
        ["MEG 001", "STI 014"],
        sfreq,
        ch_types=["mag", "stim"],
    )
    return mne.io.RawArray(data, info, first_samp=first_samp, verbose=False)


class ContinuousEpochPreprocTests(unittest.TestCase):
    def test_epoch_artifact_sidecars_require_a_complete_pair(self):
        with self.assertRaisesRegex(
            ValueError,
            "Both bad-channel and bad-segment sidecars are required",
        ):
            epochs_module.load_epoch_artifact_sidecars(
                _make_raw(),
                fname_bad_channels="bad_channels.txt",
            )

    def test_epoch_artifact_sidecars_restore_bad_channels_and_segments(self):
        raw = _make_raw()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            bad_channels_file = tmpdir / "bad_channels.txt"
            bad_segments_file = tmpdir / "bad_segments.txt"
            bad_channels_file.write_text("MEG 001\n", encoding="utf-8")
            mne.Annotations(
                onset=[0.95],
                duration=[0.2],
                description=["BAD_artifact"],
            ).save(bad_segments_file, overwrite=True)

            loaded = epochs_module.load_epoch_artifact_sidecars(
                raw,
                bad_channels_file,
                bad_segments_file,
            )

        self.assertEqual(loaded.info["bads"], ["MEG 001"])
        self.assertEqual(list(loaded.annotations.description), ["BAD_artifact"])
        np.testing.assert_allclose(loaded.annotations.onset, [0.95])

    def test_epoch_process_rejects_segments_loaded_from_artifact_sidecar(self):
        config = {
            "preproc": [],
            "task_type": "task",
            "event_source": "find_events",
            "find_events": {"stim_channel": "STI 014", "shortest_event": 1},
            "epochs": {
                "event_id": None,
                "tmin": -0.1,
                "tmax": 0.2,
                "baseline": None,
                "preload": True,
                "picks": "meg",
                "reject_by_annotation": True,
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            input_file = tmpdir / "input_raw.fif"
            bad_channels_file = tmpdir / "bad_channels.txt"
            bad_segments_file = tmpdir / "bad_segments.txt"
            _make_raw().save(input_file, overwrite=True, verbose=False)
            bad_channels_file.write_text("", encoding="utf-8")
            mne.Annotations(
                onset=[0.95],
                duration=[0.2],
                description=["BAD_artifact"],
            ).save(bad_segments_file, overwrite=True)

            with mock.patch.object(epochs_module, "plot_epochs"):
                result = epochs_module.epochs(
                    input_file,
                    "output-epo.fif",
                    tmpdir,
                    "",
                    config,
                    fname_bad_channels=bad_channels_file,
                    fname_bad_segments=bad_segments_file,
                )

        self.assertEqual(len(result), 1)
        np.testing.assert_array_equal(result.events[:, 2], [2])

    def test_empty_preproc_is_true_noop(self):
        for value in (None, [], {}, {"steps": []}):
            with self.subTest(value=value):
                raw = _make_raw()
                events = mne.find_events(raw, stim_channel="STI 014", verbose=False)
                original_events = events.copy()
                output_raw, output_events, applied = epochs_preproc.prepare_analysis_raw(
                    raw,
                    {"preproc": value},
                    events=events,
                )
                self.assertIs(output_raw, raw)
                self.assertFalse(applied)
                self.assertEqual(output_raw.info["sfreq"], 1000.0)
                np.testing.assert_array_equal(output_events, original_events)

    def test_find_events_are_remapped_during_resample(self):
        raw = _make_raw()
        events = mne.find_events(raw, stim_channel="STI 014", verbose=False)
        raw, events, applied = epochs_preproc.prepare_analysis_raw(
            raw,
            {"preproc": [{"resample": {"sfreq": 250.0}}]},
            events=events,
        )
        self.assertTrue(applied)
        self.assertEqual(raw.info["sfreq"], 250.0)
        np.testing.assert_array_equal(events[:, 0], [250, 500])
        np.testing.assert_array_equal(events[:, 2], [1, 2])

        shifted = epochs_module.apply_event_time_shift(
            events,
            raw.info["sfreq"],
            {"event_time_shift_sec": 0.04},
        )
        np.testing.assert_array_equal(shifted[:, 0], [260, 510])

    def test_resample_preserves_event_times_with_nonzero_first_sample(self):
        raw = _make_raw(first_samp=1000)
        events = mne.find_events(raw, stim_channel="STI 014", verbose=False)
        np.testing.assert_array_equal(events[:, 0], [2000, 3000])
        raw, events, _ = epochs_preproc.prepare_analysis_raw(
            raw,
            {"preproc": [{"resample": {"sfreq": 250.0}}]},
            events=events,
        )
        np.testing.assert_array_equal(events[:, 0], [500, 750])
        relative_times = (events[:, 0] - raw.first_samp) / raw.info["sfreq"]
        np.testing.assert_allclose(relative_times, [1.0, 2.0], atol=1e-12)

    def test_filter_updates_analysis_frequency_metadata(self):
        raw = _make_raw()
        raw, _, applied = epochs_preproc.prepare_analysis_raw(
            raw,
            {
                "preproc": [
                    {
                        "filter": {
                            "l_freq": 1.0,
                            "h_freq": 30.0,
                            "method": "iir",
                            "iir_params": {"order": 5, "ftype": "butter"},
                        }
                    }
                ]
            },
        )
        self.assertTrue(applied)
        self.assertAlmostEqual(raw.info["highpass"], 1.0)
        self.assertAlmostEqual(raw.info["lowpass"], 30.0)

    def test_bids_onsets_use_final_sampling_rate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            events_file = Path(tmpdir) / "events.tsv"
            events_file.write_text(
                "onset\ttrial_type\tvalue\n1.234\tword\t1\n",
                encoding="utf-8",
            )
            raw, events, applied = epochs_module.prepare_epoching_raw_and_events(
                _make_raw(),
                {
                    "preproc": [{"resample": {"sfreq": 250.0}}],
                    "event_source": "event_file",
                    "event_file": {"trial_type": {"word": 1}},
                },
                events_file,
            )
        self.assertTrue(applied)
        self.assertEqual(raw.info["sfreq"], 250.0)
        np.testing.assert_array_equal(events, [[308, 0, 1]])

    def test_annotations_use_final_sampling_rate(self):
        raw = _make_raw()
        raw.set_annotations(mne.Annotations([1.0], [0.0], ["stimulus"]))
        raw, events, applied = epochs_module.prepare_epoching_raw_and_events(
            raw,
            {
                "preproc": [{"resample": {"sfreq": 250.0}}],
                "event_source": "annotations",
                "annotations": {"event_id": 7},
            },
        )
        self.assertTrue(applied)
        self.assertEqual(raw.info["sfreq"], 250.0)
        np.testing.assert_array_equal(events, [[250, 0, 7]])

    def test_resting_events_are_created_after_resample(self):
        raw, events, applied = epochs_module.prepare_epoching_raw_and_events(
            _make_raw(duration=4.0),
            {
                "preproc": [{"resample": {"sfreq": 250.0}}],
                "task_type": "resting",
                "resting": {"fixed_length_duration": 1.0},
            },
        )
        self.assertTrue(applied)
        self.assertEqual(raw.info["sfreq"], 250.0)
        np.testing.assert_array_equal(events[:, 0], [0, 250, 500, 750])

    def test_epoch_process_saves_analysis_raw_with_remapped_events(self):
        config = {
            "preproc": [{"resample": {"sfreq": 250.0}}],
            "task_type": "task",
            "event_source": "find_events",
            "event_time_shift_sec": 0.04,
            "find_events": {"stim_channel": "STI 014", "shortest_event": 1},
            "epochs": {
                "event_id": None,
                "tmin": -0.1,
                "tmax": 0.2,
                "baseline": None,
                "preload": True,
                "picks": "meg",
                "reject_by_annotation": False,
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            input_file = tmpdir / "input_raw.fif"
            analysis_file = tmpdir / "input_analysis-raw.fif"
            _make_raw().save(input_file, overwrite=True, verbose=False)
            with mock.patch.object(epochs_module, "plot_epochs"):
                result = epochs_module.epochs(
                    input_file,
                    "output-epo.fif",
                    tmpdir,
                    "",
                    config,
                    output_analysis_raw_file=analysis_file,
                )

            self.assertTrue(analysis_file.is_file())
            self.assertTrue((tmpdir / "output-epo.fif").is_file())
            self.assertEqual(result.info["sfreq"], 250.0)
            np.testing.assert_array_equal(result.events[:, 0], [260, 510])

    def test_epoch_process_does_not_save_analysis_raw_for_empty_preproc(self):
        config = {
            "preproc": [],
            "task_type": "task",
            "event_source": "find_events",
            "find_events": {"stim_channel": "STI 014", "shortest_event": 1},
            "epochs": {
                "event_id": None,
                "tmin": -0.1,
                "tmax": 0.2,
                "baseline": None,
                "preload": True,
                "picks": "meg",
                "reject_by_annotation": False,
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            input_file = tmpdir / "input_raw.fif"
            analysis_file = tmpdir / "should_not_exist_analysis-raw.fif"
            _make_raw().save(input_file, overwrite=True, verbose=False)
            with mock.patch.object(epochs_module, "plot_epochs"):
                result = epochs_module.epochs(
                    input_file,
                    "output-epo.fif",
                    tmpdir,
                    "",
                    config,
                    output_analysis_raw_file=analysis_file,
                )

            self.assertFalse(analysis_file.exists())
            self.assertEqual(result.info["sfreq"], 1000.0)
            np.testing.assert_array_equal(result.events[:, 0], [1000, 2000])

    def test_covariance_epochs_use_same_preproc_and_event_mapping(self):
        epoch_config = {
            "preproc": [{"resample": {"sfreq": 250.0}}],
            "task_type": "task",
            "event_source": "find_events",
            "event_time_shift_sec": 0.04,
            "find_events": {"stim_channel": "STI 014", "shortest_event": 1},
            "epochs": {
                "event_id": None,
                "tmin": -0.1,
                "tmax": 0.0,
                "baseline": None,
                "preload": True,
                "picks": "meg",
                "reject_by_annotation": False,
            },
        }
        covariance_config = dict(epoch_config)
        covariance_config.pop("preproc")
        covariance_config["analysis_preproc"] = epoch_config["preproc"]

        epoch_raw, epoch_events, _ = epochs_module.prepare_epoching_raw_and_events(
            _make_raw(),
            epoch_config,
        )
        covariance_raw, covariance_epochs = compute_covariance.prepare_covariance_epochs(
            _make_raw(),
            "",
            covariance_config,
        )

        self.assertEqual(epoch_raw.info["sfreq"], 250.0)
        self.assertEqual(covariance_raw.info["sfreq"], 250.0)
        np.testing.assert_array_equal(covariance_epochs.events, epoch_events)

    def test_invalid_analysis_preproc_operation_fails_early(self):
        with self.assertRaisesRegex(ValueError, "Unsupported epochs.preproc operation"):
            epochs_preproc.prepare_analysis_raw(
                _make_raw(),
                {"preproc": [{"unsupported": {}}]},
            )


if __name__ == "__main__":
    unittest.main()
