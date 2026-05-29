#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import mne
import logging
import matplotlib.pyplot as plt
from mne.minimum_norm import apply_inverse, make_inverse_operator
from mne.minimum_norm import apply_inverse_raw
from mne.beamformer import apply_lcmv_raw
from mne.beamformer import apply_lcmv, make_lcmv
import argparse
from utils import handle_yaml_scientific_notation,stop_xvfb,start_xvfb,set_random_seed,str2bool
import yaml
from pathlib import Path
import gc
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

set_random_seed(2025)

def get_n_rank(subj, sess_id, exclude_ica_file):
    """
    Calculate the n_rank for a given subject and session based on excluded ICA components.

    Parameters
    ----------
    subj : int
        The subject identifier.
    sess_id : int
        The session identifier.
    exclude_ica_file : str
        Path to the file containing the ICA components to exclude.

    Returns
    -------
    int
        The n_rank value for the given subject and session.
    """
    try:
        subj_name = f"sub-{subj:03d}_ses-{sess_id:03d}"

        # Read excluded ICA components from the file
        with open(exclude_ica_file, 'r') as file:
            excluded_ica = file.readlines()

        # Extract the excluded ICA components for the given subject
        excluded_ica = [comp.strip() for comp in excluded_ica if subj_name in comp]

        len_exclude_ica = len(excluded_ica)
        n_rank = 69 - len_exclude_ica - 1
    except KeyError:
        print(f"ICA components for {subj} session {sess_id} not found, setting n_rank=50.")
        n_rank = 50
    return n_rank


def compute_data_covariance(epochs, cov_tmin, cov_tmax, subj_src_path, epoch_label, n_rank):
    """
    Compute or read the covariance matrix from epochs within a given time window.

    Parameters
    ----------
    epochs : instance of Epochs
        The MEG epochs data.
    cov_tmin : float
        The start time for the covariance calculation.
    cov_tmax : float
        The end time for the covariance calculation.
    subj_src_path : str
        The directory path to save the covariance matrix.
    epoch_label : str
        The label for the epoch.
    n_rank : int
        The rank of the covariance matrix.
    """
    data_cov_fn = os.path.join(subj_src_path, f"{epoch_label}_tw_{cov_tmin}_{cov_tmax}_epoch-cov.fif")
    data_cov = mne.compute_covariance(epochs, tmin=cov_tmin, tmax=cov_tmax, method="auto", rank={'meg': n_rank})
    data_cov.save(data_cov_fn, overwrite=True)

    try:
        visualize_covariance_and_spectra(data_cov, epochs, subj_src_path)
    except Exception as e:
        logger.error(f"error occurred while visualizing:{e}")

def visualize_covariance_and_spectra(data_cov, raw_data, subj_src_path):
    """
    Visualize and save the noise covariance matrix and its spectra.

    Parameters
    ----------
    data_cov : instance of Covariance
        The data covariance matrix.
    raw_data : instance of Raw
        The raw MEG data.
    subj_src_path : str
        The directory path to save the plots.
    """
    cov_plot_path = os.path.join(subj_src_path, 'data_cov.png')
    spectra_plot_path = os.path.join(subj_src_path, 'data_cov_spectra.png')
    fig_cov, fig_spectra = mne.viz.plot_cov(data_cov, raw_data.info, show=False)
    fig_cov.savefig(cov_plot_path)
    fig_spectra.savefig(spectra_plot_path)
    plt.close('all')
    print(f"Saved covariance and spectra plots to {subj_src_path}")


def visualize_source_estimate(stc, subject, subjects_dir, subj_src_path, epoch, method, spacing, block):
    """
    Visualize and save the source estimate, showing the peak activation for both hemispheres.

    Parameters
    ----------
    stc : instance of SourceEstimate
        The source estimate to visualize (e.g., from dSPM or LCMV).
    subject : str
        The subject identifier.
    subjects_dir : str or Path
        The FreeSurfer subjects directory.
    subj_src_path : str or Path
        The path where the images should be saved.
    epoch : str
        The current epoch identifier.
    method : str
        The method used to generate the source estimate (e.g., 'dSPM' or 'LCMV').
    spacing : str
        The source space resolution (e.g., 'ico5').
    block : bool
        If True, interactive visualization.

    Returns
    -------
    None
    """
    display_number = start_xvfb(interactive=True)
    try:
        fig = mne.viz.create_3d_figure((10, 10))
        fig.plotter.close()
        plot_flag = True
    except Exception as e:
        logger.error(e)
        plot_flag = False
    if plot_flag:
        try:
            logger.info("visualize_source_estimate...")
            for hs in ['lh', 'rh']:  # Loop over left hemisphere and right hemisphere
                # Get the peak vertex and time for the current hemisphere
                vertno_max, time_max = stc.get_peak(hemi=hs)

                # Set up the plotting parameters
                surfer_kwargs = dict(
                    subject=subject,
                    hemi=hs,
                    subjects_dir=subjects_dir,
                    time_viewer=True,
                    show_traces=True,
                    clim=dict(kind="percent", pos_lims=[0, 97.5, 100]),  # Color limits
                    views="lateral",  # View from the side
                    initial_time=time_max,  # Time point of maximum activation
                    time_unit="s",
                    size=(1000, 800),  # Figure size
                    smoothing_steps=10,  # Smooth the data for visualization
                    brain_kwargs=dict(block=block, show=block)
                )

                # Create the brain visualization object
                brain = stc.plot(**surfer_kwargs)
                logger.info("visualize_source_estimate,stc.plot...")

                # Add the peak activation location as a blue foci on the brain
                brain.add_foci(
                    vertno_max,
                    coords_as_verts=True,
                    hemi=hs,
                    color="blue",
                    scale_factor=0.6,
                    alpha=0.5,
                )

                # Add a title to the figure
                brain.add_text(
                    0.1, 0.9, f"{method} (plus location of maximal activation)", "title", font_size=14
                )

                # Save the image to file
                output_file = os.path.join(subj_src_path, f"{epoch}_evoked_{method}-{spacing}-{hs}.png")
                brain.save_image(output_file)
                brain.close()

                print(f"Saved {method} brain plot for {hs} hemisphere to {output_file}")
        except Exception as e:
            logger.exception("visualize_source_estimate error: %s", e)

    try:
        mne.viz.close_all_3d_figures()
    except Exception:
        pass
    gc.collect()
    time.sleep(0.5)
    stop_xvfb(display_number)

