#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import mne
import argparse
import matplotlib.pyplot as plt
from utils import handle_yaml_scientific_notation,set_random_seed,str2bool
import yaml
from pathlib import Path
mne.viz.set_browser_backend('matplotlib')
set_random_seed(2025)

def compute_noise_covariance(epochs, output_dir, config):
    """
    Compute the noise covariance matrix from baseline data or epochs and save it if not already saved.

    Parameters
    ----------
    epochs : mne.Epochs
        The epochs data to compute the noise covariance.
    output_dir : str or Path
        The path where the covariance file should be saved.


    Returns
    -------
    noise_cov : mne.Covariance
        The computed noise covariance matrix.
    """
    noise_cov_fn = os.path.join(output_dir, 'bl-cov.fif')

    # Use epochs data for covariance calculation
    noise_cov = mne.compute_covariance(epochs, **config.get('covariance'))

    noise_cov.save(noise_cov_fn, overwrite=True)

    return noise_cov

def visualize_covariance_and_spectra(noise_cov, raw_data, output_dir):
    """
    Visualize and save the noise covariance matrix and its spectra.

    Parameters
    ----------
    noise_cov : mne.Covariance
        The noise covariance matrix.
    raw_data : mne.io.Raw
        The raw MEG/EEG data.
    output_dir : str or Path
        The path to save the output figures.

    Returns
    -------
    None
    """
    # Check if the covariance and spectra plots already exist, if not, generate and save them
    cov_plot_path = os.path.join(output_dir, 'bl_cov.png')
    spectra_plot_path = os.path.join(output_dir, 'bl_cov_spectra.png')
    fig_cov, fig_spectra = mne.viz.plot_cov(noise_cov, raw_data.info, show=False) # slowly.
    fig_cov.savefig(cov_plot_path)
    fig_spectra.savefig(spectra_plot_path)
    plt.close('all')
    print(f"Saved covariance and spectra plots to {output_dir}")


def parse_arguments():
    """
    Parse command line arguments.
    """
    parser = argparse.ArgumentParser(description="Compute and visualize noise covariance matrix.")
    parser.add_argument('--raw_data_file', type=str, required=True, help="Path to raw data file (e.g., .fif file)")
    parser.add_argument('--output_dir', type=str, required=True,
                        help="Path where the covariance file should be saved")
    parser.add_argument('--visualize', type=str2bool, nargs='?', const=True, default=True,
                        help="Whether to visualize the covariance matrix (default: False)")
    parser.add_argument('--covar_type', type=str, required=True,
                        help="Estimate noise covariance matrix from Raw or Epochs.[raw or epochs]")
    parser.add_argument('--config', type=str, help="Config Parameters")

    return parser.parse_args()


def main():
    """
    Main function to compute and visualize the noise covariance matrix.
    """
    # Parse command-line arguments
    args = parse_arguments()

    handle_yaml_scientific_notation()

    Path(args.output_dir).mkdir(exist_ok=True,parents=True)
    
    # debug 
    # args.config = """
    #
    #     ## 1.Estimate noise covariance matrix from a continuous segment of raw data.
    #     compute_raw_covariance:
    #         tmin: 0
    #         tmax: null
    #         method: auto
    #         reject:
    #             grad: 4000e-13  # T / m (gradiometers)
    #             mag: 4e-12  # T (magnetometers)
    #         reject_by_annotation: true
    #         rank: null
    #
    #     ## 2.Estimate noise covariance matrix from epochs.
    #     # find events
    #     events:
    #         stim_channel: UPPT001 # for CTF Holmes
    #         shortest_event: 1
    #         min_duration: 0.0
    #
    #     # For baseline epochs
    #     epochs:
    #         event_id: 16
    #         tmin: -0.2 # Start time (in seconds) for covariance calculation window
    #         tmax: 0.0 # End time (in seconds) for covariance calculation window
    #         reject_by_annotation: true
    #         picks: meg
    #         baseline: null
    #         reject:
    #             grad: 4000e-13
    #             mag: 4e-12
    #         preload: true
    #         detrend: null
    #         reject_by_annotation: true
    #
    #     covariance:
    #         tmin: null  # Start time for baseline. If null start at first sample.
    #         tmax: null  # End time for baseline. If null end at last sample.
    #         rank: null # Rank used for covariance calculation
    # """
    
    config = yaml.safe_load(args.config)
    print(config)

    # Load baseline data
    raw = mne.io.read_raw_fif(args.raw_data_file)

    covar_type = args.covar_type
    if covar_type == 'raw':
        # Estimate noise covariance matrix from a continuous segment of raw data.
        noise_cov = mne.compute_raw_covariance(raw,**config.get("compute_raw_covariance"))
        noise_cov_fn = os.path.join(args.output_dir, 'bl-cov.fif')
        noise_cov.save(noise_cov_fn,overwrite=True)

    elif covar_type == 'epochs':
        # epochs noise covariance
        events = mne.find_events(raw,**config.get('events'))

        # Create epochs
        epochs = mne.Epochs(raw=raw, events=events, **config.get('epochs'))

        # Step 1: Compute noise covariance
        noise_cov = compute_noise_covariance(epochs, args.output_dir, config)
    else:
        raise ValueError(f"{covar_type} is not a valid.")

    # Step 2: Visualize and save covariance and spectra plots | slowly
    if bool(args.visualize):
        visualize_covariance_and_spectra(noise_cov, raw, args.output_dir)


if __name__ == "__main__":
    main()
