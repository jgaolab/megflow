#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import logging
import os
from pathlib import Path

import mne
import yaml
from mne.beamformer import apply_lcmv, apply_lcmv_raw, make_lcmv
from mne.minimum_norm import apply_inverse, apply_inverse_raw, make_inverse_operator

from source_visualization import visualize_source_estimate
from utils import (
    MegflowConfigurationError,
    RANK_NOT_SET,
    RankConfigurationError,
    handle_yaml_scientific_notation,
    normalize_mne_rank,
    normalize_source_methods,
    ranked_mne_kwargs,
    resolve_rank_policy,
    set_random_seed,
    str2bool,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

set_random_seed(2025)


class SourceConfigurationError(MegflowConfigurationError):
    """Raised for deterministic source configuration or routing errors."""


def _mapping(value, config_name):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SourceConfigurationError(f"{config_name} must be a mapping.")
    return dict(value)


def _minimum_norm_mne_kwargs(method, config, resolved_rank, data_mode):
    """Resolve direct MNE kwargs for minimum-norm construction and application."""
    method_config = _mapping(config.get(method), f"source.{method}")
    inverse_key = (
        "make_inverse_operator"
        if "make_inverse_operator" in method_config
        else "inverse_operator"
    )
    inverse_kwargs = ranked_mne_kwargs(
        _mapping(method_config.get(inverse_key), f"source.{method}.{inverse_key}"),
        resolved_rank,
        f"source.{method}.{inverse_key}",
    )

    apply_key = "apply_inverse"
    if data_mode == "raw" and "apply_inverse_raw" in method_config:
        apply_key = "apply_inverse_raw"
    apply_kwargs = _mapping(
        method_config.get(apply_key), f"source.{method}.{apply_key}"
    )
    apply_kwargs.setdefault("method", method)
    if data_mode == "raw":
        # apply_inverse has this default, whereas apply_inverse_raw requires it.
        apply_kwargs.setdefault("lambda2", 1.0 / 9.0)
    return inverse_kwargs, apply_kwargs


def _lcmv_mne_kwargs(config, resolved_rank, data_mode):
    """Resolve direct MNE kwargs for LCMV filter construction and application."""
    lcmv_config = _mapping(config.get("LCMV"), "source.LCMV")
    legacy_rank = lcmv_config.get("n_rank", RANK_NOT_SET)
    make_kwargs = ranked_mne_kwargs(
        _mapping(lcmv_config.get("make_lcmv"), "source.LCMV.make_lcmv"),
        resolved_rank,
        "source.LCMV.make_lcmv",
        legacy_rank=legacy_rank,
        legacy_config_name="source.LCMV.n_rank",
    )
    apply_key = "apply_lcmv"
    if data_mode == "raw" and "apply_lcmv_raw" in lcmv_config:
        apply_key = "apply_lcmv_raw"
    apply_kwargs = _mapping(
        lcmv_config.get(apply_key), f"source.LCMV.{apply_key}"
    )
    return make_kwargs, apply_kwargs


def _pick_source_data(inst, data_type):
    selected = inst.copy().pick(data_type or "meg")
    bads = set(selected.info.get("bads", []))
    good_channels = [name for name in selected.ch_names if name not in bads]
    if not good_channels:
        raise SourceConfigurationError(
            f"Source input has no usable {data_type or 'meg'} channels."
        )
    selected.pick(good_channels)
    selected.info["bads"] = []
    return selected


def _covariance_channel_names(covariance):
    names = getattr(covariance, "ch_names", None)
    if names is None:
        names = covariance.get("names", [])
    return list(names)


def _align_source_inputs(inst, fwd, noise_cov, data_cov=None):
    """Restrict source inputs to the ordered noise-covariance channel contract."""
    noise_channels = _covariance_channel_names(noise_cov)
    if not noise_channels:
        raise SourceConfigurationError("Noise covariance contains no channels.")

    missing_data = [name for name in noise_channels if name not in inst.ch_names]
    if missing_data:
        raise SourceConfigurationError(
            "Noise covariance contains channels absent from the target source input: "
            + ", ".join(missing_data)
        )
    inst.pick(noise_channels)
    if inst.ch_names != noise_channels:
        raise SourceConfigurationError(
            "Target source input could not be ordered like the noise covariance."
        )

    forward_channels = set(fwd["info"]["ch_names"])
    missing_forward = [name for name in noise_channels if name not in forward_channels]
    if missing_forward:
        raise SourceConfigurationError(
            "Noise covariance contains channels absent from the forward solution: "
            + ", ".join(missing_forward)
        )
    fwd = mne.pick_channels_forward(
        fwd, include=noise_channels, ordered=True, copy=True
    )
    noise_cov = mne.pick_channels_cov(
        noise_cov, include=noise_channels, ordered=True, copy=True
    )

    if data_cov is not None:
        data_channels = _covariance_channel_names(data_cov)
        if data_channels != noise_channels:
            raise SourceConfigurationError(
                "LCMV data covariance channels/order do not match the noise covariance. "
                f"noise={noise_channels}, data={data_channels}"
            )
        data_cov = mne.pick_channels_cov(
            data_cov, include=noise_channels, ordered=True, copy=True
        )
    return inst, fwd, noise_cov, data_cov


def load_resolved_rank(
    resolved_rank_file, expected_channels, expected_source_data_mode=None
):
    """Load and validate the rank artifact produced by compute_covariance.py."""
    try:
        payload = json.loads(Path(resolved_rank_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SourceConfigurationError(
            f"Could not read resolved rank from {resolved_rank_file}: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise SourceConfigurationError("resolved-rank.json must contain a JSON object.")

    channels = payload.get("channels")
    if channels != list(expected_channels):
        raise SourceConfigurationError(
            "Resolved-rank channels/order do not match the aligned source inputs. "
            f"rank={channels}, source={list(expected_channels)}"
        )
    source_data_mode = payload.get("source_data_mode")
    if (
        expected_source_data_mode is not None
        and source_data_mode != expected_source_data_mode
    ):
        raise SourceConfigurationError(
            "Resolved-rank source mode does not match the source input. "
            f"rank={source_data_mode!r}, source={expected_source_data_mode!r}"
        )
    resolved_rank = normalize_mne_rank(
        payload.get("rank"), config_name="resolved-rank.json.rank"
    )
    if not isinstance(resolved_rank, dict):
        raise SourceConfigurationError(
            "resolved-rank.json.rank must be an explicit rank dictionary."
        )
    return resolved_rank



def compute_minimum_norm(
    method,
    evoked,
    fwd,
    noise_cov,
    subj_src_path,
    subject_id,
    subjects_dir,
    epoch_label,
    spacing,
    config,
    visualize,
    resolved_rank,
):
    """
    Compute the minimum-norm inverse solution and save the results.

    Parameters
    ----------
    method: str
        minimum-norm inverse solution, “MNE” | “dSPM” | “sLORETA” | “eLORETA”
    evoked : instance of Evoked
        The averaged evoked data.
    fwd : instance of Forward
        The forward solution.
    noise_cov : instance of Covariance
        The noise covariance matrix.
    subj_src_path : str
        The directory path to save the results.
    subject_id : str
        The subject identifier.
    subjects_dir : str or Path
        The FreeSurfer subjects directory.
    epoch_label : str
        The epoch label.
    spacing : str
        The source space resolution.
    config : dict
        The configuration dictionary with parameters for processing.
    visualize : bool
        plot source imaging.
    Returns
    -------
    None
    """
    stc_file = os.path.join(subj_src_path, f"{epoch_label}_evoked_{method}-{spacing}")
    inverse_kwargs, apply_kwargs = _minimum_norm_mne_kwargs(
        method, config, resolved_rank, "epochs"
    )
    logger.info("%s inverse rank argument: %s", method, inverse_kwargs.get("rank"))
    inverse_operator = make_inverse_operator(
        info=evoked.info, forward=fwd, noise_cov=noise_cov, **inverse_kwargs
    )
    stc = apply_inverse(evoked, inverse_operator, **apply_kwargs)
    stc.save(stc_file, overwrite=True)

    if visualize:
        visualize_source_estimate(stc, subject_id, subjects_dir, subj_src_path, epoch_label, method, spacing, config, block=False)


def compute_LCMV(
    evoked,
    fwd,
    data_cov,
    noise_cov,
    subj_src_path,
    subject_id,
    subjects_dir,
    epoch_label,
    spacing,
    config,
    visualize,
    resolved_rank,
):
    """
    Compute the LCMV beamformer solution and save the results.

    Parameters
    ----------
    evoked : instance of Evoked
        The averaged evoked data.
    fwd : instance of Forward
        The forward solution.
    data_cov : instance of Covariance
        The data covariance matrix.
    noise_cov : instance of Covariance
        The noise covariance matrix.
    subj_src_path : str
        The directory path to save the results.
    subject_id : str
        The subject identifier.
    subjects_dir : str or Path
        The FreeSurfer subjects directory.
    epoch_label : str
        The epoch label.
    spacing : str
        The source space resolution.
    config : dict
        The configuration dictionary with parameters for processing.
    visualize : bool
        plot source imaging.
    Returns
    -------
    None
    """
    stc_file = os.path.join(subj_src_path, f"{epoch_label}_evoked_LCMV-{spacing}")
    make_lcmv_kwargs, apply_lcmv_kwargs = _lcmv_mne_kwargs(
        config, resolved_rank, "epochs"
    )
    logger.info("LCMV beamformer rank argument: %s", make_lcmv_kwargs.get("rank"))
    filters = make_lcmv(
        evoked.info,
        fwd,
        data_cov,
        noise_cov=noise_cov,
        **make_lcmv_kwargs,
    )
    stc = apply_lcmv(evoked, filters, **apply_lcmv_kwargs)
    stc.save(stc_file, overwrite=True)
    if visualize:
        visualize_source_estimate(stc, subject_id, subjects_dir, subj_src_path, epoch_label, "LCMV", spacing, config, block=False)


def resolve_source_input_files(
    data_file,
    epoch_label,
    spacing,
    *,
    noise_covariance_file=None,
    forward_file=None,
    noise_covariance_dir=None,
    forward_dir=None,
):
    """Resolve exact routed files, retaining directory lookup for old callers."""
    recording_id = Path(data_file).parent.name

    if noise_covariance_file:
        resolved_covariance = Path(noise_covariance_file)
    elif noise_covariance_dir:
        resolved_covariance = Path(noise_covariance_dir) / recording_id / "bl-cov.fif"
    else:
        raise SourceConfigurationError(
            "Provide --noise_covariance_file (preferred) or --noise_covariance_dir."
        )

    if forward_file:
        resolved_forward = Path(forward_file)
    elif forward_dir:
        resolved_forward = (
            Path(forward_dir)
            / recording_id
            / f"{epoch_label}_{spacing}-fwd.fif"
        )
    else:
        raise SourceConfigurationError("Provide --forward_file (preferred) or --forward_dir.")

    return resolved_covariance, resolved_forward


def process_subject(
    epoch_file,
    fs_subjects_dir,
    noise_cov_path,
    fwd_dir,
    output_dir,
    config,
    visualize,
    noise_covariance_file=None,
    forward_file=None,
    data_covariance_file=None,
    resolved_rank_file=None,
):
    """Process one epoched recording for source localization."""
    subject_id = Path(epoch_file).stem.split('_')[0]
    epoch_label = config.get("epoch_label", "")
    spacing = config.get('spacing')
    noise_cov_file, resolved_forward_file = resolve_source_input_files(
        epoch_file,
        epoch_label,
        spacing,
        noise_covariance_file=noise_covariance_file,
        forward_file=forward_file,
        noise_covariance_dir=noise_cov_path,
        forward_dir=fwd_dir,
    )

    methods = normalize_source_methods(config.get("source_methods"))
    needs_lcmv = "LCMV" in methods
    if needs_lcmv and not data_covariance_file:
        raise SourceConfigurationError(
            "LCMV requires --data_covariance_file from compute_covariance.py."
        )

    noise_cov = mne.read_cov(noise_cov_file)
    data_cov = mne.read_cov(data_covariance_file) if needs_lcmv else None
    epochs = _pick_source_data(
        mne.read_epochs(epoch_file, preload=True), config.get("data_type", "meg")
    )
    fwd = mne.read_forward_solution(resolved_forward_file)
    epochs, fwd, noise_cov, data_cov = _align_source_inputs(
        epochs, fwd, noise_cov, data_cov
    )
    resolved_rank = (
        load_resolved_rank(resolved_rank_file, epochs.ch_names, "epochs")
        if resolved_rank_file
        else resolve_rank_policy(
            epochs, config.get("rank_policy", "auto"), config_name="rank_policy"
        )
    )
    logger.info("Resolved target rank for source imaging: %s", resolved_rank)
    evoked = epochs.average()

    for method in methods:
        if method in ["MNE", "dSPM", "sLORETA", "eLORETA"]:
            compute_minimum_norm(
                method, evoked, fwd, noise_cov, output_dir, subject_id,
                fs_subjects_dir, epoch_label, spacing, config, visualize,
                resolved_rank,
            )

    if needs_lcmv:
        compute_LCMV(
            evoked, fwd, data_cov, noise_cov, output_dir, subject_id,
            fs_subjects_dir, epoch_label, spacing, config, visualize,
            resolved_rank,
        )


def process_raw(
    raw_file,
    fs_subjects_dir,
    noise_cov_path,
    fwd_dir,
    output_dir,
    config,
    visualize,
    noise_covariance_file=None,
    forward_file=None,
    data_covariance_file=None,
    resolved_rank_file=None,
):
    """Process one continuous recording for source localization."""
    subject_id = Path(raw_file).stem.split('_')[0]
    spacing = config.get('spacing')
    epoch_label = config.get("epoch_label", "")
    noise_cov_file, resolved_forward_file = resolve_source_input_files(
        raw_file,
        epoch_label,
        spacing,
        noise_covariance_file=noise_covariance_file,
        forward_file=forward_file,
        noise_covariance_dir=noise_cov_path,
        forward_dir=fwd_dir,
    )

    methods = normalize_source_methods(config.get("source_methods"))
    needs_lcmv = "LCMV" in methods
    if needs_lcmv and not data_covariance_file:
        raise SourceConfigurationError(
            "LCMV requires --data_covariance_file from compute_covariance.py."
        )

    noise_cov = mne.read_cov(noise_cov_file)
    data_cov = mne.read_cov(data_covariance_file) if needs_lcmv else None
    raw = _pick_source_data(
        mne.io.read_raw_fif(raw_file, preload=True), config.get("data_type", "meg")
    )
    fwd = mne.read_forward_solution(resolved_forward_file)
    raw, fwd, noise_cov, data_cov = _align_source_inputs(
        raw, fwd, noise_cov, data_cov
    )
    resolved_rank = (
        load_resolved_rank(resolved_rank_file, raw.ch_names, "raw")
        if resolved_rank_file
        else resolve_rank_policy(
            raw, config.get("rank_policy", "auto"), config_name="rank_policy"
        )
    )
    logger.info("Resolved target rank for source imaging: %s", resolved_rank)

    for method in methods:
        if method in ["MNE", "dSPM", "sLORETA", "eLORETA"]:
            inverse_kwargs, apply_kwargs = _minimum_norm_mne_kwargs(
                method, config, resolved_rank, "raw"
            )
            logger.info("%s inverse rank argument: %s", method, inverse_kwargs.get("rank"))
            inverse_operator = make_inverse_operator(
                info=raw.info,
                forward=fwd,
                noise_cov=noise_cov,
                **inverse_kwargs,
            )
            stc = apply_inverse_raw(raw, inverse_operator, **apply_kwargs)
            stc.save(
                os.path.join(output_dir, f"{epoch_label}_raw_{method}-{spacing}"),
                overwrite=True,
            )
            if visualize:
                visualize_source_estimate(
                    stc, subject_id, fs_subjects_dir, output_dir, epoch_label,
                    method, spacing, config, block=False,
                )

    if needs_lcmv:
        make_lcmv_kwargs, apply_lcmv_kwargs = _lcmv_mne_kwargs(
            config, resolved_rank, "raw"
        )
        logger.info("LCMV beamformer rank argument: %s", make_lcmv_kwargs.get("rank"))
        filters = make_lcmv(
            raw.info, fwd, data_cov, noise_cov=noise_cov,
            **make_lcmv_kwargs,
        )
        stc = apply_lcmv_raw(raw, filters, **apply_lcmv_kwargs)
        stc.save(
            os.path.join(output_dir, f"{epoch_label}_raw_LCMV-{spacing}"),
            overwrite=True,
        )
        if visualize:
            visualize_source_estimate(
                stc, subject_id, fs_subjects_dir, output_dir, epoch_label,
                "LCMV", spacing, config, block=False,
            )


def parse_arguments():
    """
    Parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        The parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description="Process source localization for MEG data.")
    parser.add_argument('--data_mode', type=str, default="epochs", choices=["raw", "epochs"],
                        help="Data mode: 'raw' for continuous data, 'epochs' for event-based epochs.")
    parser.add_argument('--data_file', type=str, required=True, help="Path to the epochs or raw file.")
    parser.add_argument('--fs_subjects_dir', type=str, required=True,
                        help="Path to the MRI subject directory (Freesurfer subjects dir).")
    parser.add_argument('--noise_covariance_file', type=str,
                        help="Exact routed noise covariance file (preferred).")
    parser.add_argument('--data_covariance_file', type=str,
                        help="Exact LCMV data covariance file; required only for LCMV.")
    parser.add_argument('--resolved_rank_file', type=str,
                        help="Resolved target-rank JSON produced by covariance.")
    parser.add_argument('--forward_file', type=str,
                        help="Exact routed forward solution file (preferred).")
    parser.add_argument('--noise_covariance_dir', type=str,
                        help="Legacy directory lookup for the noise covariance file.")
    parser.add_argument('--forward_dir', type=str,
                        help="Legacy directory lookup for the forward solution.")
    parser.add_argument('--output_dir', type=str, required=True, help="Subject output directory.")
    parser.add_argument('--config', type=str, help="Configuration parameters.")
    parser.add_argument('--visualize', type=str2bool, nargs='?', const=True, default=True, help="Whether to visualize the source imaging (default: True)")

    return parser.parse_args()


def main():
    """
    Main function to run the source localization for a single subject.
    """
    args = parse_arguments()
    handle_yaml_scientific_notation()

    Path(args.output_dir).mkdir(exist_ok=True, parents=True)

    config = yaml.safe_load(args.config)
    if not isinstance(config, dict):
        raise SourceConfigurationError("--config must decode to a mapping.")
    if args.data_mode == "raw":
        process_raw(args.data_file,
                    args.fs_subjects_dir,
                    args.noise_covariance_dir,
                    args.forward_dir,
                    args.output_dir,
                    config,
                    args.visualize,
                    noise_covariance_file=args.noise_covariance_file,
                    forward_file=args.forward_file,
                    data_covariance_file=args.data_covariance_file,
                    resolved_rank_file=args.resolved_rank_file)
    elif args.data_mode == "epochs":
        process_subject(args.data_file,
                        args.fs_subjects_dir,
                        args.noise_covariance_dir,
                        args.forward_dir,
                        args.output_dir,
                        config,
                        args.visualize,
                        noise_covariance_file=args.noise_covariance_file,
                        forward_file=args.forward_file,
                        data_covariance_file=args.data_covariance_file,
                        resolved_rank_file=args.resolved_rank_file)
    else:
        raise ValueError("Unspported data mode: {}".format(args.data_mode))
    print("Finished source recon processing...")

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
        logger.error("Source configuration or processing error: %s", error)
        raise SystemExit(2) from error