def compute_minimum_norm(method, evoked, fwd, noise_cov, subj_src_path, subject_id, subjects_dir, epoch_label, spacing, config, visualize):
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
    print(f"**config.get('{method}')['inverse_operator']:",config.get(method)['inverse_operator'])
    inverse_operator = make_inverse_operator(info=evoked.info, forward=fwd, noise_cov=noise_cov,
                                             **config.get(method)['inverse_operator'])
    print(f"**config.get('{method}')['apply_inverse']：",config.get(method)['apply_inverse'])
    stc = apply_inverse(evoked, inverse_operator, **config.get(method)['apply_inverse'])
    stc.save(stc_file, overwrite=True)

    if visualize:
        visualize_source_estimate(stc, subject_id, subjects_dir, subj_src_path, epoch_label, method, spacing, block=False)


def compute_LCMV(evoked, fwd, data_cov, noise_cov, subj_src_path, subject_id, subjects_dir, epoch_label, spacing,
                 config, visualize):
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
    filters = make_lcmv(evoked.info, fwd, data_cov, noise_cov=noise_cov, **config.get('LCMV')['make_lcmv'])
    stc = apply_lcmv(evoked, filters)
    stc.save(stc_file, overwrite=True)
    if visualize:
        visualize_source_estimate(stc, subject_id, subjects_dir, subj_src_path, epoch_label, "LCMV", spacing, block=False)


def process_subject(epoch_file, fs_subjects_dir, noise_cov_path, fwd_dir, output_dir, config, visualize):
    """
    Process a single subject's data for source localization.

    Parameters
    ----------
    epoch_file : str
        Path to the epochs file.
    fs_subjects_dir : str
        Path to the FreeSurfer subjects directory.
    noise_cov_path : str
        Path to the noise covariance file.
    fwd_dir: str
        forward solution directory.
    output_dir : str
        The directory to save the results.
    config : dict
        The configuration dictionary with parameters for processing.

    Returns
    -------
    None
    """
    subject_id = Path(epoch_file).stem.split('_')[0]  # mri and meg file have the same subject id.
    epoch_label = config.get("epoch_label", "")
    try:
        spacing = config.get('spacing')

        # Load noise covariance
        meg_subject_id = Path(epoch_file).parent.name
        noise_cov_file = os.path.join(noise_cov_path, meg_subject_id, 'bl-cov.fif')
        noise_cov = mne.read_cov(noise_cov_file)

        # Read epochs and evoked data for "meg"
        epochs = mne.read_epochs(epoch_file)
        evoked = epochs.average().pick(config.get('data_type'))

        # Load forward solution
        fwd = mne.read_forward_solution(os.path.join(fwd_dir, meg_subject_id, f"{epoch_label}_{spacing}-fwd.fif"))

        for method in config.get("source_methods"):
            # Compute minimum-norm inverse
            if method in ["MNE","dSPM","sLORETA","eLORETA"]:
                compute_minimum_norm(method, evoked, fwd, noise_cov, output_dir, subject_id, fs_subjects_dir, epoch_label, spacing, config, visualize)

        if 'LCMV' in config.get("source_methods"):
            n_rank = config.get('LCMV')['n_rank']
            cov_tmin = config.get('LCMV')['cov_tmin']
            cov_tmax = config.get('LCMV')['cov_tmax']

            # Compute data covariance for LCMV
            data_cov = compute_data_covariance(epochs, cov_tmin, cov_tmax, output_dir, epoch_label, n_rank)

            # Compute LCMV
            compute_LCMV(evoked, fwd, data_cov, noise_cov, output_dir, subject_id, fs_subjects_dir, epoch_label,
                         spacing, config, visualize)

    except Exception as e:
        print(f"Error processing subject {subject_id}: {e}")


