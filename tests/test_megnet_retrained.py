import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from megflow.tools.megnet_retrained.inference import (
    CLASS_NAMES,
    canonical_labels,
)
from megflow.tools.megnet_retrained.runtime.preprocessing import (
    load_component_sources,
    prepare_source_sampling,
)


class FakeSources:
    def __init__(self, sfreq):
        self.info = {"sfreq": float(sfreq)}
        self.resample_calls = []

    def resample(self, sfreq, *, npad, verbose):
        self.resample_calls.append(float(sfreq))
        self.info["sfreq"] = float(sfreq)
        return self


class FakeRawSources:
    def __init__(self, data, *, first_samp, sfreq=250.0):
        self._data = np.asarray(data, dtype=float)
        self.first_samp = int(first_samp)
        self.info = {"sfreq": float(sfreq)}
        self.ch_names = [
            f"ICA{component_idx:03d}"
            for component_idx in range(self._data.shape[0])
        ]
        self.n_times = self._data.shape[1]

    def get_data(self, *, start=None, stop=None):
        return self._data[:, slice(start, stop)]

    def load_data(self, *, verbose):
        return self

    def resample(self, sfreq, *, npad, verbose):
        self.info["sfreq"] = float(sfreq)
        return self


class FakeRaw:
    def __init__(self, *, n_times, first_samp, sfreq=250.0):
        self.n_times = int(n_times)
        self.first_samp = int(first_samp)
        self.info = {"sfreq": float(sfreq)}


class FakeIca:
    def __init__(self, data):
        self._data = np.asarray(data, dtype=float)
        self.n_components_ = self._data.shape[0]
        self._ica_names = [
            f"ICA{component_idx:03d}"
            for component_idx in range(self.n_components_)
        ]

    def get_sources(self, raw, *, start=None, stop=None):
        return FakeRawSources(
            self._data[:, slice(start, stop)],
            first_samp=raw.first_samp,
            sfreq=raw.info["sfreq"],
        )


class RetrainedMegnetClassTests(unittest.TestCase):
    def test_canonical_class_order_matches_model_output(self):
        self.assertEqual(
            CLASS_NAMES,
            (
                "brain_or_other",
                "heart_beat",
                "eye_blink",
                "eye_movement",
            ),
        )

    def test_canonical_labels_uses_each_component_argmax(self):
        probabilities = np.asarray(
            [
                [0.90, 0.05, 0.03, 0.02],
                [0.10, 0.80, 0.05, 0.05],
                [0.10, 0.20, 0.60, 0.10],
                [0.10, 0.20, 0.10, 0.60],
            ],
            dtype=np.float32,
        )

        self.assertEqual(
            canonical_labels(probabilities),
            [
                "brain_or_other",
                "heart_beat",
                "eye_blink",
                "eye_movement",
            ],
        )

    def test_canonical_labels_rejects_wrong_class_count(self):
        with self.assertRaisesRegex(ValueError, "four class columns"):
            canonical_labels(np.zeros((2, 3), dtype=np.float32))


class RetrainedMegnetSamplingTests(unittest.TestCase):
    def test_sources_above_250_hz_are_resampled_in_memory(self):
        sources = FakeSources(500.0)

        original, effective = prepare_source_sampling(sources, 250.0)

        self.assertEqual(original, 500.0)
        self.assertEqual(effective, 250.0)
        self.assertEqual(sources.resample_calls, [250.0])

    def test_sources_at_250_hz_are_not_resampled(self):
        sources = FakeSources(250.0)

        original, effective = prepare_source_sampling(sources, 250.0)

        self.assertEqual((original, effective), (250.0, 250.0))
        self.assertEqual(sources.resample_calls, [])

    def test_sources_below_250_hz_are_not_resampled(self):
        sources = FakeSources(200.0)

        original, effective = prepare_source_sampling(sources, 250.0)

        self.assertEqual((original, effective), (200.0, 200.0))
        self.assertEqual(sources.resample_calls, [])

    def test_precomputed_sources_accept_reset_first_sample_when_data_match(self):
        data = np.arange(2400, dtype=float).reshape(2, 1200) / 1000.0
        raw = FakeRaw(n_times=data.shape[1], first_samp=3250)
        ica = FakeIca(data)
        saved_sources = FakeRawSources(data, first_samp=0)

        with mock.patch(
            "megflow.tools.megnet_retrained.runtime.preprocessing.read_raw_fif",
            return_value=saved_sources,
        ):
            bundle = load_component_sources(
                raw,
                ica,
                ica_sources_file=Path("ica_sources.fif"),
            )

        self.assertEqual(bundle.raw_first_samp, 3250)
        self.assertEqual(bundle.source_first_samp, 0)
        np.testing.assert_allclose(bundle.data, data.astype(np.float32))

    def test_precomputed_sources_reject_mismatch_at_recording_end(self):
        data = np.arange(6000, dtype=float).reshape(2, 3000) / 1000.0
        raw = FakeRaw(n_times=data.shape[1], first_samp=3250)
        ica = FakeIca(data)
        stale_data = data.copy()
        stale_data[:, -1] += 1.0
        saved_sources = FakeRawSources(stale_data, first_samp=0)

        with mock.patch(
            "megflow.tools.megnet_retrained.runtime.preprocessing.read_raw_fif",
            return_value=saved_sources,
        ):
            with self.assertRaisesRegex(ValueError, "verification segment"):
                load_component_sources(
                    raw,
                    ica,
                    ica_sources_file=Path("ica_sources.fif"),
                )


if __name__ == "__main__":
    unittest.main()
