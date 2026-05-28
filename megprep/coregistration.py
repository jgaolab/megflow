# !/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Step1: Perform automated coregistration using existing algorithms.
Step2: Enhance algorithms for higher precision, formatted reports, and streamlined workflows.
"""
import os
import yaml
import argparse
import numpy as np
import pandas as pd
import mne
from mne.coreg import Coregistration
from pathlib import Path
from utils import start_xvfb, stop_xvfb, set_random_seed, str2bool
import logging
import time
import gc




# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# set random seed
set_random_seed(2025)


def perform_coregistration(raw_file_path, subjects_dir, fiducials="estimated", fiducials_file=None,
                           output_dir='.', config=None, visualize=False):
    """
    Perform automated MEG-MRI coregistration, fit fiducials, and ICP registration.
    """
    logger.info("Loading raw MEG data...")
    raw = mne.io.read_raw_fif(raw_file_path, verbose=False)
    info = raw.info
    output_dir = Path(output_dir)

    subject = Path(subjects_dir).stem
    fs_subjects_dir = Path(subjects_dir).parent

    logger.info(f"Subject ID: {subject}")
    save_trans_path = output_dir / "coreg-trans.fif"

    if os.path.exists(save_trans_path):
        print(f"The file {save_trans_path} already exists, and the data will not be overwritten.")
    else:

        # Handle fiducials
        if fiducials == "manual" and fiducials_file:
            if not Path(fiducials_file).exists():
                raise FileNotFoundError(f"Fiducials file {fiducials_file} does not exist.")
            fiducials_data = np.loadtxt(fiducials_file)
            fiducials_dict = {
                'nasion': fiducials_data[0],
                'lpa': fiducials_data[1],
                'rpa': fiducials_data[2]
            }
            coreg = Coregistration(info, subject, fs_subjects_dir, fiducials=fiducials_dict)
            logger.info("Using manual fiducials.")
        else:
            coreg = Coregistration(info, subject, fs_subjects_dir, fiducials=fiducials)
            logger.info("Using estimated fiducials.")

        # Base Plotting arguments
        # 'surfaces' will be dynamically modified in the loop
        base_plot_kwargs = dict(
            subject=subject,
            subjects_dir=fs_subjects_dir,
            dig=True,  # Ensure Head Points are drawn
            mri_fiducials='estimated',
            meg={"helmet": 0, "sensors": 0, 'ref': 1},
            coord_frame="mri",
        )

        plot_flag = visualize
        display_number = None

        if plot_flag:
            try:
                display_number = start_xvfb()
                fig = mne.viz.create_3d_figure((10, 10))
                fig.plotter.close()
            except Exception as e:
                logger.error(f"Visualization setup failed: {e}")
                plot_flag = False

        view_configs = [("head-dense", ""), ("white", "_brain")]

        # black = (0.0, 0.0, 0.0)
        white = (1.0, 1.0, 1.0)
        # gray = (0.9, 0.9, 0.9)
        point_color = (0.3, 0.3, 0.3) #deep_gray

        # modify default code of mne. !important
        mne.defaults.DEFAULTS['coreg']['extra_color'] = point_color
        from mne.viz._3d import _plot_head_shape_points
        func = _plot_head_shape_points
        if hasattr(func, '__defaults__'):
            defaults = list(func.__defaults__)
            defaults[0] = 1
            func.__defaults__ = tuple(defaults)

        # ==========================================
        # 1. Initial Alignment
        # ==========================================
        if plot_flag:
            for surf, suffix in view_configs:
                try:
                    logger.info(f"Plotting initial alignment (Surface: {surf})...")

                    current_kwargs = base_plot_kwargs.copy()
                    current_kwargs['surfaces'] = surf

                    fig = mne.viz.create_3d_figure((400, 400), bgcolor=white)

                    mne.viz.plot_alignment(info, fig=fig, trans=coreg.trans, **current_kwargs)

                    fig.plotter.screenshot(output_dir / f"{subject}_coreg_initial{suffix}.png")
                    fig.plotter.close()
                except Exception as e:
                    logger.error(f"Error plotting initial {suffix}: {e}")
                finally:
                    gc.collect()
                    time.sleep(0.2)

        # ==========================================
        # 2. Fit Fiducials
        # ==========================================
        logger.info("Fitting fiducials...")
        coreg.fit_fiducials(verbose=True)

        if plot_flag:
            for surf, suffix in view_configs:
                try:
                    logger.info(f"Plotting coreg_fiducials (Surface: {surf})...")

                    current_kwargs = base_plot_kwargs.copy()
                    current_kwargs['surfaces'] = surf

                    fig = mne.viz.create_3d_figure((400, 400), bgcolor=white)
                    mne.viz.plot_alignment(info, fig=fig, trans=coreg.trans, **current_kwargs)

                    fig.plotter.screenshot(output_dir / f"{subject}_coreg_fiducials{suffix}.png")
                    fig.plotter.close()
                except Exception as e:
                    logger.error(f"Error plotting fiducials {suffix}: {e}")
                finally:
                    gc.collect()
                    time.sleep(0.2)

        # ==========================================
        # 3. ICP Registration
        # ==========================================
        logger.info("Performing ICP registration...")
        print("config.get('grow_hair', 0):", config.get('grow_hair', 0))
        coreg.set_grow_hair(config.get('grow_hair', 0))
        coreg.omit_head_shape_points(distance=config.get('omit_head_shape_points', 5.0) / 1000)
        coreg.fit_icp(**config.get('icp'))

        if plot_flag:
            for surf, suffix in view_configs:
                try:
                    logger.info(f"Plotting coreg_icp (Surface: {surf})...")

                    current_kwargs = base_plot_kwargs.copy()
                    current_kwargs['surfaces'] = surf

                    fig = mne.viz.create_3d_figure((400, 400), bgcolor=white)
                    mne.viz.plot_alignment(info, fig=fig, trans=coreg.trans, **current_kwargs)

                    fig.plotter.screenshot(output_dir / f"{subject}_coreg_icp{suffix}.png")
                    fig.plotter.close()
                except Exception as e:
                    logger.error(f"Error plotting ICP {suffix}: {e}")
                finally:
                    gc.collect()
                    time.sleep(0.2)

        # ==========================================
        # 4. Fine tune registration
        # ==========================================
        logger.info("Fine tuning ICP registration...")
        try:
            coreg.fit_icp(**config.get('finetune_icp'))
        except ValueError as e:
            logger.error(f"ValueError: Internal algorithm failed to converge.{e}")
            print(coreg.trans)

        if plot_flag:
            for surf, suffix in view_configs:
                try:
                    logger.info(f"Plotting coreg_icp_finetune (Surface: {surf})...")

                    current_kwargs = base_plot_kwargs.copy()
                    current_kwargs['surfaces'] = surf

                    fig = mne.viz.create_3d_figure((400, 400), bgcolor=white)
                    mne.viz.plot_alignment(info, fig=fig, trans=coreg.trans, **current_kwargs)

                    # Set the 3D view (optional, kept from original)
                    # view_kwargs = dict(azimuth=45, elevation=90, distance=0.6, focalpoint=(0.0, 0.0, 0.0))
                    # mne.viz.set_3d_view(fig, **view_kwargs)

                    fig.plotter.screenshot(output_dir / f"{subject}_coreg_icp_finetune{suffix}.png")
                    fig.plotter.close()
                except Exception as e:
                    logger.error(f"Error plotting finetune {suffix}: {e}")
                finally:
                    gc.collect()
                    time.sleep(0.2)

        # Compute distances between HSP and MRI
        dists = coreg.compute_dig_mri_distances() * 1e3  # Convert to mm
        logger.info(
            f"Distance between HSP and MRI (mean/min/max): {np.mean(dists):.2f} mm / {np.min(dists):.2f} mm / {np.max(dists):.2f} mm"
        )

        # Save distance metrics
        dists_df = pd.DataFrame({
            "dist_min(mm)": [f"{np.min(dists):.2f}"],
            "dist_max(mm)": [f"{np.max(dists):.2f}"],
            "dist_mean(mm)": [f"{np.mean(dists):.2f}"]
        })
        dists_df.to_csv(output_dir / "dists.csv", index=False)

        # Save transformation matrix
        mne.write_trans(save_trans_path, coreg.trans, overwrite=True)
        logger.info(f"Transformation matrix saved to {save_trans_path}")

        if display_number is not None:
            try:
                mne.viz.close_all_3d_figures()
            except Exception:
                pass
            gc.collect()
            time.sleep(0.5)
            stop_xvfb(display_number)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Automated Coregistration for MEG and MRI data.")

    parser.add_argument('--raw_file', required=True, type=str, help='Path to the raw MEG file')
    parser.add_argument('--subjects_dir', required=True, type=str, help='Path to the subjects directory')
    parser.add_argument('--fiducials', default="estimated", type=str, choices=["estimated", "manual"],
                        help='Type of fiducials to use ("estimated" or "manual")')
    parser.add_argument('--fiducials_file', type=str,
                        help='Path to the file containing manual fiducial coordinates (required if --fiducials is "manual")')
    parser.add_argument('--output_dir', type=str, help='Path to save the transformation and figures')
    parser.add_argument('--config', type=str, help='Path to the YAML configuration file')
    parser.add_argument('--visualize', type=str2bool, nargs='?', const=True, default=True,
                        help="Whether to visualize the coregistration (default: True)")
    return parser.parse_args()


def main():
    args = parse_arguments()

    # Validate output directory
    output_dir_path = Path(args.output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    # debug coreg
    # core_config = """
    # omit_head_shape_points: 1 # mm
    # grow_hair: 0.0 #mm
    # icp:
    #     n_iterations: 200
    #     lpa_weight: 1.0
    #     nasion_weight: 10.0
    #     rpa_weight: 1.0
    #     hsp_weight: 10.0
    #     eeg_weight: 0.0
    #     hpi_weight: 1.0
    # finetune_icp:
    #     n_iterations: 200
    #     lpa_weight: 0.0
    #     nasion_weight: 0.0
    #     rpa_weight: 0.0
    #     hsp_weight: 10.0
    #     eeg_weight: 0.0
    #     hpi_weight: 0.0
    # """
    # args.config = core_config

    # Set environ params for stability
    os.environ["MESA_GLSL_VERSION_OVERRIDE"] = "150"
    os.environ["MESA_GL_VERSION_OVERRIDE"] = "3.2"

    # Parse YAML configuration
    config = yaml.safe_load(args.config)

    # Perform the coregistration
    perform_coregistration(
        raw_file_path=args.raw_file,
        subjects_dir=args.subjects_dir,
        fiducials=args.fiducials,
        fiducials_file=args.fiducials_file,
        output_dir=output_dir_path,
        config=config,
        visualize=args.visualize
    )


if __name__ == "__main__":
    main()