def process_raw(raw_file, fs_subjects_dir, noise_cov_path, fwd_dir, output_dir, config, visualize):
    """
    Process continuous (raw) data for source localization.
    """
    subject_id = Path(raw_file).stem.split('_')[0]
    spacing = config.get('spacing')
    epoch_label = config.get("epoch_label", "")

    try:
        meg_subject_id = Path(raw_file).parent.name
        noise_cov_file = os.path.join(noise_cov_path, meg_subject_id, 'bl-cov.fif')
        noise_cov = mne.read_cov(noise_cov_file)

        raw = mne.io.read_raw_fif(raw_file, preload=True)
        fwd = mne.read_forward_solution(os.path.join(fwd_dir, meg_subject_id, f"{epoch_label}_{spacing}-fwd.fif"))

        # minimum_norm algorithms
        # “MNE” | “dSPM” | “sLORETA” | “eLORETA”
        for method in config.get("source_methods"):
            # Compute minimum-norm inverse
            if method in ["MNE", "dSPM", "sLORETA", "eLORETA"]:
                inverse_operator = make_inverse_operator(info=raw.info, forward=fwd, noise_cov=noise_cov,
                                                         **config.get(method)['inverse_operator'])
                stc = apply_inverse_raw(raw, inverse_operator,
                                        **config.get(method)['apply_inverse'])
                stc.save(os.path.join(output_dir, f"{epoch_label}_raw_{method}-{spacing}"), overwrite=True)
                if visualize:
                    visualize_source_estimate(stc, subject_id, fs_subjects_dir, output_dir, epoch_label, method, spacing, block=False)

        if 'LCMV' in config.get("source_methods"):
            n_rank = config.get('LCMV')['n_rank']
            cov_tmin = config.get('LCMV')['cov_tmin']
            cov_tmax = config.get('LCMV')['cov_tmax']
            data_cov = mne.compute_raw_covariance(raw, tmin=cov_tmin, tmax=cov_tmax, method="auto", rank=n_rank)
            filters = make_lcmv(raw.info, fwd, data_cov, noise_cov=noise_cov, **config.get('LCMV')['make_lcmv'])
            stc = apply_lcmv_raw(raw, filters)
            stc.save(os.path.join(output_dir, f"{epoch_label}_raw_LCMV-{spacing}"), overwrite=True)
            if visualize:
                visualize_source_estimate(stc, subject_id, fs_subjects_dir, output_dir, epoch_label, "LCMV", spacing, block=False)
    except Exception as e:
        logger.error(f"Error processing raw data for subject {subject_id}: {e}")


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
    parser.add_argument('--noise_covariance_dir', type=str, required=True,
                        help="Directory to the noise covariance file.")
    parser.add_argument('--forward_dir', type=str, required=True, help="Directory to the forward solution.")
    parser.add_argument('--output_dir', type=str, required=True, help="Subject output directory.")
    parser.add_argument('--config', type=str, help="Configuration parameters.")
    parser.add_argument('--visualize', type=str2bool, nargs='?', const=True, default=True, help="Whether to visualize the source imaging (default: True)")

    return parser.parse_args()


def main():
    """
    Main function to run the source localization for a single subject.
    """
    # os.environ["MESA_GLSL_VERSION_OVERRIDE"] = "150"
    # os.environ["MESA_GL_VERSION_OVERRIDE"] = "3.2"
    # os.environ['DISPLAY'] = ':99'  # Set environment for pyvista backend drawing.
    # os.environ["QT_QPA_PLATFORM"] = "xcb"

    args = parse_arguments()
    handle_yaml_scientific_notation()

    Path(args.output_dir).mkdir(exist_ok=True, parents=True)

    # Example configuration (this should be loaded from a file in a real scenario)
#     args.config = """
# source_methods:
#     - dSPM
#     # - LCMV
#
# data_type: meg  # mag
# spacing: ico4
# epoch_label: wdonset
# dSPM:
#     inverse_operator:
#         loose: auto
#         depth: 0.8
#         fixed: auto
#         rank: null
#     apply_inverse:
#         lambda2: 0.111111111111
#         method: dSPM
#         pick_ori: normal
#
# LCMV:
#     n_rank: info
#     cov_tmin: 0.01
#     cov_tmax: 0.4
#     make_lcmv:
#         reg: 0.05
#         pick_ori: null
#         rank: info
#         weight_norm: unit-noise-gain-invariant
# """
    config = yaml.safe_load(args.config)
    if args.data_mode == "raw":
        process_raw(args.data_file,
                    args.fs_subjects_dir,
                    args.noise_covariance_dir,
                    args.forward_dir,
                    args.output_dir,
                    config,
                    args.visualize)
    elif args.data_mode == "epochs":
        process_subject(args.data_file,
                        args.fs_subjects_dir,
                        args.noise_covariance_dir,
                        args.forward_dir,
                        args.output_dir,
                        config,
                        args.visualize)
    else:
        raise ValueError("Unspported data mode: {}".format(args.data_mode))
    print("Finished source recon processing...")

if __name__ == "__main__":
    main()
