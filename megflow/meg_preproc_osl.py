#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MEG Preprocessing for a Single File.
"""
from argparse import ArgumentParser
from copy import deepcopy
from pathlib import Path
from osl_ephys import preprocessing, utils
# from osl import preprocessing, utils
import logging
import json
import yaml  # To parse YAML from Nextflow input
import mne
import numpy as np
from mne.io.constants import FIFF
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


def _read_numeric_pos_file(pos_file: Path) -> np.ndarray:
    """Read FastSCAN-style numeric x/y/z rows and return coordinates in meters."""
    points = []
    with pos_file.open('r', encoding='utf-8-sig') as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith('%') or stripped.startswith('#'):
                continue
            parts = stripped.split()
            if len(parts) < 3:
                continue
            try:
                points.append([float(parts[0]), float(parts[1]), float(parts[2])])
            except ValueError:
                continue

    if not points:
        raise ValueError(f"No numeric x/y/z rows found in {pos_file}")

    coords = np.asarray(points, dtype=float)
    if np.nanmax(np.abs(coords)) > 1.0:
        coords = coords / 1000.0
    return coords


def _load_coordsystem(coordsystem_file: Path) -> dict:
    with coordsystem_file.open('r', encoding='utf-8-sig') as handle:
        return json.load(handle)


def _load_coordsystem_points(coordsystem_file: Path) -> dict:
    coordsystem = _load_coordsystem(coordsystem_file)

    merged = {}
    for section in ('AnatomicalLandmarkCoordinates', 'HeadCoilCoordinates'):
        for name, coords in (coordsystem.get(section) or {}).items():
            merged[name] = np.asarray(coords, dtype=float)
    return merged


def _rigid_transform(source: np.ndarray, target: np.ndarray):
    """Return rotation and translation that maps source points onto target points."""
    source_centroid = source.mean(axis=0)
    target_centroid = target.mean(axis=0)
    source_centered = source - source_centroid
    target_centered = target - target_centroid

    u, _, vt = np.linalg.svd(source_centered.T @ target_centered)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1, :] *= -1
        rotation = vt.T @ u.T
    translation = target_centroid - rotation @ source_centroid
    return rotation, translation


def _apply_transform(points: np.ndarray, rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    return (rotation @ points.T).T + translation


def _parse_bids_entities(file_path: Path) -> dict:
    entities = {}
    stem = file_path.name
    for suffix in file_path.suffixes:
        stem = stem[:-len(suffix)]
    for part in stem.split('_'):
        if '-' not in part:
            continue
        key, value = part.split('-', 1)
        entities[key] = value
    return entities


def _bids_prefix_candidates(file_path: Path):
    entities = _parse_bids_entities(file_path)
    ordered_keys = ['sub', 'ses', 'task', 'acq', 'run', 'proc', 'space', 'split']
    parts = [f"{key}-{entities[key]}" for key in ordered_keys if key in entities]
    return ["_".join(parts[:idx]) for idx in range(len(parts), 0, -1)]


def _pattern_candidates(pattern, prefix: str):
    if not pattern:
        return []
    if '{prefix}' in pattern:
        return [pattern.replace('{prefix}', prefix)]
    return [pattern]


def _find_first_matching_file(base_dir: Path, patterns):
    for pattern in patterns:
        path = Path(pattern)
        if path.is_absolute() and path.is_file():
            return path
        matches = sorted(base_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def _digitized_head_points_from_coordsystem(coordsystem_file: Path):
    coordsystem = _load_coordsystem(coordsystem_file)
    points_file = coordsystem.get('DigitizedHeadPoints')
    if not points_file:
        return None
    points_path = Path(points_file)
    if not points_path.is_absolute():
        points_path = coordsystem_file.parent / points_path
    return points_path if points_path.is_file() else None


def _find_bids_digitization_sidecars(file_path: Path, digitization_config: dict):
    meg_dir = file_path.parent
    prefixes = _bids_prefix_candidates(file_path)
    if not prefixes:
        return None

    coordsystem_pattern = digitization_config.get('coordsystem_file_pattern', '{prefix}_coordsystem.json')
    hsp_pattern = digitization_config.get('hsp_file_pattern', '{prefix}_headshape.pos')
    elp_pattern = digitization_config.get('elp_file_pattern')

    for prefix in prefixes:
        coordsystem_file = _find_first_matching_file(
            meg_dir,
            _pattern_candidates(coordsystem_pattern, prefix),
        )
        if not coordsystem_file:
            continue

        hsp_file = _digitized_head_points_from_coordsystem(coordsystem_file)
        if not hsp_file:
            hsp_file = _find_first_matching_file(
                meg_dir,
                _pattern_candidates(hsp_pattern, prefix),
            )

        elp_file = _find_first_matching_file(
            meg_dir,
            _pattern_candidates(elp_pattern, prefix),
        )

        return hsp_file, elp_file, coordsystem_file

    return None


def create_raw_with_bids_digitization(
    hsp_file,
    elp_file,
    coordsystem_file: str,
    raw: mne.io.Raw,
) -> mne.io.Raw:
    """Attach BIDS-compatible digitization sidecars to a Raw object."""
    coordsystem_points = _load_coordsystem_points(Path(coordsystem_file))

    landmark_names = ['NAS', 'LPA', 'RPA', 'coil1', 'coil2', 'coil3', 'coil4', 'coil5']
    available_names = [name for name in landmark_names if name in coordsystem_points]
    if len(available_names) < 3:
        raise ValueError(f"Need at least NAS/LPA/RPA landmarks in {coordsystem_file}")

    hsp_head = None
    if hsp_file:
        hsp_points = _read_numeric_pos_file(Path(hsp_file))
        if elp_file:
            elp_points = _read_numeric_pos_file(Path(elp_file))
            if len(elp_points) < len(available_names):
                raise ValueError(
                    f"{elp_file} has {len(elp_points)} points, but {len(available_names)} "
                    "landmark/head-coil points are required."
                )
            source = elp_points[:len(available_names)]
            target = np.asarray([coordsystem_points[name] for name in available_names], dtype=float)
            rotation, translation = _rigid_transform(source, target)
            hsp_head = _apply_transform(hsp_points, rotation, translation)
        else:
            print(
                "No ELP/fiducial sidecar configured; using HSP points as already "
                "being in the coordsystem/head coordinate frame."
            )
            hsp_head = hsp_points

    dig_montage = mne.channels.make_dig_montage(
        nasion=coordsystem_points.get('NAS'),
        lpa=coordsystem_points.get('LPA'),
        rpa=coordsystem_points.get('RPA'),
        hpi=[coordsystem_points[name] for name in landmark_names[3:] if name in coordsystem_points],
        hsp=hsp_head,
        coord_frame='head',
    )
    raw.set_montage(dig_montage, on_missing='warn')
    return raw


def _dig_count(raw: mne.io.Raw, kind) -> int:
    dig = raw.info.get('dig') or []
    return sum(1 for point in dig if point.get('kind') == kind)


def restore_embedded_headshape_if_missing(
    original_file_path: Path,
    preproc_file_path: Path,
) -> bool:
    """Restore original embedded headshape points when preprocessing output lacks them."""
    original_raw = mne.io.read_raw(str(original_file_path), preload=False, verbose='ERROR')
    original_extra_count = _dig_count(original_raw, FIFF.FIFFV_POINT_EXTRA)
    if original_extra_count == 0:
        return False

    preproc_raw = mne.io.read_raw(str(preproc_file_path), preload=True, verbose='ERROR')
    preproc_extra_count = _dig_count(preproc_raw, FIFF.FIFFV_POINT_EXTRA)
    if preproc_extra_count > 0:
        return False

    with preproc_raw.info._unlock():
        preproc_raw.info['dig'] = deepcopy(original_raw.info.get('dig'))
    preproc_raw.save(preproc_file_path, overwrite=True)
    print(
        "[HSP]Restored embedded headshape points from original raw: "
        f"{original_extra_count} points -> {preproc_file_path}"
    )
    return True


def _has_embedded_headshape(preproc_file_path: Path) -> bool:
    raw = mne.io.read_raw(str(preproc_file_path), preload=False, verbose='ERROR')
    return _dig_count(raw, FIFF.FIFFV_POINT_EXTRA) > 0


def _should_apply_external_digitization(
    preproc_file_path: Path,
    digitization_config: dict,
) -> bool:
    if digitization_config.get('override_embedded', False):
        return True
    return not _has_embedded_headshape(preproc_file_path)


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

    osl_config = {'preproc': config.get('preproc', [])} if isinstance(config, dict) and 'preproc' in config else config
    preprocessing.run_proc_batch(
        config=osl_config,
        files=[str(file_path)],
        outdir=preproc_dir,
        overwrite=True,
        dask_client=False,
        random_seed=random_seed,
    )

    # Attach digitization sidecars when available.
    try:
        print("Headshape Positions...")
        digitization_config = config.get('digitization') if isinstance(config, dict) else {}
        digitization_config = digitization_config or {}

        base_name = file_path.stem # basename without the extension
        preproc_file_path = Path(preproc_dir) / base_name / f"{base_name}_preproc-raw.fif"
        restore_embedded_headshape_if_missing(file_path, preproc_file_path)

        if digitization_config.get('enabled', True) is False:
            return

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
            if not _should_apply_external_digitization(preproc_file_path, digitization_config):
                print(
                    "[HSP]Skipped external headshape file because embedded "
                    f"headshape points already exist: {headshape_file}"
                )
                return

            # Create a digitization montage and update the Raw object
            raw = mne.io.read_raw(str(preproc_file_path), preload=True)
            raw_with_montage = create_raw_with_dig_montage(str(headshape_file), raw)
            raw_with_montage.save(preproc_file_path, overwrite=True)
            print(f"[HSP]Processed and saved the raw data to: {preproc_file_path}")
        else:
            bids_sidecars = _find_bids_digitization_sidecars(file_path, digitization_config)
            if bids_sidecars:
                hsp_file, elp_file, coordsystem_file = bids_sidecars
                if not _should_apply_external_digitization(preproc_file_path, digitization_config):
                    print(
                        "[HSP]Skipped BIDS digitization sidecars because embedded "
                        f"headshape points already exist: {coordsystem_file}"
                    )
                    return
                raw = mne.io.read_raw(str(preproc_file_path), preload=True)
                raw_with_montage = create_raw_with_bids_digitization(
                    str(hsp_file) if hsp_file else None,
                    str(elp_file) if elp_file else None,
                    str(coordsystem_file),
                    raw,
                )
                raw_with_montage.save(preproc_file_path, overwrite=True)
                print(
                    "[HSP]Processed BIDS digitization and saved the raw data to: "
                    f"{preproc_file_path}"
                )

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
