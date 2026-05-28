#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MEG Preprocessing for a Single File.
"""
from argparse import ArgumentParser
from pathlib import Path
from osl_ephys import preprocessing, utils
# from osl import preprocessing, utils
import logging
import yaml  # To parse YAML from Nextflow input
import mne
import numpy as np
mne.viz.set_browser_backend('matplotlib')


def create_raw_with_dig_montage(headshape_file: str, raw: mne.io.Raw) -> mne.io.Raw:
    """
    Create a digitization montage and integrate it into an existing MNE Raw object
    from a headshape.pos file.

    Parameters:
    headshape_file (str): The path to the headshape.pos file.

    raw (mne.io.Raw): An MNE Raw object to integrate the digitization montage.

    Returns:
    mne.io.Raw: The updated Raw object with digitization information.
    """

    # Function to read headshape data from the provided file
    def read_headshape_file(file_path):
        # X, Y, Z coordinates (in cm)
        # https://megcore.nih.gov/images/a/a8/FileFormats.pdf#page=77.05
        with open(file_path, 'r') as file:
            lines = file.readlines()

        points = []
        names = []

        for line in lines:
            parts = line.split()
            if len(parts) == 4:  # Check for standard format: name, X, Y, Z coordinates
                name = parts[0]  # Get the name
                coords = list(map(float, parts[1:4]))  # Get X, Y, Z coordinates
                names.append(name)
                points.append(coords)

        return np.array(points), names

    # Step 1: Read headshape data from the specified file
    headshape_points, headshape_names = read_headshape_file(headshape_file)

    # Initialize variables to store coordinates of standard anatomical points
    nasion_coords = None
    lpa_coords = None
    rpa_coords = None
    hpi_points = []
    hsp_points = []
    hsp_names = []

    # Iterate through all points to identify standard anatomical points and HPI points
    for name, coords in zip(headshape_names, headshape_points):
        if name == 'Nasion':
            nasion_coords = coords
        elif name == 'LPA':
            lpa_coords = coords
        elif name == 'RPA':
            rpa_coords = coords
        elif name.startswith('HPI'):  # Check for HPI points
            hpi_points.append(coords)
        else:
            hsp_points.append(coords)
            hsp_names.append(name)

    # Convert HPI points and other headshape points to NumPy arrays
    hpi_points = np.array(hpi_points)
    hsp_points = np.array(hsp_points)

    # Create a digitization montage using make_dig_montage
    if nasion_coords is not None and lpa_coords is not None and rpa_coords is not None:
        dig_montage = mne.channels.make_dig_montage(
            nasion=nasion_coords / 100,
            lpa=lpa_coords / 100,
            rpa=rpa_coords / 100,
            hpi=hpi_points / 100,  # Register HPI points
            hsp=hsp_points / 100,  # Remaining headshape points
            coord_frame='head'  # Use 'head' coordinate system
        )
    else:
        raise ValueError("Nasion, LPA, and RPA points must be found in the headshape file.")

    # Integrate the digitization montage into the provided Raw object
    raw.set_montage(dig_montage, on_missing='warn')

    # Return the updated Raw object with digitization information
    return raw

def run_meg_preprocessing(file_path, preproc_dir, config, random_seed):
    """
    Run MEG preprocessing pipeline for a single file.

    Parameters
    ----------
    file_path : str
        Path to the raw MEG file.
    preproc_dir : str
        Directory to save preprocessed data.
    config : str
        YAML configuration string for preprocessing.
    random_seed : int
        Random Seed
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File {file_path} not found.")

    preprocessing.run_proc_batch(
        config=config,
        files=[str(file_path)],
        outdir=preproc_dir,
        overwrite=True,
        dask_client=False,
        random_seed=random_seed,
    )

    # Headshape Positions for CTF
    try:
        print("Headshape Positions for CTF...")
        base_name = file_path.stem # basename without the extension
        preproc_file_path = Path(preproc_dir) / base_name / f"{base_name}_preproc-raw.fif"

        # Get the current MEG file's directory and base name
        dir_name = file_path.parent
        current_base_name = file_path.name

        # Generate the path for the headshape position file, replacing the suffix with 'pos'
        # Extract sub and ses information from the file name
        parts = current_base_name.split('_')  # Split the file name by underscores
        sub_name = "_".join(
            part for part in parts if part.startswith("sub") or part.startswith("ses"))  # Keep only 'sub' and 'ses'

        headshape_file = dir_name / f"{sub_name}_headshape.pos"

        if headshape_file.exists() and headshape_file.is_file():

            # Create a digitization montage and update the Raw object
            raw = mne.io.read_raw(str(preproc_file_path), preload=True)
            raw_with_montage = create_raw_with_dig_montage(str(headshape_file), raw)
            raw_with_montage.save(preproc_file_path, overwrite=True)
            print(f"[HSP]Processed and saved the raw data to: {preproc_file_path}")

    except Exception as e:
        logging.exception(f"{e}")


if __name__ == "__main__":
    # Argument parser
    argp = ArgumentParser(description="Run MEG preprocessing for a single file.")
    argp.add_argument('--file', required=True, type=str, help='Path to the raw MEG file.')
    argp.add_argument('--preproc_dir', required=True, type=str, help='Directory to save preprocessed data.')
    argp.add_argument('--config', required=True, type=str, help='YAML configuration string for preprocessing.')
    argp.add_argument('--seed', required=False, default=2025, help='Random seed')

    args = argp.parse_args()

    try:
        random_seed = args.seed
        random_seed = int(random_seed)
    except Exception:
        random_seed = 2025

    # Directories
    file_path = args.file
    preproc_dir = Path(args.preproc_dir)
    preproc_dir.mkdir(parents=True, exist_ok=True)

    # Parse YAML configuration
    config = yaml.safe_load(args.config)

    # Run preprocessing
    run_meg_preprocessing(file_path, str(preproc_dir), config, random_seed)
