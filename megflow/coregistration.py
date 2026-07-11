# !/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Step1: Perform automated coregistration using existing algorithms.
Step2: Enhance algorithms for higher precision, formatted reports, and streamlined workflows.
"""
import os
import yaml
import argparse
import copy
import shutil
import subprocess
import sys
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


def configure_coreg_plot_defaults():
    point_color = (0.3, 0.3, 0.3)
    mne.defaults.DEFAULTS['coreg']['extra_color'] = point_color
    from mne.viz._3d import _plot_head_shape_points
    func = _plot_head_shape_points
    if hasattr(func, '__defaults__'):
        defaults = list(func.__defaults__)
        defaults[0] = 1
        func.__defaults__ = tuple(defaults)


def plot_coregistration_figure(raw_file_path, subjects_dir, trans_file, output_png, surface):
    raw = mne.io.read_raw_fif(raw_file_path, verbose=False)
    info = raw.info
    subject = Path(subjects_dir).stem
    fs_subjects_dir = Path(subjects_dir).parent
    display_number = None
    fig = None

    configure_coreg_plot_defaults()
    try:
        display_number = start_xvfb()
        fig = mne.viz.create_3d_figure((10, 10))
        fig.plotter.close()
        fig = None

        trans = mne.read_trans(trans_file)
        fig = mne.viz.create_3d_figure((400, 400), bgcolor=(1.0, 1.0, 1.0))
        mne.viz.plot_alignment(
            info,
            fig=fig,
            trans=trans,
            subject=subject,
            subjects_dir=fs_subjects_dir,
            dig=True,
            mri_fiducials='estimated',
            meg={"helmet": 0, "sensors": 0, 'ref': 1},
            coord_frame="mri",
            surfaces=surface,
        )
        fig.plotter.screenshot(output_png)
        fig.plotter.close()
    finally:
        if fig is not None:
            try:
                fig.plotter.close()
            except Exception:
                pass
        if display_number is not None:
            try:
                mne.viz.close_all_3d_figures()
            except Exception:
                pass
            gc.collect()
            time.sleep(0.5)
            stop_xvfb(display_number)


def run_plot_subprocess(raw_file_path, subjects_dir, output_dir, subject, stage, trans, surface, suffix):
    trans_path = output_dir / f".{subject}_{stage}{suffix}-trans.fif"
    output_png = output_dir / f"{subject}_{stage}{suffix}.png"
    mne.write_trans(trans_path, trans, overwrite=True)

    cmd = [
        sys.executable,
        __file__,
        "--plot_only",
        "--raw_file",
        str(raw_file_path),
        "--subjects_dir",
        str(subjects_dir),
        "--plot_trans_file",
        str(trans_path),
        "--plot_surface",
        str(surface),
        "--plot_output_png",
        str(output_png),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            stderr_tail = "\n".join((result.stderr or "").splitlines()[-8:])
            logger.error(
                f"Coregistration figure skipped for {stage}{suffix} "
                f"(surface={surface}, exit={result.returncode}). {stderr_tail}"
            )
    except subprocess.TimeoutExpired:
        logger.error(f"Coregistration figure timed out for {stage}{suffix} (surface={surface}).")
    finally:
        try:
            trans_path.unlink()
        except FileNotFoundError:
            pass


def perform_coregistration(raw_file_path, subjects_dir, fiducials="estimated", fiducials_file=None,
                           output_dir='.', config=None, visualize=False, supplied_trans_file=None):
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
    view_configs = [("head-dense", ""), ("white", "_brain")]
    configure_coreg_plot_defaults()

    if os.path.exists(save_trans_path):
        print(f"The file {save_trans_path} already exists, and the data will not be overwritten.")
        if visualize:
            trans = mne.read_trans(save_trans_path)
            for surf, suffix in view_configs:
                figure_path = output_dir / f"{subject}_coreg_icp_finetune{suffix}.png"
                if figure_path.exists():
                    continue
                logger.info(f"Plotting saved coregistration transform (Surface: {surf})...")
                run_plot_subprocess(raw_file_path, subjects_dir, output_dir, subject, "coreg_icp_finetune", trans, surf, suffix)
    elif supplied_trans_file:
        supplied_trans_path = Path(supplied_trans_file)
        if not supplied_trans_path.exists():
            raise FileNotFoundError(f"Supplied transform file {supplied_trans_path} does not exist.")

        shutil.copy2(supplied_trans_path, save_trans_path)
        logger.info(f"Using supplied coregistration transform: {supplied_trans_path}")
        logger.info(f"Transformation matrix saved to {save_trans_path}")

        if visualize:
            trans = mne.read_trans(save_trans_path)
            for surf, suffix in view_configs:
                logger.info(f"Plotting supplied coregistration transform (Surface: {surf})...")
                run_plot_subprocess(raw_file_path, subjects_dir, output_dir, subject, "coreg_icp_finetune", trans, surf, suffix)
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

        trans_snapshots = [("coreg_initial", copy.deepcopy(coreg.trans))]

        # ==========================================
        # 2. Fit Fiducials
        # ==========================================
        logger.info("Fitting fiducials...")
        coreg.fit_fiducials(verbose=True)
        trans_snapshots.append(("coreg_fiducials", copy.deepcopy(coreg.trans)))

        # ==========================================
        # 3. ICP Registration
        # ==========================================
        logger.info("Performing ICP registration...")
        print("config.get('grow_hair', 0):", config.get('grow_hair', 0))
        coreg.set_grow_hair(config.get('grow_hair', 0))
        coreg.omit_head_shape_points(distance=config.get('omit_head_shape_points', 5.0) / 1000)
        coreg.fit_icp(**config.get('icp'))
        trans_snapshots.append(("coreg_icp", copy.deepcopy(coreg.trans)))

        # ==========================================
        # 4. Fine tune registration
        # ==========================================
        logger.info("Fine tuning ICP registration...")
        try:
            coreg.fit_icp(**config.get('finetune_icp'))
        except ValueError as e:
            logger.error(f"ValueError: Internal algorithm failed to converge.{e}")
            print(coreg.trans)
        trans_snapshots.append(("coreg_icp_finetune", copy.deepcopy(coreg.trans)))

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

        if visualize:
            for stage, trans in trans_snapshots:
                for surf, suffix in view_configs:
                    logger.info(f"Plotting {stage} (Surface: {surf})...")
                    run_plot_subprocess(raw_file_path, subjects_dir, output_dir, subject, stage, trans, surf, suffix)


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
    parser.add_argument('--supplied_trans_file', type=str,
                        help='Use an existing head-MRI transform instead of running automated coregistration')
    parser.add_argument('--plot_only', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--plot_trans_file', type=str, help=argparse.SUPPRESS)
    parser.add_argument('--plot_surface', type=str, help=argparse.SUPPRESS)
    parser.add_argument('--plot_output_png', type=str, help=argparse.SUPPRESS)
    return parser.parse_args()


def main():
    args = parse_arguments()

    if args.plot_only:
        plot_coregistration_figure(
            args.raw_file,
            args.subjects_dir,
            args.plot_trans_file,
            args.plot_output_png,
            args.plot_surface,
        )
        return

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
        visualize=args.visualize,
        supplied_trans_file=args.supplied_trans_file
    )


if __name__ == "__main__":
    main()
