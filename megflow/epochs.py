#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script to generate epochs from raw MEG data and save rejected epochs info.
"""

import os
import mne
import re
import ast
import argparse
import numpy as np
import logging
import pandas as pd
from scipy.io import loadmat
import yaml
from collections import defaultdict
from pathlib import Path
from autoreject import AutoReject
from autoreject import get_rejection_threshold
from epochs_preproc import get_analysis_preproc_steps, prepare_analysis_raw
from utils import load_bad_chn_seg, set_random_seed
import matplotlib.pyplot as plt
mne.viz.set_browser_backend('matplotlib')
set_random_seed(2025)

def plot_epochs(epochs, subj_tag, subj_path):
    """
    Generate and save plots for the epochs data.
    """
    try:
        subj_tag = Path(subj_tag).stem
        fig = epochs.plot_sensors(kind="3d", ch_type="all")
        fig.savefig(os.path.join(subj_path, f"{subj_tag}_epoch_onset_sensors_3d.png"), dpi=100)
        fig.clf()

        fig = epochs.plot_sensors(kind="topomap", ch_type="all")
        fig.savefig(os.path.join(subj_path, f"{subj_tag}_epoch_onset_sensors_2d.png"), dpi=100)
        fig.clf()

        fig = epochs.compute_psd().plot(picks="mag", exclude="bads")
        fig.savefig(os.path.join(subj_path, f"{subj_tag}_epoch_onset_psd.png"), dpi=100)
        fig.clf()

        evokeds = epochs.average(picks='mag')
        times = evokeds.times
        times = np.linspace(times[0], times[-1], 6)
        fig = evokeds.plot_topomap(times, ch_type="mag")
        fig.savefig(os.path.join(subj_path, f"{subj_tag}_epoch_onset_topo_mag.png"), dpi=100)
        fig.clf()
    except Exception as e:
        logging.error(e)

def _normalize_exclude_event_ids(exclude_event_id):
    """Convert exclude_event_id config to a set of ints, or empty set if unset."""
    if not exclude_event_id:
        return set()
    if isinstance(exclude_event_id, (str, int, float)):
        exclude_event_id = [exclude_event_id]
    elif isinstance(exclude_event_id, dict):
        exclude_event_id = exclude_event_id.values()
    return {int(eid) for eid in exclude_event_id if eid is not None}


def _get_epoch_kwargs(config):
    """Return MNE Epochs kwargs and keep MEGFlow-only keys out of MNE."""
    epoch_kwargs = dict(config.get('epochs') or {})
    for key in (
        'preproc',
        'task_type',
        'resting',
        'event_source',
        'autoreject',
        'interpolate_bads',
        'drop_bad_channels',
        'event_file',
        'find_events',
        'annotations',
        'exclude_event_id',
        'event_time_shift_sec',
        'event_time_shift_ms',
        'event_time_shift',
        'stimulus_delay_sec',
        'stimulus_delay_ms',
        'event_timing',
    ):
        epoch_kwargs.pop(key, None)
    return epoch_kwargs


def _get_exclude_event_id(config):
    exclude_event_id = config.get('exclude_event_id', None)
    if exclude_event_id is None:
        exclude_event_id = (config.get('epochs') or {}).get('exclude_event_id', None)
    return exclude_event_id


def load_epoch_artifact_sidecars(
    raw,
    fname_bad_channels=None,
    fname_bad_segments=None,
):
    """Apply artifact sidecars to Raw before epoch construction when provided."""
    has_bad_channels = bool(fname_bad_channels)
    has_bad_segments = bool(fname_bad_segments)
    if has_bad_channels != has_bad_segments:
        raise ValueError(
            "Both bad-channel and bad-segment sidecars are required when "
            "loading artifact results for epoching."
        )
    if not has_bad_channels:
        return raw
    return load_bad_chn_seg(raw, fname_bad_channels, fname_bad_segments)


def analysis_preproc_has_operation(config, operation, *, config_name="epochs.preproc"):
    return any(
        operation in step
        for step in get_analysis_preproc_steps(config, config_name=config_name)
    )


def _auxiliary_trigger_events_for_resample(raw, config):
    """Find trigger events used only to make Raw resampling event-aware."""
    find_config = dict(config.get('find_events') or config.get('events') or {})
    find_config.setdefault('initial_event', True)
    find_config['verbose'] = False
    try:
        events = mne.find_events(raw, **find_config)
    except (ValueError, RuntimeError):
        return None
    if events is None or len(events) == 0:
        return None
    return events


def _config_float(value, key):
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a numeric value, got {value!r}") from exc


def _get_event_time_shift_sec(config):
    """Return configured event timing shift in seconds.

    Positive values move event sample indices later in time, which is useful
    when hardware triggers precede the actual sensory stimulus arrival.
    """
    event_timing = config.get('event_timing') or {}
    if not isinstance(event_timing, dict):
        raise ValueError("event_timing must be a mapping when provided.")

    seconds_keys = (
        ('event_time_shift_sec', config.get('event_time_shift_sec')),
        ('event_time_shift', config.get('event_time_shift')),
        ('stimulus_delay_sec', config.get('stimulus_delay_sec')),
        ('event_timing.event_time_shift_sec', event_timing.get('event_time_shift_sec')),
        ('event_timing.shift_sec', event_timing.get('shift_sec')),
        ('event_timing.stimulus_delay_sec', event_timing.get('stimulus_delay_sec')),
    )
    for key, value in seconds_keys:
        parsed = _config_float(value, key)
        if parsed is not None:
            return parsed

    millisecond_keys = (
        ('event_time_shift_ms', config.get('event_time_shift_ms')),
        ('stimulus_delay_ms', config.get('stimulus_delay_ms')),
        ('event_timing.event_time_shift_ms', event_timing.get('event_time_shift_ms')),
        ('event_timing.shift_ms', event_timing.get('shift_ms')),
        ('event_timing.stimulus_delay_ms', event_timing.get('stimulus_delay_ms')),
    )
    for key, value in millisecond_keys:
        parsed = _config_float(value, key)
        if parsed is not None:
            return parsed / 1000.0

    return 0.0


def apply_event_time_shift(events, sfreq, config, context="events"):
    """Apply a configured event timing shift to MNE events."""
    if events is None or len(events) == 0:
        return events

    shift_sec = _get_event_time_shift_sec(config)
    if not shift_sec:
        return events

    shift_samples = int(round(shift_sec * float(sfreq)))
    if shift_samples == 0:
        print(
            f"Configured event_time_shift_sec={shift_sec:g} for {context}, "
            f"but it rounds to 0 samples at {sfreq:g} Hz."
        )
        return events

    shifted = events.copy()
    shifted[:, 0] = shifted[:, 0] + shift_samples
    print(
        f"Applied event_time_shift_sec={shift_sec:g} "
        f"({shift_samples} samples at {sfreq:g} Hz) to {context}."
    )
    return shifted


def _validate_epoch_events(events, context):
    if events is None or len(events) == 0:
        raise ValueError(f"No events remain for epoching after applying event filters ({context}).")
    return events


def _read_events_text(events_file):
    """Read a BIDS events.tsv file."""
    with open(events_file, 'r', encoding='utf-8-sig') as f:
        return f.read().splitlines()


def _should_read_bids_events(events_file):
    """Return True only for explicit BIDS-style tabular event files."""
    if not events_file:
        return False

    path = Path(events_file)
    suffix = path.suffix.lower()
    if suffix == ".tsv":
        if not path.exists():
            raise FileNotFoundError(f"BIDS events file does not exist: {events_file}")
        return True

    if path.exists():
        print(
            f"Event source is 'event_file', but {events_file} is not a BIDS "
            "events.tsv file. Falling back to mne.find_events."
        )
    else:
        print(
            f"Event source is 'event_file', but inferred events file does not exist: "
            f"{events_file}. Falling back to mne.find_events."
        )
    return False


def _find_events(raw, config, exclude_event_id):
    find_events_config = config.get('find_events')
    if find_events_config is None:
        find_events_config = config.get('events', {})
    events = mne.find_events(raw, **(find_events_config or {}))
    events = filter_events_by_exclude(events, exclude_event_id)
    return _validate_epoch_events(events, "find_events")


def _events_from_annotations(raw, config, exclude_event_id):
    annotations_config = config.get('annotations') or {}
    fixed_event_id = annotations_config.get('event_id')
    event_id_map = annotations_config.get('event_id_map')

    if fixed_event_id is not None:
        event_id = lambda desc: int(fixed_event_id)
    elif event_id_map:
        event_id = event_id_map
    else:
        event_id = annotations_config.get('event_id_mode', 'auto')

    events, _ = mne.events_from_annotations(raw, event_id=event_id)
    events = filter_events_by_exclude(events, exclude_event_id)
    return _validate_epoch_events(events, "annotations")


def filter_events_by_exclude(events, exclude_event_id):
    """
    Remove events whose id (third column) is listed in exclude_event_id.

    Parameters
    ----------
    events : ndarray, shape (n_events, 3)
    exclude_event_id : list, optional
        Event ids to drop.

    Returns
    -------
    events : ndarray, shape (n_events, 3)
    """
    exclude_ids = _normalize_exclude_event_ids(exclude_event_id)
    if not exclude_ids or events.size == 0:
        return events
    mask = np.array([evt[2] not in exclude_ids for evt in events])
    filtered = events[mask]
    if len(filtered) < len(events):
        print(f"Excluded event ids {sorted(exclude_ids)}: "
              f"{len(events) - len(filtered)} events removed, {len(filtered)} kept.")
    return filtered


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _first_event_type_key(event_types, header):
    if not isinstance(event_types, dict):
        return 'trial_type'
    if event_types.get('column'):
        return event_types.get('column')

    control_keys = {
        'event_id',
        'value_column',
        'trial_type_contains',
        'trial_type_regex',
        'trial_type_fields',
    }
    for key in event_types.keys():
        if key not in control_keys and key in header:
            return key
    return 'trial_type'


def _parse_mapping_text(value):
    try:
        parsed = ast.literal_eval(value)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _matches_field_filters(value, field_filters):
    if not field_filters:
        return True

    parsed = _parse_mapping_text(value)
    if not parsed:
        return False

    for field_name, expected in field_filters.items():
        actual = parsed.get(field_name)
        expected_values = [str(item) for item in _as_list(expected)]
        if str(actual) not in expected_values:
            return False
    return True


def _matches_text_filters(value, contains_filters, regex_filters):
    if contains_filters:
        if not any(str(token) in value for token in contains_filters):
            return False
    if regex_filters:
        if not any(re.search(str(pattern), value) for pattern in regex_filters):
            return False
    return True


def _event_value_from_row(columns, value_idx, event_type_value, exact_mapping, fixed_event_id):
    if exact_mapping is not None:
        return int(exact_mapping[event_type_value])
    if fixed_event_id is not None:
        return int(fixed_event_id)
    if value_idx is None:
        return 1
    return int(columns[value_idx].strip('"'))


def read_bids_events(events_file,sfreq,event_types=None,exclude_event_id=None):
    """
    Read events from a BIDS formatted events file.

    Parameters
    ----------
    events_file : str
        Path to the events file in BIDS format.
    sfreq: float, optional
        sample rate.
    event_types : dict, optional
        A dictionary to filter specific event types (e.g., {'type': ['word1', 'word2']}).
        If None, all events will be returned.
    exclude_event_id : list, optional
        A list of event ids to exclude.
    Returns
    -------
    events : ndarray, shape (n_events, 3)
        Array of events to be used with MNE.
    """
    events = []
    exclude_ids = _normalize_exclude_event_ids(exclude_event_id)

    lines = [line for line in _read_events_text(events_file) if line.strip()]
    if not lines:
        raise ValueError(f"Events file has no non-empty rows: {events_file}")

    header = lines[0].strip().split('\t')
    # Remove any leading BOM characters (if not done by encoding)
    header = [col.lstrip('\ufeff') for col in header]
    onset_idx = header.index('onset')

    try:
        value_idx = header.index('value')
    except ValueError as e:
        value_idx = None

    event_types = event_types or {'trial_type': None}
    type_key = _first_event_type_key(event_types, header)
    type_idx = header.index(type_key)

    type_filter = event_types.get(type_key) if isinstance(event_types, dict) else None
    exact_values = None
    exact_mapping = None
    if type_filter is not None:
        filtered_events = []
        if isinstance(type_filter, dict):
            filtered_events.extend(list(type_filter.keys()))
            exact_mapping = type_filter
        else:
            filtered_events.extend(_as_list(type_filter))
        exact_values = {str(item) for item in filtered_events}
        print("filtered_events:", filtered_events)
        print("type_key:", type_key)

    contains_filters = _as_list(event_types.get(f'{type_key}_contains')) if isinstance(event_types, dict) else []
    if not contains_filters and type_key == 'trial_type' and isinstance(event_types, dict):
        contains_filters = _as_list(event_types.get('trial_type_contains'))
    regex_filters = _as_list(event_types.get(f'{type_key}_regex')) if isinstance(event_types, dict) else []
    if not regex_filters and type_key == 'trial_type' and isinstance(event_types, dict):
        regex_filters = _as_list(event_types.get('trial_type_regex'))
    field_filters = event_types.get(f'{type_key}_fields') if isinstance(event_types, dict) else None
    if not field_filters and type_key == 'trial_type' and isinstance(event_types, dict):
        field_filters = event_types.get('trial_type_fields')
    fixed_event_id = event_types.get('event_id') if isinstance(event_types, dict) else None

    for line in lines[1:]:
        columns = line.strip().split('\t')
        if len(columns) <= onset_idx or len(columns) <= type_idx:
            continue
        onset = float(columns[onset_idx])
        event_type_value = columns[type_idx].strip() if type_idx is not None else None

        if exact_values is not None:
            if event_type_value not in exact_values:
                continue
        if not _matches_text_filters(event_type_value, contains_filters, regex_filters):
            continue
        if not _matches_field_filters(event_type_value, field_filters):
            continue

        if value_idx is not None and len(columns) <= value_idx:
            if fixed_event_id is None and exact_mapping is None:
                continue

        # handle the problem that value is not int
        try:
            value = _event_value_from_row(
                columns,
                value_idx,
                event_type_value,
                exact_mapping,
                fixed_event_id,
            )
        except ValueError as e:
            row_value = columns[value_idx] if value_idx is not None and len(columns) > value_idx else ''
            print(f"ValueError: The value:{row_value} is not int.(Please check the event file.)", e)
            break

        value = int(value)
        if value in (0, -1) or value in exclude_ids:
            continue

        events.append([int(onset * sfreq), 0, value])

    return np.array(events, dtype=int)


def prepare_epoching_raw_and_events(
    raw,
    config,
    events_file="",
    *,
    preproc_config=None,
    preproc_config_name="epochs.preproc",
    output_analysis_raw_file=None,
):
    """Prepare continuous Raw data and events through one shared path.

    Trigger-channel events are detected before resampling so MNE can remap their
    sample indices. BIDS onsets and annotations are converted after optional
    preprocessing using the final sampling rate.
    """
    config = config or {}
    analysis_config = config if preproc_config is None else preproc_config
    task_type = config.get('task_type', 'task')
    event_source = config.get('event_source', 'find_events')
    exclude_event_id = _get_exclude_event_id(config)
    events = None
    read_bids_event_file = False

    if task_type == 'task':
        if event_source == 'find_events':
            events = _find_events(raw, config, exclude_event_id)
        elif event_source == 'event_file':
            read_bids_event_file = _should_read_bids_events(events_file)
            if not read_bids_event_file:
                events = _find_events(raw, config, exclude_event_id)
        elif event_source != 'annotations':
            raise ValueError(
                "Unknown event_source specified in the config. "
                "Use 'find_events', 'annotations', or 'event_file'."
            )
    elif task_type != 'resting':
        raise ValueError("Unknown task_type specified in the config. Use 'resting' or 'task'.")

    events_are_authoritative = events is not None
    resample_events = events
    if resample_events is None and analysis_preproc_has_operation(
        analysis_config,
        'resample',
        config_name=preproc_config_name,
    ):
        resample_events = _auxiliary_trigger_events_for_resample(raw, config)
        if resample_events is not None:
            print(
                f"Tracking {len(resample_events)} auxiliary trigger events during Raw resampling; "
                f"{event_source} remains the epoch event source."
            )

    raw, remapped_events, preprocessed = prepare_analysis_raw(
        raw,
        analysis_config,
        events=resample_events,
        save_path=output_analysis_raw_file,
        config_name=preproc_config_name,
    )
    events = remapped_events if events_are_authoritative else None

    if task_type == 'resting':
        fixed_length_duration = (config.get('resting') or {}).get('fixed_length_duration', 2.0)
        print(f"Resting Epochs, fixed length duration: {fixed_length_duration}")
        events = mne.make_fixed_length_events(raw, id=1, duration=fixed_length_duration)
        return raw, events, preprocessed

    if event_source == 'annotations':
        events = _events_from_annotations(raw, config, exclude_event_id)
    elif event_source == 'event_file' and read_bids_event_file:
        print(f"Load bids events file from {events_file}")
        events = read_bids_events(
            events_file,
            raw.info['sfreq'],
            config.get('event_file'),
            exclude_event_id,
        )
        events = _validate_epoch_events(events, "event_file")
        events[:, 0] = events[:, 0] + raw.first_samp
        print("bids events:\n", events)

    events = _validate_epoch_events(events, event_source)
    events = apply_event_time_shift(events, raw.info['sfreq'], config, event_source)
    return raw, events, preprocessed


def epochs(
    subj_data_file,
    output_epoch_file,
    output_dir,
    events_file,
    config,
    output_analysis_raw_file=None,
    fname_bad_channels=None,
    fname_bad_segments=None,
):
    """
    Process each subject and session to generate epochs and handle rejection logs.
    """

    # Load raw data
    raw = mne.io.read_raw_fif(subj_data_file)
    raw = load_epoch_artifact_sidecars(
        raw,
        fname_bad_channels=fname_bad_channels,
        fname_bad_segments=fname_bad_segments,
    )

    # Extract parameters from config
    subj_tag = os.path.basename(subj_data_file)
    epoch_kwargs = _get_epoch_kwargs(config)
    raw, events, _ = prepare_epoching_raw_and_events(
        raw,
        config,
        events_file,
        output_analysis_raw_file=output_analysis_raw_file,
    )
    epochs_data = mne.Epochs(raw=raw, events=events, **epoch_kwargs)

    if config.get('interpolate_bads', False):
        print("Interpolating bad channels in epochs.")
        epochs_data.interpolate_bads(reset_bads=True)

    if config.get('drop_bad_channels', False):
        bad_channels = list(epochs_data.info['bads'])
        if bad_channels:
            print("Dropping bad channels in epochs: {}".format(bad_channels))
            epochs_data.drop_channels(bad_channels)
        else:
            print("No bad channels found in epochs to drop.")

    # autoreject[epochs]
    # if config.get('autoreject'):
        # ar = AutoReject()
        # epochs_data = ar.fit_transform(epochs_data) # clean epochs
        # reject_log = ar.get_reject_log(epochs_data)
        # reject_log.bad_epochs
        # reject_log.plot('horizontal')
    try:
        if config.get('autoreject'):
            # global rejection threshold.
            reject = get_rejection_threshold(epochs_data)
            epochs_data.drop_bad(reject=reject)
    except Exception as e:
        print("Error while auto-rejecting[autoreject]")

    # Save epochs and plots
    epochs_data.save(os.path.join(output_dir, output_epoch_file), overwrite=True)

    reject_epochs_id_file = os.path.join(output_dir, f"{Path(subj_tag).stem}_reject_epoch_log.txt")
    save_rejected_epochs(epochs_data, subj_tag, reject_epochs_id_file)

    plot_epochs(epochs_data, subj_tag, output_dir)
    return epochs_data


def save_rejected_epochs(epochs, subj_tag, reject_epochs_id_file):
    """
    Save the rejected epochs and update the rejection log.
    """
    # Initialize dictionary for rejected epochs
    rejected_epochs_dict = defaultdict(lambda: defaultdict(list))

    rejected_epochs_ids = [i for i, reason in enumerate(epochs.drop_log) if reason]
    rejected_epochs_dict[f"{subj_tag}"] = rejected_epochs_ids
    num_epochs = len(epochs)

    with open(reject_epochs_id_file, 'w') as file:
        for subject,epoch_id in rejected_epochs_dict.items():
            file.write(f"{epoch_id}\n")
        file.write(f"num_epochs:{num_epochs}")
    print(f"Rejected epochs data has been saved to {reject_epochs_id_file}")



def parse_arguments():
    """
    Parse command line arguments.
    """
    parser = argparse.ArgumentParser(description="Generate epochs from raw MEG data and save rejected epochs info.")
    parser.add_argument('--preproc_raw_file', type=str, required=True, help="")
    parser.add_argument('--events_file', type=str, default="", help="Path to the events.tsv file. (BIDS)")
    parser.add_argument('--output_epoch_file', type=str, default="epoch-epo.fif", help="")
    parser.add_argument(
        '--output_analysis_raw_file',
        type=str,
        default="",
        help="Optional output path for continuous Raw after epochs.preproc.",
    )
    parser.add_argument('--output_dir', type=str, default=".", help="")
    parser.add_argument(
        '--fname_bad_channels',
        type=str,
        default="",
        help="Optional bad-channel sidecar applied before epoching.",
    )
    parser.add_argument(
        '--fname_bad_segments',
        type=str,
        default="",
        help="Optional bad-segment annotation sidecar applied before epoching.",
    )
    parser.add_argument('--config', type=str,  default="{}", help="YAML configuration string for epochs")

    return parser.parse_args()

def main():
    # Parse command-line arguments
    args = parse_arguments()

    # handle scientific notation.
    loader = yaml.SafeLoader
    loader.add_implicit_resolver(
        u'tag:yaml.org,2002:float',
        re.compile(u'''^(?:
         [-+]?(?:[0-9][0-9_]*)\\.[0-9_]*(?:[eE][-+]?[0-9]+)?
        |[-+]?(?:[0-9][0-9_]*)(?:[eE][-+]?[0-9]+)
        |\\.[0-9_]+(?:[eE][-+][0-9]+)?
        |[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\\.[0-9_]*
        |[-+]?\\.(?:inf|Inf|INF)
        |\\.(?:nan|NaN|NAN))$''', re.X),
        list(u'-+0123456789.'))

    # # debug
    # epoch_config = """
    #     task_type: 'task'   # or 'resting'
    #     event_source: 'event_file'  # event_file or 'find_events'
    #     autoreject: true
    #     resting:
    #         fixed_length_duration: 2.0
    #
    #     #event_file
    #     event_file:
    #         # trial_type: null # specific the event type of *_events.tsv[filterd]; null means get all events.
    #         trial_type:
    #             Beg: 1
    #             End: 2
    #         # type:
    #         #     word_onset_01: 1
    #         #     phoneme_onset_01: 2
    #         # trial_type:
    #         #     - Beg
    #
    #     # find events
    #     find_events:
    #         stim_channel: null
    #         shortest_event: 1
    #         min_duration: 0.0
    #     exclude_event_id:
    #         - 255
    #         - 99
    #     epochs:
    #         event_id: null
    #         tmin: -0.2
    #         tmax: 1
    #         reject_by_annotation: false
    #         picks: meg
    #         baseline: null
    #         reject:
    #             grad: 4000e-13
    #             mag: 4e-12
    #         preload: true
    #         detrend: null
    # """
    # args.config = epoch_config

    # Parse YAML configuration
    config = yaml.safe_load(args.config) or {}
    print(config)
    os.makedirs(args.output_dir, exist_ok=True)
    epochs(
        args.preproc_raw_file,
        args.output_epoch_file,
        args.output_dir,
        args.events_file,
        config,
        output_analysis_raw_file=args.output_analysis_raw_file or None,
        fname_bad_channels=args.fname_bad_channels or None,
        fname_bad_segments=args.fname_bad_segments or None,
    )


if __name__ == "__main__":
    main()
