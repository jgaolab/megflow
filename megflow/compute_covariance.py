#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import json
import logging
import os
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
import mne
import yaml

from epochs import _get_epoch_kwargs, prepare_epoching_raw_and_events
from epochs_preproc import prepare_analysis_raw
from utils import (
    MegflowConfigurationError,
    RANK_NOT_SET,
    RankConfigurationError,
    handle_yaml_scientific_notation,
    normalize_source_methods,
    present_sensor_types,
    ranked_mne_kwargs,
    resolve_rank_policy,
    set_random_seed,
    str2bool,
)

mne.viz.set_browser_backend("matplotlib")
set_random_seed(2025)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class CovarianceConfigurationError(MegflowConfigurationError):
    """Raised for deterministic covariance configuration or routing errors."""


NOISE_COVARIANCE_MODES = {"epochs", "raw", "ad_hoc", "none"}


def _mapping(value, config_name):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CovarianceConfigurationError(f"{config_name} must be a mapping.")
    return dict(value)


def _pick_good_data_channels(inst, data_type, label):
    selected = inst.copy().pick(data_type or "meg")
    bads = set(selected.info.get("bads", []))
    good_channels = [name for name in selected.ch_names if name not in bads]
    if not good_channels:
        raise CovarianceConfigurationError(
            f"{label} has no usable {data_type or 'meg'} channels after excluding bad channels."
        )
    selected.pick(good_channels)
    selected.info["bads"] = []
    return selected


def _restrict_to_common_channels(target, noise):
    noise_channels = set(noise.ch_names)
    common_channels = [name for name in target.ch_names if name in noise_channels]
    if not common_channels:
        raise CovarianceConfigurationError(
            "Target and noise inputs have no common good channels after data-type selection."
        )

    missing_from_noise = [name for name in target.ch_names if name not in noise_channels]
    if missing_from_noise:
        logger.warning(
            "Dropping %d target channels absent from the noise input: %s",
            len(missing_from_noise),
            ", ".join(missing_from_noise),
        )
    target.pick(common_channels)
    noise.pick(common_channels)
    if target.ch_names != noise.ch_names:
        raise CovarianceConfigurationError(
            "Target and noise inputs could not be ordered into the same channel space."
        )
    return target, noise, common_channels


def prepare_covariance_epochs(raw, events_file, config):
    """Create baseline epochs with the same Raw/event preparation as epochs.py."""
    raw, events, _ = prepare_epoching_raw_and_events(
        raw,
        config,
        events_file,
        preproc_config={"preproc": config.get("analysis_preproc")},
        preproc_config_name="covariance.analysis_preproc",
    )
    return raw, mne.Epochs(raw=raw, events=events, **_get_epoch_kwargs(config))


def _read_target_source(path, data_mode, source_config):
    if data_mode == "epochs":
        target = mne.read_epochs(path, preload=True)
    elif data_mode == "raw":
        target = mne.io.read_raw_fif(path, preload=True)
    else:
        raise CovarianceConfigurationError(
            f"source.type must be 'raw' or 'epochs'; got {data_mode!r}."
        )
    return _pick_good_data_channels(
        target, source_config.get("data_type", "meg"), "Target source input"
    )


def _prepare_noise_input(
    path, noise_covariance_mode, events_file, covariance_config, data_type
):
    if not path:
        raise CovarianceConfigurationError(
            f"noise_data_file is required when noise_covariance_mode="
            f"{noise_covariance_mode!r}."
        )
    raw = mne.io.read_raw_fif(path, preload=True)
    if noise_covariance_mode == "raw":
        raw, _, _ = prepare_analysis_raw(
            raw,
            {"preproc": covariance_config.get("analysis_preproc")},
            config_name="covariance.analysis_preproc",
        )
        noise = raw
    elif noise_covariance_mode == "epochs":
        raw, noise = prepare_covariance_epochs(raw, events_file, covariance_config)
    else:
        raise CovarianceConfigurationError(
            "Noise data preparation is only valid for empirical raw or epochs "
            f"modes; got {noise_covariance_mode!r}."
        )
    return raw, _pick_good_data_channels(noise, data_type, "Noise covariance input")


