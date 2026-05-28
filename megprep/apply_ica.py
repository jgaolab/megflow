#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import mne
import argparse
from mne.preprocessing import read_ica
import matplotlib.pyplot as plt
from utils import load_bad_chn_seg

def load_exclude_components(exclude_file):
    """
    Load components to exclude from the specified text file.
    Each line in the text file should contain one component index.
    """
    exclude = []
    with open(exclude_file, 'r') as f:
        for line in f:
            try:
                exclude.append(int(line.strip()))
            except ValueError:
                print(f"Skipping invalid line in exclude file: {line.strip()}")
    return exclude

def apply_ica(raw_file, ica_file, exclude_file, output_file, output_dir, fname_bad_channels, fname_bad_segments):
    # Load raw data
    raw = mne.io.read_raw_fif(raw_file, preload=True)
    raw = load_bad_chn_seg(raw, fname_bad_channels, fname_bad_segments)

    # Load ICA data
    ica = read_ica(ica_file)

    # Load components to exclude
    exclude = load_exclude_components(exclude_file)
    ica.exclude = exclude
    print(f"Excluding components: {exclude}")

    # Apply ICA to clean the data
    raw_cleaned = raw.copy()
    ica.apply(raw_cleaned)

    # Save cleaned raw data
    raw_cleaned.save(output_file, overwrite=True)
    print(f"Cleaned MEG data saved to {output_file}")

    # Generate quality assurance plots
    os.makedirs(output_dir, exist_ok=True)

    # Plot and save ICA overlay (magnetometers)
    fig_mag = ica.plot_overlay(raw, exclude=exclude, picks='mag', show=False)
    fig_mag.set_size_inches(12, 8)
    fig_mag.savefig(os.path.join(output_dir, "ica_overlay_mag.png"), dpi=150)
    plt.close(fig_mag)

    try:
        # Plot and save ICA overlay (gradiometers)
        fig_grad = ica.plot_overlay(raw, exclude=exclude, picks='grad', show=False)
        fig_grad.set_size_inches(12, 8)
        fig_grad.savefig(os.path.join(output_dir, "ica_overlay_grad.png"), dpi=150)
        plt.close(fig_grad)
    except ValueError as e:
        print("picks ('grad') could not be used.")

    # Plot and save PSD before cleaning
    fig_psd_before = raw.compute_psd(picks='meg').plot(show=False)
    fig_psd_before.savefig(os.path.join(output_dir, "raw_psd.png"), dpi=150)
    plt.close(fig_psd_before)

    # Plot and save PSD after cleaning
    fig_psd_after = raw_cleaned.compute_psd(picks='meg').plot(show=False)
    fig_psd_after.savefig(os.path.join(output_dir, "ica_psd.png"), dpi=150)
    plt.close(fig_psd_after)

def parse_arguments():
    parser = argparse.ArgumentParser(description="Apply ICA to remove artifact components from MEG data.")
    parser.add_argument('--raw_file', required=True, help='Path to the raw MEG file')
    parser.add_argument('--ica_file', required=True, help='Path to the ICA file')
    parser.add_argument('--exclude_file', required=True, help='Path to the text file specifying components to exclude')
    parser.add_argument('--output_file', required=True, help='Path to save the cleaned MEG file')
    parser.add_argument('--output_dir', required=True, help='Path to save quality assurance plots')
    parser.add_argument('--fname_bad_channels', required=True, help='Path to the bad channels file')
    parser.add_argument('--fname_bad_segments', required=True, help='Path to the bad segments file')
    return parser.parse_args()
def main():
    args = parse_arguments()
    apply_ica(
        args.raw_file,
        args.ica_file,
        args.exclude_file,
        args.output_file,
        args.output_dir,
        args.fname_bad_channels,
        args.fname_bad_segments,
    )

if __name__ == "__main__":
    main()
