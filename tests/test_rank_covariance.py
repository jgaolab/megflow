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
import source_localization
import utils
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


class CovarianceVisualizationTests(unittest.TestCase):
    def test_plotting_preserves_diagonal_and_dense_covariances(self):
        info = mne.create_info(
            ["MEG0111", "MEG0121", "MEG0112", "MEG0122"],
            100.0,
            ["mag", "mag", "grad", "grad"],
        )
        diagonal = mne.make_ad_hoc_cov(info)
        dense = diagonal.copy()
        dense["data"] = np.diag(diagonal.data)
        dense["diag"] = False
        dense["data"][0, 1] = dense["data"][1, 0] = dense.data[0, 0] * 0.1

        for name, covariance in (("diagonal", diagonal), ("dense", dense)):
            with self.subTest(covariance=name), tempfile.TemporaryDirectory() as tmp:
                original = covariance.copy()
                with mock.patch.object(
                    compute_covariance.mne.viz,
                    "plot_cov",
                    wraps=mne.viz.plot_cov,
                ) as plot_cov:
                    compute_covariance._visualize_covariance(
                        covariance, info, tmp, name
                    )

                plotted = plot_cov.call_args.args[0]
                expected = np.diag(original.data) if original["diag"] else original.data
                np.testing.assert_array_equal(plotted.data, expected)
                self.assertFalse(plotted["diag"])
                self.assertEqual(plotted.ch_names, original.ch_names)
                np.testing.assert_array_equal(covariance.data, original.data)
                self.assertEqual(covariance["diag"], original["diag"])
                self.assertEqual(covariance.ch_names, original.ch_names)
                for filename in (f"{name}.png", f"{name}_spectra.png"):
                    self.assertGreater((Path(tmp) / filename).stat().st_size, 0)


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

    def test_none_mode_skips_only_noise_covariance(self):
        output_dir = self.root / "no_noise"
        source_config = {
            "source_methods": ["LCMV"],
            "data_type": "mag",
            "rank_policy": "auto",
            "LCMV": {
                "data_covariance": {
                    "method": "empirical",
                    "reject_by_annotation": True,
                },
                "make_lcmv": {},
            },
        }

        with mock.patch.object(
            compute_covariance,
            "_prepare_noise_input",
        ) as prepare_noise, mock.patch.object(
            compute_covariance.mne,
            "make_ad_hoc_cov",
        ) as make_ad_hoc:
            noise_path, data_path, resolved_rank = (
                compute_covariance.compute_covariances(
                    noise_data_file=None,
                    source_data_file=self.target_raw_path,
                    source_data_mode="raw",
                    events_file="",
                    output_dir=output_dir,
                    noise_covariance_mode="none",
                    covariance_config={"rank_policy": "auto"},
                    source_config=source_config,
                    visualize=False,
                )
            )

        prepare_noise.assert_not_called()
        make_ad_hoc.assert_not_called()
        self.assertIsNone(noise_path)
        self.assertTrue(data_path.is_file())
        self.assertEqual(resolved_rank, {"mag": 2})
        self.assertFalse((output_dir / "bl-cov.fif").exists())
        self.assertFalse((output_dir / "noise-cov.fif").exists())
        metadata = json.loads(
            (output_dir / "covariance-metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["noise_covariance_mode"], "none")
        self.assertIsNone(metadata["noise_covariance_file"])
        self.assertEqual(metadata["data_covariance_file"], "lcmv-data-cov.fif")

    def test_none_mode_rejects_additional_source_methods_before_loading_data(self):
        with mock.patch.object(
            compute_covariance, "_read_target_source"
        ) as read_target:
            with self.assertRaisesRegex(
                compute_covariance.CovarianceConfigurationError,
                "source_methods=\\['LCMV'\\]",
            ):
                compute_covariance.compute_covariances(
                    noise_data_file=None,
                    source_data_file=self.target_raw_path,
                    source_data_mode="raw",
                    events_file="",
                    output_dir=self.root / "none_with_dspm",
                    noise_covariance_mode="none",
                    covariance_config={"rank_policy": "auto"},
                    source_config={
                        "source_methods": ["LCMV", "dSPM"],
                        "data_type": "mag",
                        "LCMV": {"data_covariance": {"method": "empirical"}},
                    },
                    visualize=False,
                )

        read_target.assert_not_called()

    def test_none_mode_rejects_mixed_sensor_types_before_data_covariance(self):
        info = mne.create_info(
            ["MEG0111", "MEG0112"],
            100.0,
            ["mag", "grad"],
        )
        data = np.random.default_rng(22).standard_normal((2, 600)) * 1e-12
        mixed_raw = mne.io.RawArray(data, info, verbose=False)
        mixed_path = self.root / "mixed_none_raw.fif"
        mixed_raw.save(mixed_path, overwrite=True, verbose=False)

        with mock.patch.object(
            compute_covariance.mne, "compute_raw_covariance"
        ) as compute_data_covariance:
            with self.assertRaisesRegex(
                compute_covariance.CovarianceConfigurationError,
                "single sensor type",
            ):
                compute_covariance.compute_covariances(
                    noise_data_file=None,
                    source_data_file=mixed_path,
                    source_data_mode="raw",
                    events_file="",
                    output_dir=self.root / "mixed_none",
                    noise_covariance_mode="none",
                    covariance_config={"rank_policy": "auto"},
                    source_config={
                        "source_methods": ["LCMV"],
                        "data_type": "meg",
                        "LCMV": {"data_covariance": {"method": "empirical"}},
                    },
                    visualize=False,
                )

        compute_data_covariance.assert_not_called()

    def test_ad_hoc_visualization_completes_covariance_outputs(self):
        for mode, source_path in (
            ("raw", self.target_raw_path),
            ("epochs", self.epochs_path),
        ):
            with self.subTest(source_data_mode=mode):
                output_dir = self.root / f"ad_hoc_visualization_{mode}"
                noise_path, data_path, rank = compute_covariance.compute_covariances(
                    noise_data_file=None,
                    source_data_file=source_path,
                    source_data_mode=mode,
                    events_file="",
                    output_dir=output_dir,
                    noise_covariance_mode="ad_hoc",
                    covariance_config={},
                    source_config={
                        "source_methods": ["LCMV"],
                        "data_type": "meg",
                        "LCMV": {"data_covariance": {"method": "empirical"}},
                    },
                    visualize=True,
                )

                noise = mne.read_cov(noise_path, verbose=False)
                self.assertTrue(noise["diag"])
                self.assertEqual(noise.data.ndim, 1)
                expected = mne.make_ad_hoc_cov(low_rank_raw().info)
                np.testing.assert_array_equal(noise.data, expected.data)
                data = mne.read_cov(data_path, verbose=False)
                self.assertFalse(data["diag"])
                self.assertEqual(data.ch_names, noise.ch_names)
                rank_payload = json.loads((output_dir / "resolved-rank.json").read_text())
                self.assertEqual(rank_payload["rank"], rank)
                self.assertEqual(rank_payload["source_data_mode"], mode)
                metadata = json.loads((output_dir / "covariance-metadata.json").read_text())
                self.assertEqual(metadata["noise_covariance_file"], noise_path.name)
                self.assertEqual(metadata["data_covariance_file"], data_path.name)
                for stem in ("noise_cov", "lcmv_data_cov"):
                    for suffix in (".png", "_spectra.png"):
                        self.assertGreater((output_dir / f"{stem}{suffix}").stat().st_size, 0)

    def test_ad_hoc_mode_uses_selected_target_info(self):
        output_dir = self.root / "ad_hoc"
        info = mne.create_info(
            ["MEG0111", "MEG0112"],
            100.0,
            ["mag", "grad"],
        )
        data = np.random.default_rng(21).standard_normal((2, 600)) * 1e-12
        mixed_raw = mne.io.RawArray(data, info, verbose=False)
        mixed_path = self.root / "mixed_raw.fif"
        mixed_raw.save(mixed_path, overwrite=True, verbose=False)
        source_config = {
            "source_methods": ["LCMV"],
            "data_type": "meg",
            "rank_policy": "auto",
            "LCMV": {
                "data_covariance": {"method": "empirical"},
                "make_lcmv": {},
            },
        }

        with mock.patch.object(
            compute_covariance.mne,
            "make_ad_hoc_cov",
            wraps=mne.make_ad_hoc_cov,
        ) as make_ad_hoc:
            noise_path, data_path, _ = compute_covariance.compute_covariances(
                noise_data_file=None,
                source_data_file=mixed_path,
                source_data_mode="raw",
                events_file="",
                output_dir=output_dir,
                noise_covariance_mode="ad_hoc",
                covariance_config={"make_ad_hoc_cov": {}},
                source_config=source_config,
                visualize=False,
            )

        make_ad_hoc.assert_called_once()
        selected_info = make_ad_hoc.call_args.args[0]
        self.assertEqual(selected_info["ch_names"], ["MEG0111", "MEG0112"])
        self.assertEqual(noise_path.name, "noise-cov.fif")
        self.assertTrue(noise_path.is_file())
        self.assertTrue(data_path.is_file())
        metadata = json.loads(
            (output_dir / "covariance-metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["noise_covariance_mode"], "ad_hoc")
        self.assertEqual(metadata["noise_covariance_file"], "noise-cov.fif")


class SourceCovarianceNumericsTests(unittest.TestCase):
    @staticmethod
    def _synthetic_meg_and_forward():
        channel_types = ["mag", "grad"] * 6
        info = mne.create_info(
            [f"MEG{index:03}" for index in range(12)], 100.0, channel_types
        )
        for index, channel in enumerate(info["chs"]):
            angle = 2 * np.pi * index / 12
            z = 0.3 + 0.3 * (index % 2)
            normal = np.array([
                np.sqrt(1 - z * z) * np.cos(angle),
                np.sqrt(1 - z * z) * np.sin(angle),
                z,
            ])
            tangent = np.cross([0.0, 0.0, 1.0], normal)
            tangent /= np.linalg.norm(tangent)
            channel["loc"][:] = np.concatenate(
                [0.12 * normal, tangent, np.cross(normal, tangent), normal]
            )
        src = mne.setup_volume_source_space(pos={
            "rr": np.array([[0.02, 0.01, 0.02], [-0.02, 0.015, 0.025]]),
            "nn": np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]]),
        })
        sphere = mne.make_sphere_model(r0=(0.0, 0.0, 0.0), head_radius=None)
        forward = mne.make_forward_solution(
            info, trans=None, src=src, bem=sphere, eeg=False, mindist=0.0, n_jobs=1
        )
        scales = np.array([
            1e-13 if channel_type == "mag" else 1e-11
            for channel_type in channel_types
        ])
        data = np.random.default_rng(21).standard_normal((12, 300)) * scales[:, None]
        return mne.io.RawArray(data, info, verbose=False), forward

    def test_fif_covariance_alignment_supports_real_whitening(self):
        info = mne.create_info(
            ["MEG0111", "MEG0112", "MEG0121", "MEG0122"],
            100.0,
            ["mag", "grad", "mag", "grad"],
        )
        raw = mne.io.RawArray(np.zeros((4, 100)), info, verbose=False)
        diagonal = mne.make_ad_hoc_cov(info)
        dense = diagonal.copy()
        dense["data"] = np.diag(diagonal.data)
        dense["diag"] = False
        dense["data"][0, 2] = dense["data"][2, 0] = dense.data[0, 0] * 0.1
        forward = {"info": info}

        with tempfile.TemporaryDirectory() as tmp:
            for name, original in (("diagonal", diagonal), ("dense", dense)):
                with self.subTest(covariance=name):
                    path = Path(tmp) / f"{name}-cov.fif"
                    original.save(path, overwrite=True)
                    loaded = mne.read_cov(path)
                    before = loaded.copy()
                    data_cov = dense.copy()
                    non_native = ">f8" if np.little_endian else "<f8"
                    data_cov["data"] = data_cov.data.astype(non_native)
                    with mock.patch.object(
                        source_localization.mne,
                        "pick_channels_forward",
                        return_value=forward,
                    ):
                        _, _, noise, data = source_localization._align_source_inputs(
                            raw.copy(), forward, loaded, data_cov
                        )

                    # Exercise the MNE eigensolver, not a mocked source call.
                    for rank in ({"meg": 4}, {"meg": 3}):
                        actual, names = mne.cov.compute_whitener(noise, info, rank=rank)
                        expected, _ = mne.cov.compute_whitener(original, info, rank=rank)
                        np.testing.assert_allclose(actual, expected)
                        self.assertTrue(np.isfinite(actual).all())
                        self.assertEqual(names, info["ch_names"])
                    self.assertTrue(noise.data.dtype.isnative)
                    self.assertTrue(data.data.dtype.isnative)
                    np.testing.assert_array_equal(noise.data, before.data)
                    np.testing.assert_array_equal(data.data, data_cov.data)
                    self.assertEqual(noise["diag"], before["diag"])
                    self.assertEqual(noise["nfree"], before["nfree"])
                    self.assertEqual(loaded.data.dtype, before.data.dtype)
                    np.testing.assert_array_equal(loaded.data, before.data)
                    self.assertFalse(data_cov.data.dtype.isnative)
                    np.testing.assert_array_equal(mne.read_cov(path).data, before.data)

    def test_covariance_alignment_keeps_none_noise(self):
        raw = low_rank_raw()
        forward = {"info": raw.info}
        data_cov = mne.compute_raw_covariance(raw, method="empirical")
        non_native = ">f8" if np.little_endian else "<f8"
        data_cov["data"] = data_cov.data.astype(non_native)
        with mock.patch.object(
            source_localization.mne, "pick_channels_forward", return_value=forward
        ):
            _, _, noise, data = source_localization._align_source_inputs(
                raw, forward, None, data_cov
            )

        self.assertIsNone(noise)
        self.assertTrue(data.data.dtype.isnative)
        np.testing.assert_array_equal(data.data, data_cov.data)

    def test_zero_imaginary_lcmv_filters_keep_raw_and_evoked_stc_real(self):
        raw, forward = self._synthetic_meg_and_forward()
        data_cov = mne.compute_raw_covariance(raw, method="empirical")
        noise_cov = mne.make_ad_hoc_cov(raw.info)
        real_eig = np.linalg.eig

        def complex_dtype_eig(matrix):
            values, vectors = real_eig(matrix)
            # A complex, unselected eigenpair promotes the whole batched array.
            return values.astype(complex), vectors.astype(complex)

        config = {
            "source_methods": ["LCMV"], "data_type": "meg",
            "epoch_label": "test", "spacing": "test",
            "LCMV": {"make_lcmv": {
                "reg": 0.05, "depth": 0.8, "pick_ori": "max-power",
                "weight_norm": "unit-noise-gain-invariant", "reduce_rank": True,
            }},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_path = root / "sub-01_raw.fif"
            forward_path = root / "test-fwd.fif"
            noise_path = root / "noise-cov.fif"
            data_path = root / "data-cov.fif"
            raw.save(raw_path, overwrite=True)
            mne.write_forward_solution(forward_path, forward, overwrite=True)
            noise_cov.save(noise_path, overwrite=True)
            data_cov.save(data_path, overwrite=True)
            for mode in ("raw", "evoked"):
                with self.subTest(mode=mode), mock.patch.object(
                    np.linalg, "eig", side_effect=complex_dtype_eig
                ) as eig:
                    if mode == "raw":
                        source_localization.process_raw(
                            raw_path, root, None, None, root, config, False,
                            noise_covariance_file=noise_path,
                            forward_file=forward_path, data_covariance_file=data_path,
                            noise_covariance_mode="ad_hoc",
                        )
                    else:
                        evoked = mne.EvokedArray(raw.get_data(), raw.info)
                        source_localization.compute_LCMV(
                            evoked, forward, data_cov, noise_cov, root, "sub-01",
                            root, "test", "test", config, False, {"meg": 12},
                            noise_covariance_mode="ad_hoc",
                        )
                    eig.assert_called_once()
                    stc = mne.read_source_estimate(
                        str(root / f"test_{mode}_LCMV-test-vl.stc")
                    )
                    self.assertFalse(np.iscomplexobj(stc.data))
                    self.assertTrue(np.isfinite(stc.data).all())
                    self.assertGreater(np.abs(stc.data).max(), 0)

    def test_real_lcmv_filter_validation_is_lossless_and_rejects_nonzero_imaginary(self):
        original = np.array([[np.pi, -np.e], [1.123456789012345, 4.987654321098765]])
        orientations = np.array([[np.pi, -np.e, np.sqrt(2)]] * 2)
        for dtype in (np.float32, np.float64, np.complex64, np.complex128):
            with self.subTest(dtype=dtype):
                filters = {
                    "weights": original.astype(dtype),
                    "max_power_ori": orientations.astype(dtype),
                    "rank": 2,
                }
                expected = {key: filters[key].real.copy() for key in (
                    "weights", "max_power_ori"
                )}
                utils.ensure_real_lcmv_filters(filters)
                for key, values in expected.items():
                    np.testing.assert_array_equal(filters[key], values)
                    self.assertEqual(filters[key].dtype, values.dtype)
                self.assertEqual(filters["rank"], 2)

        for key in ("weights", "max_power_ori"):
            for invalid in (1j, 1e-30j, complex(0, np.nan), complex(np.inf, 0)):
                with self.subTest(key=key, invalid=invalid):
                    filters = {
                        "weights": original.astype(complex),
                        "max_power_ori": np.ones((2, 3), dtype=complex),
                    }
                    filters[key][0, 0] = invalid
                    with self.assertRaisesRegex(ValueError, "LCMV.*" + key):
                        utils.ensure_real_lcmv_filters(filters)
                    self.assertTrue(np.iscomplexobj(filters["weights"]))
        filters = {"weights": original, "max_power_ori": None}
        utils.ensure_real_lcmv_filters(filters)
        self.assertIs(filters["weights"], original)
        self.assertIsNone(filters["max_power_ori"])

    def test_fif_round_trip_runs_real_raw_and_epochs_source_solvers(self):
        raw, forward = self._synthetic_meg_and_forward()
        events = np.column_stack([
            [0, 75, 150, 225], np.zeros(4, dtype=int), np.ones(4, dtype=int)
        ])
        epochs = mne.Epochs(
            raw, events, tmin=0.0, tmax=0.49, baseline=None, preload=True
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_path = root / "sub-01_raw.fif"
            epochs_path = root / "sub-01-epo.fif"
            forward_path = root / "test-fwd.fif"
            raw.save(raw_path, overwrite=True)
            epochs.save(epochs_path, overwrite=True)
            mne.write_forward_solution(forward_path, forward, overwrite=True)
            for mode in ("raw", "epochs"):
                for noise_mode in ("ad_hoc", "raw"):
                    for method in ("LCMV", "dSPM"):
                        with self.subTest(mode=mode, noise_mode=noise_mode, method=method):
                            config = {
                                "source_methods": [method],
                                "data_type": "meg",
                                "rank_policy": "auto",
                                "epoch_label": "test",
                                "spacing": "test",
                                "LCMV": {
                                    "data_covariance": {"method": "empirical"},
                                    "make_lcmv": {
                                        "reg": 0.05,
                                        "depth": 0.8,
                                        "pick_ori": "max-power",
                                        "weight_norm": "unit-noise-gain-invariant",
                                        # Spherical MEG lead fields have a null radial direction.
                                        "reduce_rank": True,
                                    },
                                    "apply_lcmv_raw": {"start": None, "stop": None},
                                },
                                "dSPM": {
                                    "inverse_operator": {"loose": 1.0, "depth": 0.8},
                                    "apply_inverse": {"lambda2": 1.0 / 9.0},
                                },
                            }
                            output = root / f"{mode}_{noise_mode}_{method}"
                            covariance_dir = output / "covariance"
                            source_path = raw_path if mode == "raw" else epochs_path
                            noise_path, data_path, _ = compute_covariance.compute_covariances(
                                noise_data_file=raw_path if noise_mode == "raw" else None,
                                source_data_file=source_path,
                                source_data_mode=mode,
                                events_file="",
                                output_dir=covariance_dir,
                                noise_covariance_mode=noise_mode,
                                covariance_config={
                                    "compute_raw_covariance": {"method": "empirical"}
                                },
                                source_config=config,
                                visualize=False,
                            )
                            noise_bytes = noise_path.read_bytes()
                            process = (
                                source_localization.process_raw if mode == "raw"
                                else source_localization.process_subject
                            )
                            process(
                                source_path, root, None, None, output, config, False,
                                noise_covariance_file=noise_path,
                                forward_file=forward_path,
                                data_covariance_file=data_path,
                                resolved_rank_file=covariance_dir / "resolved-rank.json",
                                noise_covariance_mode=noise_mode,
                            )
                            label = "raw" if mode == "raw" else "evoked"
                            stc = mne.read_source_estimate(
                                str(output / f"test_{label}_{method}-test-vl.stc")
                            )
                            self.assertEqual(stc.data.shape, (2, 300 if mode == "raw" else 50))
                            self.assertTrue(np.isfinite(stc.data).all())
                            self.assertGreater(np.abs(stc.data).max(), 0)
                            self.assertEqual(noise_path.read_bytes(), noise_bytes)


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

    def test_source_alignment_uses_resolved_rank_channel_contract(self):
        raw = low_rank_raw(("MEG001", "MEG002", "MEG003"))
        noise_cov = mne.Covariance(
            np.eye(2), ["MEG003", "MEG001"], [], [], nfree=10
        )
        data_cov = mne.Covariance(
            np.eye(2), ["MEG003", "MEG001"], [], [], nfree=10
        )
        forward = {"info": {"ch_names": ["MEG001", "MEG002", "MEG003"]}}

        with mock.patch.object(
            source_localization.mne,
            "pick_channels_forward",
            return_value=forward,
        ) as pick_forward, mock.patch.object(
            source_localization.mne,
            "pick_channels_cov",
            side_effect=lambda covariance, **kwargs: covariance,
        ) as pick_cov:
            aligned_raw, _, _, _ = source_localization._align_source_inputs(
                raw,
                forward,
                noise_cov,
                data_cov,
                expected_channels=["MEG003", "MEG001"],
            )

        self.assertEqual(aligned_raw.ch_names, ["MEG003", "MEG001"])
        self.assertEqual(
            pick_forward.call_args.kwargs["include"], ["MEG003", "MEG001"]
        )
        self.assertEqual(pick_cov.call_count, 2)

    def test_lcmv_none_mode_defaults_to_nai_without_overriding_explicit_weight_norm(self):
        default_kwargs, _ = source_localization._lcmv_mne_kwargs(
            {"LCMV": {"make_lcmv": {}}},
            {"mag": 2},
            "raw",
            noise_covariance_mode="none",
        )
        explicit_kwargs, _ = source_localization._lcmv_mne_kwargs(
            {
                "LCMV": {
                    "make_lcmv": {
                        "weight_norm": "unit-noise-gain-invariant"
                    }
                }
            },
            {"mag": 2},
            "raw",
            noise_covariance_mode="none",
        )

        self.assertEqual(default_kwargs["weight_norm"], "nai")
        self.assertEqual(
            explicit_kwargs["weight_norm"], "unit-noise-gain-invariant"
        )

    def test_lcmv_noise_modes_keep_the_existing_default_normalization(self):
        for mode in ("epochs", "raw", "ad_hoc"):
            with self.subTest(mode=mode):
                make_kwargs, _ = source_localization._lcmv_mne_kwargs(
                    {"LCMV": {"make_lcmv": {}}},
                    {"mag": 2},
                    "raw",
                    noise_covariance_mode=mode,
                )
                self.assertEqual(
                    make_kwargs["weight_norm"],
                    "unit-noise-gain-invariant",
                )

    def test_lcmv_make_config_cannot_override_routed_noise_covariance(self):
        with self.assertRaisesRegex(
            source_localization.SourceConfigurationError,
            "noise_cov",
        ):
            source_localization._lcmv_mne_kwargs(
                {"LCMV": {"make_lcmv": {"noise_cov": None}}},
                {"mag": 2},
                "raw",
                noise_covariance_mode="none",
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
            "load_resolved_rank_contract",
            return_value=({"mag": 2}, epochs.ch_names),
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
        load_rank.assert_called_once_with("/cov/resolved-rank.json", "epochs")
        resolve_rank.assert_not_called()
        self.assertIs(compute_lcmv.call_args.args[2], data_cov)
        self.assertEqual(compute_lcmv.call_args.args[-2], {"mag": 2})
        self.assertEqual(compute_lcmv.call_args.args[-1], "epochs")

    def test_raw_lcmv_consumes_routed_data_covariance(self):
        raw = low_rank_raw(("MEG001", "MEG002"))
        noise_cov = object()
        data_cov = object()
        forward = object()
        filters = {"weights": np.ones((2, 3)), "max_power_ori": None}
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

    def test_raw_lcmv_none_mode_reads_only_data_covariance(self):
        raw = low_rank_raw(("MEG001", "MEG002"))
        data_cov = object()
        forward = object()
        filters = {"weights": np.ones((2, 3)), "max_power_ori": None}
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
            return_value=data_cov,
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
            return_value=(raw, forward, None, data_cov),
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
                noise_covariance_mode="none",
                data_covariance_file="/cov/lcmv-data-cov.fif",
                forward_file="/fwd/continuous_ico4-fwd.fif",
            )

        read_cov.assert_called_once_with("/cov/lcmv-data-cov.fif")
        self.assertIsNone(make_lcmv.call_args.kwargs["noise_cov"])
        self.assertEqual(make_lcmv.call_args.kwargs["weight_norm"], "nai")

    def test_raw_lcmv_none_mode_rejects_mixed_meg_sensor_types(self):
        info = mne.create_info(
            ["MEG0111", "MEG0112"], 200.0, ["mag", "grad"]
        )
        raw = mne.io.RawArray(np.zeros((2, 100)), info, verbose=False)
        config = {
            "spacing": "ico4",
            "epoch_label": "continuous",
            "source_methods": ["LCMV"],
            "data_type": "meg",
            "LCMV": {"make_lcmv": {}},
        }

        with mock.patch.object(
            source_localization.mne.io,
            "read_raw_fif",
            return_value=raw,
        ), mock.patch.object(
            source_localization.mne,
            "read_cov",
        ) as read_cov:
            with self.assertRaisesRegex(
                source_localization.SourceConfigurationError,
                "single sensor type",
            ):
                source_localization.process_raw(
                    "/raw/sub-01/sub-01_raw.fif",
                    "/subjects",
                    None,
                    None,
                    "/output",
                    config,
                    False,
                    noise_covariance_mode="none",
                    data_covariance_file="/cov/lcmv-data-cov.fif",
                    forward_file="/fwd/continuous_ico4-fwd.fif",
                )

        read_cov.assert_not_called()

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