def _save_covariance_atomic(covariance, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp_dir:
        temporary_path = Path(temp_dir) / destination.name
        covariance.save(temporary_path, overwrite=True)
        os.replace(temporary_path, destination)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(f"Covariance output was not written correctly: {destination}")


def _save_json_atomic(payload, destination, label):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp_dir:
        temporary_path = Path(temp_dir) / destination.name
        temporary_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary_path, destination)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(f"{label} output was not written correctly: {destination}")


def _save_resolved_rank_atomic(resolved_rank, channels, source_data_mode, destination):
    _save_json_atomic(
        {
            "rank": resolved_rank,
            "channels": list(channels),
            "source_data_mode": source_data_mode,
        },
        destination,
        "Resolved-rank",
    )


def _visualize_covariance(covariance, info, output_dir, stem):
    cov_plot_path = Path(output_dir) / f"{stem}.png"
    spectra_plot_path = Path(output_dir) / f"{stem}_spectra.png"
    fig_cov, fig_spectra = mne.viz.plot_cov(covariance, info, show=False)
    fig_cov.savefig(cov_plot_path)
    fig_spectra.savefig(spectra_plot_path)
    plt.close("all")
    logger.info("Saved covariance diagnostics: %s and %s", cov_plot_path, spectra_plot_path)


def _source_uses_lcmv(source_config):
    if "source_methods" not in source_config:
        return False
    return "LCMV" in normalize_source_methods(source_config["source_methods"])


def _noise_covariance_kwargs(noise_covariance_mode, covariance_config, resolved_rank):
    if noise_covariance_mode == "raw":
        config_name = "covariance.compute_raw_covariance"
        kwargs = _mapping(covariance_config.get("compute_raw_covariance"), config_name)
    else:
        config_name = "covariance.covariance"
        kwargs = _mapping(covariance_config.get("covariance"), config_name)
        for key in (
            "visualize",
            "noise_covariance_mode",
            "raw_covariance_task_id",
            "event_time_shift_sec",
            "compute_raw_covariance",
            "events",
            "epochs",
            "event_source",
            "event_file",
            "find_events",
            "analysis_preproc",
            "rank_policy",
        ):
            kwargs.pop(key, None)
    return ranked_mne_kwargs(kwargs, resolved_rank, config_name)


def _lcmv_data_covariance_kwargs(source_config, resolved_rank):
    lcmv_config = _mapping(source_config.get("LCMV"), "source.LCMV")
    kwargs = _mapping(lcmv_config.get("data_covariance"), "source.LCMV.data_covariance")
    if "cov_tmin" in lcmv_config and "tmin" not in kwargs:
        kwargs["tmin"] = lcmv_config["cov_tmin"]
    if "cov_tmax" in lcmv_config and "tmax" not in kwargs:
        kwargs["tmax"] = lcmv_config["cov_tmax"]
    kwargs.setdefault("method", "auto")
    legacy_rank = lcmv_config.get("n_rank", RANK_NOT_SET)
    return ranked_mne_kwargs(
        kwargs,
        resolved_rank,
        "source.LCMV.data_covariance",
        legacy_rank=legacy_rank,
        legacy_config_name="source.LCMV.n_rank",
    )


