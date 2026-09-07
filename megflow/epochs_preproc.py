#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Continuous MEG preprocessing for Raw- or Epochs-based secondary analysis."""

import argparse
from pathlib import Path

import mne
import numpy as np
import yaml

from utils import handle_yaml_scientific_notation


_SUPPORTED_OPERATIONS = {"filter", "notch", "notch_filter", "resample"}


def get_analysis_preproc_steps(config=None, *, config_name="epochs.preproc"):
    """Return normalized analysis-Raw preprocessing steps.

    Missing, null, empty-list, empty-dict, and ``steps: []`` configurations are
    true no-ops.
    """
    if config is None:
        return []

    value = config
    if isinstance(config, dict):
        if not config:
            return []
        if "preproc" in config:
            value = config.get("preproc")
        elif "steps" in config:
            value = config
        elif len(config) == 1 and next(iter(config)) in _SUPPORTED_OPERATIONS:
            value = [config]
        else:
            return []

    if value is None:
        return []

    if isinstance(value, dict):
        if not value:
            return []
        if "steps" in value:
            value = value.get("steps")
            if value is None:
                return []
        else:
            value = [value]

    if value is None:
        return []

    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{config_name} must be a list of single-operation mappings.")

    steps = []
    for index, step in enumerate(value):
        if not isinstance(step, dict) or len(step) != 1:
            raise ValueError(
                f"{config_name}[{index}] must contain exactly one operation, got {step!r}."
            )
        operation = next(iter(step))
        if operation not in _SUPPORTED_OPERATIONS:
            raise ValueError(
                f"Unsupported {config_name} operation {operation!r}. "
                "Supported operations: filter, notch_filter/notch, resample."
            )
        steps.append(dict(step))
    return steps


def _numeric_freqs(value):
    if isinstance(value, str):
        return [float(item) for item in value.replace(",", " ").split() if item]
    if isinstance(value, (list, tuple, np.ndarray)):
        return [float(item) for item in value]
    return [float(value)]


def prepare_analysis_raw(
    raw,
    config=None,
    *,
    events=None,
    save_path=None,
    config_name="epochs.preproc",
):
    """Apply optional analysis preprocessing to continuous Raw data.

    When ``events`` are supplied and a resample step is configured, MNE remaps
    event sample indices together with the Raw object. ``save_path`` is honored
    only when at least one preprocessing step is applied.
    """
    steps = get_analysis_preproc_steps(config, config_name=config_name)
    if not steps:
        return raw, events, False

    raw.load_data()
    current_events = None if events is None else np.asarray(events, dtype=int).copy()
    before = {
        "highpass": float(raw.info.get("highpass", 0.0)),
        "lowpass": float(raw.info.get("lowpass", 0.0)),
        "sfreq": float(raw.info["sfreq"]),
    }

    for step in steps:
        operation, raw_kwargs = next(iter(step.items()))
        kwargs = dict(raw_kwargs or {})

        if operation == "filter":
            raw.filter(**kwargs)
        elif operation in {"notch", "notch_filter"}:
            if "freqs" not in kwargs:
                raise ValueError(f"{config_name} notch_filter requires freqs.")
            kwargs["freqs"] = _numeric_freqs(kwargs["freqs"])
            raw.notch_filter(**kwargs)
        elif operation == "resample":
            if "sfreq" not in kwargs:
                raise ValueError(f"{config_name} resample requires sfreq.")
            target_sfreq = float(kwargs.pop("sfreq"))
            if target_sfreq <= 0:
                raise ValueError(f"{config_name} resample.sfreq must be positive.")
            if np.isclose(target_sfreq, float(raw.info["sfreq"]), rtol=0.0, atol=1e-9):
                print(f"Skipping analysis resample because Raw is already {target_sfreq:g} Hz.")
                continue
            if current_events is None:
                raw.resample(target_sfreq, **kwargs)
            else:
                raw, current_events = raw.resample(
                    target_sfreq,
                    events=current_events,
                    **kwargs,
                )

    after = {
        "highpass": float(raw.info.get("highpass", 0.0)),
        "lowpass": float(raw.info.get("lowpass", 0.0)),
        "sfreq": float(raw.info["sfreq"]),
    }
    print(f"Applied analysis Raw preprocessing: before={before}, after={after}")

    if save_path:
        analysis_path = Path(save_path)
        analysis_path.parent.mkdir(parents=True, exist_ok=True)
        raw.save(analysis_path, overwrite=True)
        print(f"Analysis-ready continuous MEG data saved to {analysis_path}")

    return raw, current_events, True


def materialize_analysis_raw(input_file, output_file, config=None):
    """Create the exact continuous Raw artifact consumed by source imaging."""
    input_path = Path(input_file)
    output_path = Path(output_file)
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Analysis Raw output must differ from its input file.")

    raw = mne.io.read_raw_fif(input_path, preload=True)
    raw, _, _ = prepare_analysis_raw(raw, config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw.save(output_path, overwrite=True)
    print(f"Analysis-ready continuous MEG data saved to {output_path}")
    return output_path


def apply_continuous_preproc(raw, config=None, events=None):
    """Backward-compatible alias for older callers."""
    return prepare_analysis_raw(raw, config, events=events)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Materialize analysis-ready continuous MEG data."
    )
    parser.add_argument("--input_file", required=True)
    parser.add_argument("--output_file", required=True)
    parser.add_argument("--config", default="{}")
    return parser.parse_args()


def main():
    args = parse_arguments()
    handle_yaml_scientific_notation()
    config = yaml.safe_load(args.config)
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError("--config must decode to a mapping.")
    materialize_analysis_raw(args.input_file, args.output_file, config)


if __name__ == "__main__":
    main()
