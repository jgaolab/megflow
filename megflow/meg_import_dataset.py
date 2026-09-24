# !/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified function to read BIDS and raw datasets.
"""
import os
import re
import yaml
import argparse
from pathlib import Path
from typing import Literal, Optional, List, Union
from mne_bids import get_bids_path_from_fname, print_dir_tree, make_report, get_entity_vals
from mne_bids.config import ALLOWED_DATATYPE_EXTENSIONS

def _normalize_keywords(value) -> Optional[List[str]]:
    """Turn YAML config value into a list of non-empty strings, or None if unset."""
    if value is None:
        return None
    if isinstance(value, str):
        return [value] if value.strip() else None
    if isinstance(value, list):
        out = [str(x).strip() for x in value if x is not None and str(x).strip()]
        return out or None
    return None


def _normalize_entity_filter(value, available_values=None) -> Optional[List[str]]:
    """Normalize BIDS entity filters and support selectors such as ``first:10``."""
    if value is None:
        return None
    if isinstance(value, str):
        items = [value.strip()] if value.strip() else []
    elif isinstance(value, (list, tuple, set)):
        items = [str(x).strip() for x in value if x is not None and str(x).strip()]
    else:
        items = [str(value).strip()]

    if not items:
        return None

    normalized = []
    available = list(available_values or [])
    for item in items:
        selector = item.lower()
        if selector.startswith("first:"):
            if not available:
                continue
            try:
                count = int(selector.split(":", 1)[1])
            except ValueError as exc:
                raise ValueError(f"Invalid first:n selector: {item}") from exc
            normalized.extend(available[:count])
        else:
            normalized.append(item)

    return normalized or None


def _matches_suffix(path: Path, file_suffix: str) -> bool:
    """Return True when a raw file/directory name matches the configured suffix."""
    suffix = str(file_suffix or '').strip()
    if not suffix:
        return False
    return path.name.lower().endswith(suffix.lower())


def _matches_keywords(path: Path, keywords: Optional[List[str]]) -> bool:
    """Match include/exclude keywords against the raw candidate basename."""
    if not keywords:
        return False
    name_lower = path.name.lower()
    return any(keyword.lower() in name_lower for keyword in keywords)


def _resolve_existing_or_parent(path_value) -> Optional[Path]:
    """Resolve a path for containment checks without requiring the leaf to exist."""
    if path_value is None:
        return None
    path_text = str(path_value).strip()
    if not path_text:
        return None

    path = Path(path_text).expanduser()
    if path.exists():
        return path.resolve()

    existing_parent = path.parent
    while existing_parent != existing_parent.parent and not existing_parent.exists():
        existing_parent = existing_parent.parent

    if existing_parent.exists():
        return existing_parent.resolve() / path.relative_to(existing_parent)
    return path.resolve(strict=False)


def _is_relative_to(path: Path, parent: Path) -> bool:
    """Compatibility helper for Python versions without Path.is_relative_to."""
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _bids_recording_paths(dataset_dir: Path, datatype: str) -> List:
    """Parse complete filenames, including directory-based MEG recordings."""
    endings = tuple(f"_{datatype}{ext}" for ext in ALLOWED_DATATYPE_EXTENSIONS[datatype])
    paths = []
    # Limit discovery to source BIDS recordings, outside derivatives/sourcedata.
    for layout in (f"sub-*/{datatype}/*", f"sub-*/ses-*/{datatype}/*"):
        for candidate in sorted(dataset_dir.glob(layout)):
            is_bti = candidate.is_dir() and candidate.name.endswith(f"_{datatype}")
            if not is_bti and not candidate.name.endswith(endings):
                continue
            try:
                bids_path = get_bids_path_from_fname(candidate)
                if is_bti:
                    bids_path.update(extension=".pdf")
            except (KeyError, ValueError) as exc:
                raise ValueError(f"Invalid BIDS MEG recording {candidate}: {exc}") from exc
            if bids_path.task is None:
                continue  # Calibration and crosstalk files are not recordings.
            if bids_path.fpath != candidate:
                raise ValueError(f"BIDS filename and directory do not agree: {candidate}")
            paths.append(bids_path)
    return paths


def read_meg_dataset(dataset_dir: Union[str, Path], file_suffix: str = '.fif',
                      dataset_format: Optional[Literal['bids', 'raw','auto']] = None,
                      datatype: Literal['meg'] = 'meg', subjects: Optional[List[str]] = None,
                      sessions: Optional[List[str]] = None, tasks: Optional[List[str]] = None,
                      runs: Optional[List[str]] = None, print_dir: bool = False,
                      bids_report: bool = False,
                      raw_exclude_keywords: Optional[List[str]] = None,
                      raw_include_keywords: Optional[List[str]] = None,
                      raw_exclude_dirs: Optional[List[Union[str, Path]]] = None) -> List:
    """
    General function to read MEG datasets, supporting both BIDS and raw formats.

    Parameters
    ----------
    dataset_dir : str or Path
        Path to the dataset directory.
    file_suffix : str, optional
        File suffix to filter raw dataset files (default is '.fif').
    raw_exclude_keywords : list of str, optional
        For ``dataset_format='raw'`` only: basenames containing any of these
        substrings (case-insensitive) are skipped. Use to drop non-MEG ``.fif``
        files (for example ``phantom``, ``crosstalk``) that share the same suffix.
    raw_include_keywords : list of str, optional
        For ``dataset_format='raw'`` only: when set, only basenames containing
        at least one of these substrings (case-insensitive) are kept.
    raw_exclude_dirs : list of str or Path, optional
        For ``dataset_format='raw'`` only: candidate files inside these
        directories are skipped. This is used to keep MEGFlow output/preprocessed
        directories out of raw input discovery.
    dataset_format : {'bids', 'raw','auto'}, optional
        Format of the dataset. If None, it will be auto-detected.
    datatype : {'meg'}, optional
        The type of data to read (default is 'meg').
    subjects : list of str, optional
        Specific subjects to load (BIDS format only).
    sessions : list of str, optional
        Specific sessions to load (BIDS format only).
    tasks : list of str, optional
        Specific tasks to load (BIDS format only).
    runs : list of str, optional
        Specific runs to load (BIDS format only).
    print_dir : bool, optional
        If True, prints the directory tree (BIDS format only).
    bids_report : bool, optional
        If True, generates a BIDS report (BIDS format only).

    Returns
    -------
    List
        A list of loaded MEG data objects or file paths.

    Raises
    ------
    ValueError
        If the dataset format is unsupported or the dataset directory is invalid.
    """
    dataset_dir = Path(dataset_dir)

    if not dataset_dir.is_dir():
        raise ValueError(f"The specified dataset directory {dataset_dir} is not valid.")

    # Auto-detect dataset format
    if dataset_format == "auto":
        if (dataset_dir / "dataset_description.json").exists():
            dataset_format = 'bids'
        else:
            dataset_format = 'raw'

    # Handle BIDS dataset
    if dataset_format == 'bids':
        if print_dir:
            print_dir_tree(str(dataset_dir), max_depth=3)
        if bids_report:
            print(make_report(str(dataset_dir)))

        filters = {}
        for entity, value in (
            ('subject', subjects), ('session', sessions), ('task', tasks), ('run', runs)
        ):
            available = get_entity_vals(str(dataset_dir), entity, with_key=False)
            filters[entity] = _normalize_entity_filter(value, available)
            if entity == 'subject' and filters[entity] is None:
                filters[entity] = available

        raw_list = []
        split_recordings = {}
        for bids_path in _bids_recording_paths(dataset_dir, datatype):
            if any(values is not None and getattr(bids_path, entity) not in values
                   for entity, values in filters.items()):
                continue
            if bids_path.extension == '.fif' and bids_path.split is not None:
                key = bids_path.copy().update(split=None).basename
                split_recordings.setdefault(key, []).append(bids_path)
            else:
                raw_list.append(bids_path)

        # MNE follows the FIF links from the first part; do not schedule each part.
        for recording, parts in split_recordings.items():
            first = [part for part in parts if int(part.split) == 1]
            if len(first) != 1:
                raise ValueError(f"Expected exactly one first split (split-01) for {recording}.")
            raw_list.append(first[0])

        if not raw_list:
            raise ValueError(f"No BIDS MEG recordings match the import filters in {dataset_dir}.")
        raw_list.sort(key=str)
        for bids_path in raw_list:
            print("file_path:", bids_path.fpath)
        return raw_list

    # Handle raw dataset
    elif dataset_format == 'raw':
        raw_list = []
        include_keywords = raw_include_keywords or None
        exclude_keywords = raw_exclude_keywords or None
        exclude_dirs = []
        if raw_exclude_dirs:
            exclude_dirs = [
                resolved for resolved in (_resolve_existing_or_parent(p) for p in raw_exclude_dirs) if resolved
            ]
        dataset_resolved = dataset_dir.resolve()
        if any(exclude_dir == dataset_resolved for exclude_dir in exclude_dirs):
            print(
                f"Warning: a raw exclusion directory is the same as dataset_dir ({dataset_dir}); "
                "raw input discovery may exclude all files."
            )

        def keep_candidate(candidate_path: Path) -> bool:
            candidate_resolved = candidate_path.resolve()
            if exclude_dirs and any(_is_relative_to(candidate_resolved, exclude_dir) for exclude_dir in exclude_dirs):
                print(f"raw_exclude_dirs excluded: {candidate_path}")
                return False
            if include_keywords and not _matches_keywords(candidate_path, include_keywords):
                print(f"raw_include_keywords skipped: {candidate_path}")
                return False
            if exclude_keywords and _matches_keywords(candidate_path, exclude_keywords):
                print(f"raw_exclude_keywords excluded: {candidate_path}")
                return False
            return True

        for root, dirs, files in os.walk(dataset_dir):
            root_path = Path(root).resolve()
            if exclude_dirs and any(_is_relative_to(root_path, exclude_dir) for exclude_dir in exclude_dirs):
                dirs[:] = []
                continue
            if exclude_dirs:
                dirs[:] = [
                    dirname for dirname in dirs
                    if not any(_is_relative_to((root_path / dirname).resolve(), exclude_dir) for exclude_dir in exclude_dirs)
                ]

            matched_dirs = []
            for dirname in list(dirs):
                candidate_path = Path(root) / dirname
                if not _matches_suffix(candidate_path, file_suffix):
                    continue
                matched_dirs.append(dirname)
                if keep_candidate(candidate_path):
                    raw_list.append(str(candidate_path))

            if matched_dirs:
                dirs[:] = [dirname for dirname in dirs if dirname not in matched_dirs]

            for file in files:
                candidate_path = Path(root) / file
                if not _matches_suffix(candidate_path, file_suffix):
                    continue
                if keep_candidate(candidate_path):
                    raw_list.append(str(candidate_path))
        if not raw_list:
            raise ValueError(f"No raw data files found in {dataset_dir}.")

        return sorted(raw_list)

    else:
        raise ValueError(f"Unsupported dataset format: {dataset_format}. Supported formats: 'bids', 'raw'.")


def save_raw_list_to_file(raw_list: List[str], output_file: str):
    """
    Save the raw MEG file paths to a text file.

    Parameters
    ----------
    raw_list : List[str]
        List of file paths to be written to the output file.
    output_file : str
        Path to the output text file where the raw list will be saved.
    """
    with open(output_file, 'w') as f:
        for file_path in raw_list:
            f.write(f"{file_path}\n")
    print(f"Saved {len(raw_list)} file paths to {output_file}")

if __name__ == "__main__":
    # Example usage
    # dataset_dir = "/path/to/dataset"
    # # Read BIDS format dataset
    # raw_data_bids = read_meg_dataset(dataset_dir, dataset_format='bids', print_dir=True, bids_report=True)
    # print(f"Loaded {len(raw_data_bids)} MEG datasets from BIDS.")
    #
    # # Read raw format dataset
    # raw_data_raw = read_meg_dataset(dataset_dir, dataset_format='raw')
    # print(f"Loaded {len(raw_data_raw)} MEG datasets from raw format.")

    parser = argparse.ArgumentParser(description="Read MEG datasets in BIDS or raw format.")
    parser.add_argument("--dataset_dir", type=str, required=True, help="Path to the dataset directory.")
    parser.add_argument("--dataset_format", type=str, choices=["auto", "bids", "raw"], required=False, help="Format of the dataset.")
    parser.add_argument("--file_suffix", type=str, default=".fif", help="Suffix for raw data files (default: .fif).")
    parser.add_argument("--print_dir", action="store_true", help="Print directory structure (for BIDS format).")
    parser.add_argument("--bids_report", action="store_true", help="Generate BIDS report (for BIDS format).")
    parser.add_argument("--output_file", type=str, required=True,
                        help="Output file to save the raw list of file paths.")
    parser.add_argument("--exclude_output_dir", type=str, default="",
                        help="Pipeline output directory to exclude from raw dataset discovery.")
    parser.add_argument("--exclude_preproc_dir", type=str, default="",
                        help="Pipeline preprocessed directory to exclude from raw dataset discovery.")
    parser.add_argument('--config', type=str, default="{}", help='YAML configuration parameters')
    args = parser.parse_args()

    # debug
    # args.config = """
    #     # Filter out specific megs
    #     subject_id:
    #         - '01'
    #     session_id:
    #         - '006'
    #     task:
    #         - aef
    # """
    config = yaml.safe_load(args.config)

    raw_list = read_meg_dataset(
        dataset_dir=args.dataset_dir,
        dataset_format=args.dataset_format,
        file_suffix=args.file_suffix,
        print_dir=args.print_dir,
        bids_report=args.bids_report,
        subjects=config.get('subject_id'),
        sessions=config.get('session_id'),
        tasks=config.get('task'),
        runs=config.get('run_id'),
        raw_exclude_keywords=_normalize_keywords(config.get('raw_exclude_keywords')),
        raw_include_keywords=_normalize_keywords(config.get('raw_include_keywords')),
        raw_exclude_dirs=[args.exclude_output_dir, args.exclude_preproc_dir],
    )

    #filtering: keep only the main file, exclude files that are split (e.g. -1.fif, -2.fif, etc.)
    filtered_raw_list = []
    pattern = re.compile(r'-\d+' + re.escape(args.file_suffix) + r'$')

    for file_path in raw_list:
        file_name = os.path.basename(file_path)
        if not pattern.search(file_name):
            filtered_raw_list.append(file_path)
        else:
            print(f"excluded: {file_path}")

    save_raw_list_to_file(filtered_raw_list, args.output_file)
    print(f"Loaded {len(raw_list)} MEG datasets and saved to {args.output_file}.")
