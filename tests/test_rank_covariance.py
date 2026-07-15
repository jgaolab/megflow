import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mne
import numpy as np


MEGFLOW_DIR = Path(__file__).resolve().parents[1] / "megflow"
if str(MEGFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(MEGFLOW_DIR))

import compute_covariance
import source_localization
from utils import (
    RankConfigurationError,
    ranked_mne_kwargs,
    resolve_rank_policy,
)


mne.set_log_level("ERROR")


def low_rank_raw(channel_names=("MEG001", "MEG002", "MEG003"), seed=7):
    rng = np.random.default_rng(seed)
    first = rng.standard_normal(600) * 1e-12
    second = rng.standard_normal(600) * 1e-12
    rows = {
        "MEG001": first,
        "MEG002": second,
        "MEG003": first.copy(),
        "MEG004": second.copy(),
    }
    data = np.vstack([rows[name] for name in channel_names])
    info = mne.create_info(list(channel_names), 100.0, ["mag"] * len(channel_names))
    return mne.io.RawArray(data, info, verbose=False)


class RankPolicyTests(unittest.TestCase):
    def test_auto_uses_empirical_target_rank_instead_of_info_rank(self):
        raw = low_rank_raw()

        self.assertEqual(resolve_rank_policy(raw, "auto"), {"mag": 2})
        self.assertEqual(resolve_rank_policy(raw, None), {"mag": 2})
        self.assertEqual(resolve_rank_policy(raw, "info"), {"mag": 3})
        self.assertEqual(resolve_rank_policy(raw, "full"), {"mag": 3})
        self.assertEqual(resolve_rank_policy(raw, {"mag": 1}), {"mag": 1})

    def test_explicit_then_legacy_then_policy_precedence(self):
        resolved = {"mag": 2}

        explicit = ranked_mne_kwargs(
            {"rank": None}, resolved, "source.LCMV.make_lcmv", legacy_rank=50
        )
        legacy = ranked_mne_kwargs(
            {}, resolved, "source.LCMV.make_lcmv", legacy_rank=50
        )
        default = ranked_mne_kwargs({}, resolved, "source.LCMV.make_lcmv")

        self.assertIsNone(explicit["rank"])
        self.assertEqual(legacy["rank"], {"meg": 50})
        self.assertEqual(default["rank"], resolved)

    def test_integer_is_rejected_for_direct_mne_rank_field(self):
        with self.assertRaisesRegex(RankConfigurationError, "rank dictionary"):
            ranked_mne_kwargs(
                {"rank": 50}, {"mag": 2}, "covariance.compute_raw_covariance"
            )


class CovarianceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        target = low_rank_raw()
        noise = low_rank_raw(("MEG002", "MEG001", "MEG004"), seed=11)
        events = np.column_stack(
            [np.arange(100, 501, 100), np.zeros(5, dtype=int), np.ones(5, dtype=int)]
        )
        epochs = mne.Epochs(
            target,
            events,
            event_id=1,
            tmin=-0.1,
            tmax=0.2,
            baseline=None,
            preload=True,
            verbose=False,
        )

        self.target_raw_path = self.root / "target_raw.fif"
        self.noise_raw_path = self.root / "emptyroom_raw.fif"
        self.epochs_path = self.root / "target-epo.fif"
        target.save(self.target_raw_path, overwrite=True, verbose=False)
        noise.save(self.noise_raw_path, overwrite=True, verbose=False)
        epochs.save(self.epochs_path, overwrite=True, verbose=False)
        self.covariance_config = {
            "rank_policy": "auto",
            "compute_raw_covariance": {"method": "empirical"},
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dspm_only_skips_lcmv_data_covariance(self):
        output_dir = self.root / "dspm"
        output_dir.mkdir()
        (output_dir / "lcmv-data-cov.fif").write_text(
            "stale LCMV output\n", encoding="utf-8"
        )
        noise_path, data_path, resolved_rank = compute_covariance.compute_covariances(
            self.noise_raw_path,
            self.target_raw_path,
            "raw",
            "",
            output_dir,
            "raw",
            self.covariance_config,
            {
                "source_methods": ["dSPM"],
                "data_type": "meg",
                "rank_policy": "auto",
            },
            visualize=False,
        )

        self.assertTrue(noise_path.is_file())
        self.assertIsNone(data_path)
        self.assertFalse((output_dir / "lcmv-data-cov.fif").exists())
        self.assertEqual(resolved_rank, {"mag": 2})
        self.assertEqual(mne.read_cov(noise_path, verbose=False).ch_names, ["MEG001", "MEG002"])
        rank_payload = json.loads(
            (output_dir / "resolved-rank.json").read_text(encoding="utf-8")
        )
        self.assertEqual(rank_payload["rank"], {"mag": 2})
        self.assertEqual(rank_payload["channels"], ["MEG001", "MEG002"])

    def test_epoch_noise_covariance_uses_target_rank_without_lcmv_output(self):
        output_dir = self.root / "epoch_noise"
        covariance_config = {
            "rank_policy": "auto",
            "task_type": "resting",
            "resting": {"fixed_length_duration": 1.0},
            "epochs": {
                "event_id": 1,
                "tmin": 0.0,
                "tmax": 0.5,
                "baseline": None,
                "picks": "meg",
                "preload": True,
                "reject_by_annotation": False,
            },
            "covariance": {"method": "empirical"},
        }

        noise_path, data_path, resolved_rank = compute_covariance.compute_covariances(
            self.target_raw_path,
            self.epochs_path,
            "epochs",
            "",
            output_dir,
            "epochs",
            covariance_config,
            {
                "source_methods": ["dSPM"],
                "data_type": "meg",
                "rank_policy": "auto",
            },
            visualize=False,
        )

        self.assertTrue(noise_path.is_file())
        self.assertIsNone(data_path)
        self.assertEqual(resolved_rank, {"mag": 2})
        self.assertEqual(
            mne.read_cov(noise_path, verbose=False).ch_names,
            ["MEG001", "MEG002", "MEG003"],
        )

    def test_lcmv_raw_and_saved_epochs_use_the_same_common_channel_space(self):
        cases = (
            (
                "raw",
                self.target_raw_path,
                {
                    "source_methods": ["LCMV"],
                    "data_type": "meg",
                    "rank_policy": "auto",
                    "LCMV": {
                        "n_rank": 2,
                        "data_covariance": {"method": "empirical"},
                        "make_lcmv": {},
                    },
                },
            ),
            (
                "epochs",
                self.epochs_path,
                {
                    "source_methods": ["LCMV"],
                    "data_type": "meg",
                    "rank_policy": "auto",
                    "LCMV": {
                        "data_covariance": {
                            "method": "empirical",
                            "rank": {"mag": 2},
                        },
                        "make_lcmv": {},
                    },
                },
            ),
        )

        for data_mode, source_path, source_config in cases:
            with self.subTest(data_mode=data_mode):
                output_dir = self.root / f"lcmv_{data_mode}"
                noise_path, data_path, resolved_rank = compute_covariance.compute_covariances(
                    self.noise_raw_path,
                    source_path,
                    data_mode,
                    "",
                    output_dir,
                    "raw",
                    self.covariance_config,
                    source_config,
                    visualize=False,
                )

                self.assertTrue(noise_path.is_file())
                self.assertTrue(data_path.is_file())
                self.assertEqual(resolved_rank, {"mag": 2})
                self.assertEqual(
                    mne.read_cov(noise_path, verbose=False).ch_names,
                    ["MEG001", "MEG002"],
                )
                self.assertEqual(
                    mne.read_cov(data_path, verbose=False).ch_names,
                    ["MEG001", "MEG002"],
                )

    def test_raw_noise_must_support_the_target_rank(self):
        raw = low_rank_raw(("MEG001", "MEG002"))
        one_component = raw.get_data()[0]
        noise = mne.io.RawArray(
            np.vstack([one_component, one_component]), raw.info.copy(), verbose=False
        )
        insufficient_noise_path = self.root / "insufficient_noise_raw.fif"
        noise.save(insufficient_noise_path, overwrite=True, verbose=False)

        with self.assertRaisesRegex(
            compute_covariance.CovarianceConfigurationError,
            "cannot support the target rank",
        ):
            compute_covariance.compute_covariances(
                insufficient_noise_path,
                self.target_raw_path,
                "raw",
                "",
                self.root / "insufficient",
                "raw",
                self.covariance_config,
                {
                    "source_methods": ["dSPM"],
                    "data_type": "meg",
                    "rank_policy": "auto",
                },
                visualize=False,
            )


class SourceContractTests(unittest.TestCase):
    def test_lcmv_requires_precomputed_data_covariance(self):
        config = {
            "spacing": "ico4",
            "epoch_label": "event",
            "source_methods": ["LCMV"],
            "data_type": "meg",
        }
        with self.assertRaisesRegex(
            source_localization.SourceConfigurationError,
            "data_covariance_file",
        ):
            source_localization.process_subject(
                "/epochs/sub-01/sub-01-epo.fif",
                "/subjects",
                None,
                None,
                "/output",
                config,
                False,
                noise_covariance_file="/cov/bl-cov.fif",
                forward_file="/fwd/event_ico4-fwd.fif",
            )

    def test_resolved_rank_artifact_requires_exact_channel_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rank_file = Path(temp_dir) / "resolved-rank.json"
            rank_file.write_text(
                json.dumps(
                    {
                        "rank": {"mag": 2},
                        "channels": ["MEG001", "MEG002"],
                        "source_data_mode": "epochs",
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                source_localization.load_resolved_rank(
                    rank_file, ["MEG001", "MEG002"], "epochs"
                ),
                {"mag": 2},
            )
            with self.assertRaisesRegex(
                source_localization.SourceConfigurationError,
                "channels/order",
            ):
                source_localization.load_resolved_rank(
                    rank_file, ["MEG002", "MEG001"], "epochs"
                )
            with self.assertRaisesRegex(
                source_localization.SourceConfigurationError,
                "source mode",
            ):
                source_localization.load_resolved_rank(
                    rank_file, ["MEG001", "MEG002"], "raw"
                )

    def test_lcmv_covariance_channel_order_mismatch_fails_before_solver(self):
        raw = low_rank_raw(("MEG001", "MEG002"))
        noise_cov = mne.Covariance(
            np.eye(2), ["MEG001", "MEG002"], [], [], nfree=10
        )
        data_cov = mne.Covariance(
            np.eye(2), ["MEG002", "MEG001"], [], [], nfree=10
        )
        forward = {"info": {"ch_names": ["MEG001", "MEG002"]}}

        with mock.patch.object(
            source_localization.mne,
            "pick_channels_forward",
            return_value=forward,
        ), mock.patch.object(
            source_localization.mne,
            "pick_channels_cov",
            side_effect=lambda covariance, **kwargs: covariance,
        ):
            with self.assertRaisesRegex(
                source_localization.SourceConfigurationError,
                "channels/order",
            ):
                source_localization._align_source_inputs(
                    raw, forward, noise_cov, data_cov
                )

    def test_epochs_lcmv_consumes_routed_data_covariance(self):
        epochs = mne.EpochsArray(
            low_rank_raw().get_data()[None, :, :100],
            low_rank_raw().info,
            tmin=0.0,
            verbose=False,
        )
        noise_cov = object()
        data_cov = object()
        forward = object()
        config = {
            "spacing": "ico4",
            "epoch_label": "event",
            "source_methods": ["LCMV"],
            "data_type": "meg",
            "rank_policy": "auto",
            "LCMV": {"make_lcmv": {}},
        }

        with mock.patch.object(
            source_localization.mne,
            "read_cov",
            side_effect=[noise_cov, data_cov],
        ) as read_cov, mock.patch.object(
            source_localization.mne,
            "read_epochs",
            return_value=epochs,
        ), mock.patch.object(
            source_localization.mne,
            "read_forward_solution",
            return_value=forward,
        ), mock.patch.object(
            source_localization,
            "_align_source_inputs",
            return_value=(epochs, forward, noise_cov, data_cov),
        ), mock.patch.object(
            source_localization,
            "load_resolved_rank",
            return_value={"mag": 2},
        ) as load_rank, mock.patch.object(
            source_localization,
            "resolve_rank_policy",
        ) as resolve_rank, mock.patch.object(
            source_localization,
            "compute_LCMV",
        ) as compute_lcmv:
            source_localization.process_subject(
                "/epochs/sub-01/sub-01-epo.fif",
                "/subjects",
                None,
                None,
                "/output",
                config,
                False,
                noise_covariance_file="/cov/bl-cov.fif",
                data_covariance_file="/cov/lcmv-data-cov.fif",
                resolved_rank_file="/cov/resolved-rank.json",
                forward_file="/fwd/event_ico4-fwd.fif",
            )

        self.assertEqual(read_cov.call_count, 2)
        load_rank.assert_called_once_with(
            "/cov/resolved-rank.json", epochs.ch_names, "epochs"
        )
        resolve_rank.assert_not_called()
        self.assertIs(compute_lcmv.call_args.args[2], data_cov)
        self.assertEqual(compute_lcmv.call_args.args[-1], {"mag": 2})

    def test_raw_lcmv_consumes_routed_data_covariance(self):
        raw = low_rank_raw(("MEG001", "MEG002"))
        noise_cov = object()
        data_cov = object()
        forward = object()
        filters = object()
        stc = mock.Mock()
        config = {
            "spacing": "ico4",
            "epoch_label": "continuous",
            "source_methods": ["LCMV"],
            "data_type": "meg",
            "rank_policy": "auto",
            "LCMV": {"make_lcmv": {}},
        }

        with mock.patch.object(
            source_localization.mne,
            "read_cov",
            side_effect=[noise_cov, data_cov],
        ) as read_cov, mock.patch.object(
            source_localization.mne.io,
            "read_raw_fif",
            return_value=raw,
        ), mock.patch.object(
            source_localization.mne,
            "read_forward_solution",
            return_value=forward,
        ), mock.patch.object(
            source_localization,
            "_align_source_inputs",
            return_value=(raw, forward, noise_cov, data_cov),
        ), mock.patch.object(
            source_localization,
            "resolve_rank_policy",
            return_value={"mag": 2},
        ), mock.patch.object(
            source_localization,
            "make_lcmv",
            return_value=filters,
        ) as make_lcmv, mock.patch.object(
            source_localization,
            "apply_lcmv_raw",
            return_value=stc,
        ):
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

        self.assertEqual(read_cov.call_count, 2)
        self.assertIs(make_lcmv.call_args.args[2], data_cov)
        self.assertIs(make_lcmv.call_args.kwargs["noise_cov"], noise_cov)
        self.assertEqual(make_lcmv.call_args.kwargs["rank"], {"mag": 2})
        stc.save.assert_called_once()

    def test_dspm_does_not_read_lcmv_data_covariance(self):
        epochs = mne.EpochsArray(
            low_rank_raw().get_data()[None, :, :100],
            low_rank_raw().info,
            tmin=0.0,
            verbose=False,
        )
        noise_cov = object()
        forward = object()
        config = {
            "spacing": "ico4",
            "epoch_label": "event",
            "source_methods": ["dSPM"],
            "data_type": "meg",
            "rank_policy": "auto",
            "dSPM": {"inverse_operator": {}, "apply_inverse": {}},
        }

        with mock.patch.object(
            source_localization.mne,
            "read_cov",
            return_value=noise_cov,
        ) as read_cov, mock.patch.object(
            source_localization.mne,
            "read_epochs",
            return_value=epochs,
        ), mock.patch.object(
            source_localization.mne,
            "read_forward_solution",
            return_value=forward,
        ), mock.patch.object(
            source_localization,
            "_align_source_inputs",
            return_value=(epochs, forward, noise_cov, None),
        ), mock.patch.object(
            source_localization,
            "resolve_rank_policy",
            return_value={"mag": 2},
        ), mock.patch.object(
            source_localization,
            "compute_minimum_norm",
        ) as compute_minimum_norm:
            source_localization.process_subject(
                "/epochs/sub-01/sub-01-epo.fif",
                "/subjects",
                None,
                None,
                "/output",
                config,
                False,
                noise_covariance_file="/cov/bl-cov.fif",
                forward_file="/fwd/event_ico4-fwd.fif",
            )

        read_cov.assert_called_once()
        compute_minimum_norm.assert_called_once()


if __name__ == "__main__":
    unittest.main()
