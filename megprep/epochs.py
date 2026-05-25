#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script to generate epochs from raw MEG data and save rejected epochs info.
"""

import os
import mne
import re
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
from utils import set_random_seed
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
    return {int(eid) for eid in exclude_event_id}


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

    with open(events_file, 'r') as f:
        header = f.readline().strip().split('\t')
        # Remove any leading BOM characters (if not done by encoding)
        header = [col.lstrip('\ufeff') for col in header]
        onset_idx = header.index('onset')

        try:
            value_idx = header.index('value')
        except ValueError as e:
            value_idx = None

        type_key = list(event_types.keys())[0]
        type_idx = header.index(type_key)

        if event_types[type_key] is not None:
            filtered_events = []
            for evt in event_types.values():
                if isinstance(evt, dict):
                    filtered_events.extend(list(evt.keys()))
                else:
                    filtered_events.extend(evt)
            print("filtered_events:", filtered_events)
            print("type_key:", type_key)

        for line in f:
            if line.strip():
                columns = line.strip().split('\t')
                onset = float(columns[onset_idx])
                event_type_value = columns[type_idx].strip() if type_idx is not None else None

                if event_types[type_key] is not None:
                    if event_type_value not in filtered_events:
                        continue

                # handle the problem that value is not int
                try:
                    if isinstance(event_types[type_key], dict):
                        value = event_types[type_key][event_type_value]
                    else:
                        value = int(columns[value_idx].strip('"'))  # Remove quotes and convert to int.
                except ValueError as e:
                    print(f"ValueError: The value:{columns[value_idx]} is not int.(Please check the event file.)", e)
                    break

                value = int(value)
                if value in (0, -1) or value in exclude_ids:
                    continue

                events.append([int(onset * sfreq), 0, value])

    return np.array(events, dtype=int)

def epochs(subj_data_file,output_epoch_file, output_dir, events_file, config):
    """
    Process each subject and session to generate epochs and handle rejection logs.
    """

    # Load raw data
    raw = mne.io.read_raw_fif(subj_data_file)

    # Extract parameters from config
    task_type = config.get('task_type', 'task')
    subj_tag = os.path.basename(subj_data_file)

    event_source = config.get('event_source', 'find_events')
    exclude_event_id = config.get('exclude_event_id', None)


    if task_type == 'resting':
        fixed_length_duration = config.get('resting', {}).get('fixed_length_duration', 2.0)
        print("Resting Epochs, fixed length duration: {}".format(fixed_length_duration))
        events = mne.make_fixed_length_events(raw, id=1, duration=fixed_length_duration)
        epochs_data = mne.Epochs(raw=raw, events=events, **config.get('epochs'))
    elif task_type == 'task':
        if event_source == 'find_events':
            events = mne.find_events(raw, **config.get('find_events', {}))
            events = filter_events_by_exclude(events, exclude_event_id)
            epochs_data = mne.Epochs(raw=raw, events=events, **config.get('epochs'))
        else:
            # According to the event file to generate epochs (in BIDS format)
            # events = mne.read_events(events_file)
            print("Load bids events file from {}".format(events_file))
            events = read_bids_events(
                events_file, raw.info['sfreq'], config.get('event_file'), exclude_event_id
            )
            # add first sample
            events[:, 0] = events[:, 0] + raw.first_samp
            print("bids events:\n", events)
            epochs_data = mne.Epochs(raw=raw, events=events, **config.get('epochs'))
    else:
        raise ValueError("Unknown task_type specified in the config. Use 'resting' or 'task'.")

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
    parser.add_argument('--output_dir', type=str, default=".", help="")
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
    config = yaml.safe_load(args.config)
    print(config)
    os.makedirs(args.output_dir, exist_ok=True)
    epochs(args.preproc_raw_file, args.output_epoch_file, args.output_dir, args.events_file, config)


if __name__ == "__main__":
    main()