def compute_covariances(
    noise_data_file,
    source_data_file,
    source_data_mode,
    events_file,
    output_dir,
    noise_covariance_mode,
    covariance_config,
    source_config,
    visualize=True,
):
    """Compute target rank, conditional noise covariance, and LCMV data covariance."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    resolved_rank_path = output_dir / "resolved-rank.json"
    metadata_path = output_dir / "covariance-metadata.json"
    empirical_noise_path = output_dir / "bl-cov.fif"
    ad_hoc_noise_path = output_dir / "noise-cov.fif"
    data_covariance_path = output_dir / "lcmv-data-cov.fif"
    for stale_path in (
        resolved_rank_path,
        metadata_path,
        empirical_noise_path,
        ad_hoc_noise_path,
        data_covariance_path,
    ):
        stale_path.unlink(missing_ok=True)

    noise_covariance_mode = str(noise_covariance_mode).strip().lower()
    if noise_covariance_mode not in NOISE_COVARIANCE_MODES:
        raise CovarianceConfigurationError(
            "noise_covariance_mode must be one of "
            f"{sorted(NOISE_COVARIANCE_MODES)}; got {noise_covariance_mode!r}."
        )
    data_type = source_config.get("data_type", "meg")
    needs_lcmv = _source_uses_lcmv(source_config)
    if noise_covariance_mode == "none":
        methods = normalize_source_methods(source_config.get("source_methods"))
        if methods != ["LCMV"]:
            raise CovarianceConfigurationError(
                "noise_covariance_mode='none' requires "
                "source.source_methods=['LCMV']; "
                f"received {methods}."
            )

    target = _read_target_source(source_data_file, source_data_mode, source_config)
    if noise_covariance_mode == "none":
        sensor_types = present_sensor_types(target)
        if len(sensor_types) > 1:
            formatted_types = ", ".join(sorted(sensor_types))
            raise CovarianceConfigurationError(
                "noise_covariance_mode='none' requires a single sensor type, but "
                f"the selected source input contains: {formatted_types}. Select "
                "one type with source.data_type or use "
                "noise_covariance_mode='ad_hoc'."
            )
    noise = None
    if noise_covariance_mode in {"raw", "epochs"}:
        _, noise = _prepare_noise_input(
            noise_data_file,
            noise_covariance_mode,
            events_file,
            covariance_config,
            data_type,
        )
        target, noise, common_channels = _restrict_to_common_channels(target, noise)
    else:
        common_channels = list(target.ch_names)

    policy = source_config.get(
        "rank_policy", covariance_config.get("rank_policy", "auto")
    )
    resolved_rank = resolve_rank_policy(target, policy, config_name="rank_policy")
    logger.info(
        "Resolved target rank %s from %s using %d common channels.",
        resolved_rank,
        source_data_file,
        len(common_channels),
    )
    if noise_covariance_mode == "raw":
        noise_empirical_rank = resolve_rank_policy(
            noise, "auto", config_name="raw noise empirical rank"
        )
        logger.info("Empirical rank of the routed raw noise input: %s", noise_empirical_rank)
        if sum(noise_empirical_rank.values()) < sum(resolved_rank.values()):
            raise CovarianceConfigurationError(
                "The routed raw noise input cannot support the target rank: "
                f"target={resolved_rank}, noise={noise_empirical_rank}. Check empty-room "
                "preprocessing, ICA exclusions, and channel matching."
            )

    noise_path = None
    if noise_covariance_mode in {"raw", "epochs"}:
        noise_kwargs = _noise_covariance_kwargs(
            noise_covariance_mode, covariance_config, resolved_rank
        )
        logger.info("Noise covariance rank argument: %s", noise_kwargs.get("rank"))
        if noise_covariance_mode == "raw":
            noise_covariance = mne.compute_raw_covariance(noise, **noise_kwargs)
        else:
            noise_covariance = mne.compute_covariance(noise, **noise_kwargs)
        noise_path = empirical_noise_path
        _save_covariance_atomic(noise_covariance, noise_path)
        if visualize:
            _visualize_covariance(noise_covariance, noise.info, output_dir, "bl_cov")
    elif noise_covariance_mode == "ad_hoc":
        ad_hoc_kwargs = _mapping(
            covariance_config.get("make_ad_hoc_cov"),
            "covariance.make_ad_hoc_cov",
        )
        if "info" in ad_hoc_kwargs:
            raise CovarianceConfigurationError(
                "covariance.make_ad_hoc_cov.info is workflow-owned."
            )
        noise_covariance = mne.make_ad_hoc_cov(target.info, **ad_hoc_kwargs)
        noise_path = ad_hoc_noise_path
        _save_covariance_atomic(noise_covariance, noise_path)
        if visualize:
            _visualize_covariance(
                noise_covariance, target.info, output_dir, "noise_cov"
            )
    else:
        logger.info("Noise covariance mode is none; no noise covariance was computed.")

    if not needs_lcmv:
        _save_resolved_rank_atomic(
            resolved_rank, common_channels, source_data_mode, resolved_rank_path
        )
        _save_json_atomic(
            {
                "channels": common_channels,
                "data_covariance_file": None,
                "noise_covariance_file": noise_path.name if noise_path else None,
                "noise_covariance_mode": noise_covariance_mode,
                "rank": resolved_rank,
                "resolved_rank_file": resolved_rank_path.name,
                "source_data_mode": source_data_mode,
            },
            metadata_path,
            "Covariance metadata",
        )
        logger.info("LCMV is not requested; data covariance was not computed.")
        return noise_path, None, resolved_rank

    data_kwargs = _lcmv_data_covariance_kwargs(source_config, resolved_rank)
    logger.info("LCMV data covariance rank argument: %s", data_kwargs.get("rank"))
    if source_data_mode == "raw":
        data_covariance = mne.compute_raw_covariance(target, **data_kwargs)
    else:
        data_covariance = mne.compute_covariance(target, **data_kwargs)
    _save_covariance_atomic(data_covariance, data_covariance_path)
    if visualize:
        _visualize_covariance(data_covariance, target.info, output_dir, "lcmv_data_cov")
    _save_resolved_rank_atomic(
        resolved_rank, common_channels, source_data_mode, resolved_rank_path
    )
    _save_json_atomic(
        {
            "channels": common_channels,
            "data_covariance_file": data_covariance_path.name,
            "noise_covariance_file": noise_path.name if noise_path else None,
            "noise_covariance_mode": noise_covariance_mode,
            "rank": resolved_rank,
            "resolved_rank_file": resolved_rank_path.name,
            "source_data_mode": source_data_mode,
        },
        metadata_path,
        "Covariance metadata",
    )
    return noise_path, data_covariance_path, resolved_rank


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Compute noise covariance and, when requested, LCMV data covariance."
    )
    parser.add_argument(
        "--noise_data_file",
        "--raw_data_file",
        dest="noise_data_file",
        default="",
        help="Noise input Raw FIF, required only for raw or epochs noise modes.",
    )
    parser.add_argument(
        "--source_data_file",
        required=True,
        help="Exact final Raw or Epochs FIF consumed by source imaging.",
    )
    parser.add_argument(
        "--source_data_mode", choices=["raw", "epochs"], default="raw"
    )
    parser.add_argument("--events_file", default="", help="BIDS events.tsv file.")
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--visualize", type=str2bool, nargs="?", const=True, default=True)
    parser.add_argument(
        "--noise_covariance_mode",
        required=True,
        choices=sorted(NOISE_COVARIANCE_MODES),
    )
    parser.add_argument("--config", default="{}", help="Covariance configuration mapping.")
    parser.add_argument("--source_config", default="{}", help="Source configuration mapping.")
    parser.add_argument("--noise_recording_id", default="", help="Routed noise recording identifier for logs.")
    return parser.parse_args()


def main():
    args = parse_arguments()
    handle_yaml_scientific_notation()
    covariance_config = yaml.safe_load(args.config) or {}
    source_config = yaml.safe_load(args.source_config) or {}
    if not isinstance(covariance_config, dict) or not isinstance(source_config, dict):
        raise CovarianceConfigurationError("--config and --source_config must decode to mappings.")

    if args.noise_recording_id:
        logger.info("Noise covariance input recording: %s", args.noise_recording_id)
    compute_covariances(
        noise_data_file=args.noise_data_file,
        source_data_file=args.source_data_file,
        source_data_mode=args.source_data_mode,
        events_file=args.events_file,
        output_dir=args.output_dir,
        noise_covariance_mode=args.noise_covariance_mode,
        covariance_config=covariance_config,
        source_config=source_config,
        visualize=args.visualize,
    )


if __name__ == "__main__":
    try:
        main()
    except (
        MegflowConfigurationError,
        RankConfigurationError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as error:
        logger.error("Covariance configuration or processing error: %s", error)
        raise SystemExit(2) from error
