#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import mne
import argparse
import sys
from utils import handle_yaml_scientific_notation,set_random_seed
import yaml
from pathlib import Path

set_random_seed(2025)

def compute_forward_solution(subj_epoch_file, trans, src, bem, fwd_file):
    """
    Compute the forward solution and save it if not already saved.

    Parameters
    ----------
    subj_epoch_file : str or Path
        The path to the subject's epoch file.
    trans : str or instance of mne.transforms.Transform
        The MRI to head coordinate transformation.
    src : instance of mne.SourceSpaces
        The source space object.
    bem : instance of mne.ConductorModel
        The BEM solution.
    fwd_file : str or Path
        The name of forward solution.

    Returns
    -------
    fwd : instance of mne.Forward
        The computed forward solution.
    """
    fwd = mne.make_forward_solution(
        subj_epoch_file, trans=trans, src=src, bem=bem, meg=True, eeg=False, mindist=5.0, n_jobs=None
    )
    mne.write_forward_solution(fwd_file, fwd, overwrite=True)

    return fwd

def plot_all_bem_slices(subject, subjects_dir, orientations=['coronal', 'sagittal', 'axial'], output='.'):
    """
    Plot all slices of the BEM (Boundary Element Model) for specified orientations: coronal, sagittal, and axial.

    Parameters:
    - subject: Name of the subject
    - subjects_dir: Path to the subject data
    - orientations: List of orientations to plot, supports 'coronal', 'sagittal', 'axial'
    """
    # Loop through each orientation and plot all slices
    for orientation in orientations:
        # BEM plotting parameters
        slices = list(range(1, 235, 6))
        fig = mne.viz.plot_bem(subject=subject,
                               subjects_dir=subjects_dir,
                               orientation=orientation,
                               brain_surfaces=["white"],
                               slices=slices,
                               show_indices=True,
                               show_orientation=True,
                               show=False)

        fig.savefig(os.path.join(output,f"headmodel_{orientation}.png"))

def parse_arguments():
    """
    Parse command line arguments.
    """
    parser = argparse.ArgumentParser(description="Compute and save forward solution for MEG data.")
    parser.add_argument('--epoch_file', type=str, required=True, help="Epoch file")
    parser.add_argument('--trans_file', type=str, required=True, help="Trans file")
    parser.add_argument('--epoch_label', type=str, default='epochs',help="Epoch label (e.g., 'wdonset')")
    parser.add_argument('--mri_subject_dir', type=str, required=True, help="BEM solution file path")
    parser.add_argument('--output_dir', type=str, required=True, help="Path for output files")
    parser.add_argument('--config', type=str, help="parameters for forward solution (e.g., 'ico4')")

    return parser.parse_args()


def main():
    """
    Main function to compute and save the forward solution for MEG data.
    """
    # Parse command-line arguments
    args = parse_arguments()

    # Handle YAML scientific notation
    handle_yaml_scientific_notation()

    # Ensure output directory exists
    Path(args.output_dir).mkdir(exist_ok=True, parents=True)

    # Load YAML configuration |For TEST
    # args.config = """
    #     surface: white # pial
    #     spacing: ico4
    # """
    config = yaml.safe_load(args.config)
    print(config)

    # Define paths to necessary files
    trans = mne.read_trans(args.trans_file)

    spacing = config.get('spacing')
    surface_name = config.get('surface')
    mri_subject_dir = Path(args.mri_subject_dir)
    subjects_dir = mri_subject_dir.parent
    subj_name = mri_subject_dir.stem

    # Setup source space and BEM model paths
    src_space_fif = os.path.join(subjects_dir, subj_name, "bem",
                                  f"{subj_name}_{spacing}_bem_{surface_name}_surface-src.fif")  # Source space
    bem_fif = os.path.join(subjects_dir, subj_name, "bem",
                           f"{subj_name}_{spacing}_watershed_bem-sol.fif")

    # Load source space and BEM model
    if not os.path.exists(src_space_fif) or not os.path.exists(bem_fif):
        print(f"{src_space_fif} or {bem_fif} is missing, exiting...")
        sys.exit(-1)

    src = mne.read_source_spaces(src_space_fif)
    bem = mne.read_bem_solution(bem_fif)

    # Define the forward solution output path
    subj_fwd_file = os.path.join(args.output_dir, f"{args.epoch_label}_{spacing}-fwd.fif")

    # Compute forward solution
    compute_forward_solution(args.epoch_file, trans, src, bem, subj_fwd_file)

    try:
        # Call the plot function to plot all slices
        plot_all_bem_slices(subj_name, subjects_dir,orientations=['coronal', 'sagittal', 'axial'],output=args.output_dir)
    except Exception as e:
        print("headmodel visualization error:", e)

    print(f"Forward solution saved to: {subj_fwd_file}")



if __name__ == "__main__":
    main()
