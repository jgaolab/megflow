import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import mne
import numpy as np


MEGQC_DIR = (
    Path(__file__).resolve().parents[1] / "megflow" / "tools" / "megqc"
)
if str(MEGQC_DIR) not in sys.path:
    sys.path.insert(0, str(MEGQC_DIR))

import score_meg_reference_quota_standalone as scorer


class NormMegQcPreprocessingTests(unittest.TestCase):
    @staticmethod
    def _raw(sfreq=1000.0, duration=2.0):
        rng = np.random.default_rng(2025)
        n_times = int(round(sfreq * duration))
        info = mne.create_info(
            ["MEG001", "MEG002"],
            sfreq=sfreq,
            ch_types=["mag", "mag"],
        )
        data = rng.standard_normal((2, n_times)) * 1e-12
        return mne.io.RawArray(data, info, verbose="error")

    def test_missing_or_empty_config_uses_isolated_internal_defaults(self):
        missing = scorer.load_preproc_steps("")
        empty = scorer.load_preproc_steps('{"preproc": []}')

        self.assertEqual(missing, scorer.DEFAULT_REFERENCE_PREPROC_STEPS)
        self.assertEqual(empty, scorer.DEFAULT_REFERENCE_PREPROC_STEPS)
        self.assertIsNot(missing, scorer.DEFAULT_REFERENCE_PREPROC_STEPS)
        missing[0]["filter"]["l_freq"] = 9.0
        self.assertEqual(
            scorer.DEFAULT_REFERENCE_PREPROC_STEPS[0]["filter"]["l_freq"],
            1.0,
        )

    def test_internal_defaults_can_only_be_disabled_explicitly(self):
        self.assertEqual(scorer.load_preproc_steps("off"), [])
        self.assertEqual(
            scorer.load_preproc_steps('{"preproc": false}'),
            [],
        )

    def test_internal_default_pipeline_is_executable(self):
        raw = self._raw(duration=10.0)
        args = SimpleNamespace(preproc_config="", n_jobs=1)

        processed, steps = scorer.apply_reference_preprocessing(raw, args)

        self.assertEqual(processed.info["sfreq"], 250.0)
        self.assertEqual(
            [step["step"] for step in steps],
            ["filter", "notch_filter", "resample"],
        )

    def test_resample_step_changes_only_the_scoring_copy(self):
        raw = self._raw()
        args = SimpleNamespace(
            preproc_config=json.dumps(
                {"preproc": [{"resample": {"sfreq": 250}}]}
            ),
            n_jobs=1,
        )

        processed, steps = scorer.apply_reference_preprocessing(raw, args)

        self.assertEqual(raw.info["sfreq"], 1000.0)
        self.assertEqual(processed.info["sfreq"], 250.0)
        self.assertLess(processed.n_times, raw.n_times)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["step"], "resample")
        self.assertEqual(steps[0]["sfreq_before"], 1000.0)
        self.assertEqual(steps[0]["sfreq_after"], 250.0)
        self.assertEqual(steps[0]["status"], "applied")

    def test_resample_at_target_rate_is_recorded_as_skipped(self):
        raw = self._raw(sfreq=250.0)
        args = SimpleNamespace(
            preproc_config=json.dumps(
                {"preproc": [{"resample": {"sfreq": 250}}]}
            ),
            n_jobs=1,
        )

        processed, steps = scorer.apply_reference_preprocessing(raw, args)

        self.assertEqual(processed.info["sfreq"], 250.0)
        self.assertEqual(steps[0]["status"], "skipped")
        self.assertEqual(steps[0]["reason"], "already at target sampling rate")

    def test_invalid_resample_rate_fails_explicitly(self):
        raw = self._raw()
        args = SimpleNamespace(
            preproc_config=json.dumps(
                {"preproc": [{"resample": {"sfreq": 0}}]}
            ),
            n_jobs=1,
        )

        with self.assertRaisesRegex(ValueError, "resample.sfreq"):
            scorer.apply_reference_preprocessing(raw, args)

    def test_fallback_parser_keeps_resample_step(self):
        steps = scorer._fallback_preproc_steps(
            "preproc:\n  - resample: {sfreq: 250}\n"
        )

        self.assertEqual(steps, [{"resample": {"sfreq": 250.0}}])


if __name__ == "__main__":
    unittest.main()
