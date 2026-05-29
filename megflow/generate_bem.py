# !/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anatomy Data Preprocessing.
- 基于python调用Freesurfer的recon-all，以及BEM生成
"""
import os
import mne
import yaml
import argparse
from pathlib import Path
from mne.bem import make_watershed_bem
from utils import set_random_seed

set_random_seed(2025)

# 基于mne-python来计算边界元模型BEM
def gen_bem_from_anat(subject_dir, ico=4, conductivity=(0.3,),display=True,output_dir='.'):
    """
    Generate BEM model based on Freesurfer Results.

    Parameters
    ----------
    subject_dir:str
        - The full path to the subject directory, combining the Freesurfer root directory (SUBJECTS_DIR)
          and the subject name.
    ico:int
        - The surface ico(icosahedron) downsampling to use, e.g. 5=20484, 4=5120, 3=1280.
    conductivity:tuple
        - for single layer:(0.3,); for three layers:(0.3, 0.006, 0.3)
    display:bool
    display:bool
        - If True, display with GUI.
    """
    subject_dir = Path(subject_dir)
    subject_name = subject_dir.stem
    fs_root_dir = subject_dir.parent
    bem_path = subject_dir / 'bem'
    bem_path.mkdir(parents=True, exist_ok=True)

    fname_bem_surf = bem_path / f'{subject_name}_ico{ico}_watershed_bem.fif'
    fname_bem_sol = bem_path / f'{subject_name}_ico{ico}_watershed_bem-sol.fif'

    make_watershed_bem(subject=subject_name, subjects_dir=fs_root_dir, overwrite=True, volume='T1', atlas=True,
                       gcaatlas=False, show=False, copy=True)

    bem_surf = mne.make_bem_model(subject=subject_name, subjects_dir=fs_root_dir, ico=ico,
                                  conductivity=conductivity)  # for single layer:(0.3,); for three layers:(0.3, 0.006, 0.3)
    bem_sol = mne.make_bem_solution(surfs=bem_surf)

    mne.write_bem_surfaces(fname_bem_surf, bem_surf, overwrite=True)
    mne.write_bem_solution(fname=fname_bem_sol, bem=bem_sol, overwrite=True)

    for surface_name in ['pial', 'white']:
        fname_src_spac = bem_path / f'{subject_name}_ico{ico}_bem_{surface_name}_surface-src.fif'
        fname_vol_src_spac = bem_path / f'{subject_name}_ico{ico}_bem_{surface_name}_volume-src.fif'
        src_spac = mne.setup_source_space(subject=subject_name, subjects_dir=fs_root_dir, spacing=f'ico{ico}',
                                          surface=surface_name, add_dist="patch")
        vol_src_spac = mne.setup_volume_source_space(subject=subject_name, subjects_dir=fs_root_dir,
                                                     surface=fs_root_dir / subject_name / 'bem' / 'inner_skull.surf',
                                                     verbose=True)
        mne.write_source_spaces(fname_src_spac, src_spac, overwrite=True)
        mne.write_source_spaces(fname_vol_src_spac, vol_src_spac, overwrite=True)

    if display:
        plot_bem_kwargs = dict(subject=subject_name, subjects_dir=fs_root_dir, brain_surfaces='white',
                               orientation='coronal', slices=[50, 100, 150, 200],show=False)
        bem_fig = mne.viz.plot_bem(**plot_bem_kwargs)  # type: ignore
        bem_fig.savefig(os.path.join(output_dir,"bem_fig.png"), dpi=300)


if __name__ == "__main__":
    # Parse command line arguments using argparse
    parser = argparse.ArgumentParser(description="Generate BEM model based on Freesurfer Results")
    parser.add_argument('--subject_dir', type=str, required=True, help='Full path to the subject directory')
    parser.add_argument('--config', type=str, help='BEM parameters')
    parser.add_argument('--output_dir', type=str, default='.', help='output directory for BEM models')

    args = parser.parse_args()
    # Parse YAML configuration
    config = yaml.safe_load(args.config)
    ico = config.get("ico", 4)
    conductivity = config.get("conductivity",[0.3])

    # Call gen_bem_from_anat with arguments from the command line
    gen_bem_from_anat(args.subject_dir, ico=ico, conductivity=tuple(conductivity), output_dir=args.output_dir)