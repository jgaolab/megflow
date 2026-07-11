#! /usr/bin/env python3
import os
import yaml
import argparse
from bids import BIDSLayout
from pathlib import Path
import re
import warnings
warnings.filterwarnings('ignore', category=UserWarning)


def _normalize_entity_filter(value, available_values=None):
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


def _safe_layout_values(layout, method_name):
    try:
        method = getattr(layout, method_name)
    except AttributeError:
        return []
    try:
        return method() or []
    except Exception:
        return []


def _extract_bids_entity(path, entity):
    matcher = re.search(rf'{entity}-([^_/]+)', str(path))
    return matcher.group(1) if matcher else None


def _matches_filter(value, filters, key):
    expected = filters.get(key)
    if expected is None:
        return True
    return value in expected


def _fallback_t1_patterns(config):
    configured = (config or {}).get('t1_patterns')
    if configured:
        return configured if isinstance(configured, list) else [configured]
    return [
        '*T1w.nii.gz',
        '*T1w.nii',
        '*T1_defaced.nii.gz',
        '*T1_defaced.nii',
        '*T1*.nii.gz',
        '*T1*.nii',
    ]


def _normalize_keywords(value):
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]
    return [str(item).lower() for item in values if str(item).strip()]


def _matches_keyword_filters(path, config):
    path_text = str(path).lower()
    include = _normalize_keywords((config or {}).get('t1_include_keywords'))
    exclude = _normalize_keywords((config or {}).get('t1_exclude_keywords'))
    if include and not any(keyword in path_text for keyword in include):
        return False
    if exclude and any(keyword in path_text for keyword in exclude):
        return False
    return True


def _find_t1_fallback_files(bids_dir, filters, config):
    """Find T1-like NIfTI files when BIDSLayout cannot index non-standard names."""
    root = Path(bids_dir)
    candidates = []
    seen = set()

    for pattern in _fallback_t1_patterns(config):
        for path in root.glob(f'sub-*/**/{pattern}'):
            if not path.is_file():
                continue
            if 'derivatives' in path.parts:
                continue
            if not _matches_keyword_filters(path, config):
                continue
            resolved = str(path.resolve())
            if resolved in seen:
                continue

            subject = _extract_bids_entity(path, 'sub')
            session = _extract_bids_entity(path, 'ses')
            if not _matches_filter(subject, filters, 'subject'):
                continue
            if not _matches_filter(session, filters, 'session'):
                continue

            seen.add(resolved)
            candidates.append((subject, str(path)))

    return sorted(candidates, key=lambda item: item[1])


def process_bids(bids_dir, output_file, config):
    """Process BIDS directory to retrieve T1w files for specified subject IDs."""
    print("Loading T1w BIDS files...")
    # ignore_dirs = ['derivatives', 'code']
    # layout = BIDSLayout(root=bids_dir,derivatives=False,ignore=ignore_dirs)
    print("config:",config)

    ignore_pattern = [r'(?!sub-).*']
    layout = BIDSLayout(bids_dir, derivatives=False, ignore=ignore_pattern, validate=False)
    subject_dict = {}

    print("Loading subject IDs...")

    if config is not None:
        available = {
            'subject': _safe_layout_values(layout, 'get_subjects'),
            'session': _safe_layout_values(layout, 'get_sessions'),
            'task': _safe_layout_values(layout, 'get_tasks'),
            'run': _safe_layout_values(layout, 'get_runs'),
        }
        filters = {
            'subject': _normalize_entity_filter(config.get('subject_id'), available.get('subject')),
            'session': _normalize_entity_filter(config.get('session_id'), available.get('session')),
            'task': _normalize_entity_filter(config.get('task'), available.get('task')),
            'run': _normalize_entity_filter(config.get('run_id'), available.get('run'))
        }

        filters = {key: value for key, value in filters.items() if value is not None}
    else:
        filters = {}

    # Fetch T1w files and organize them by subject ID
    for t1w_file in layout.get(return_type='filename',
                               suffix="T1w",
                               extension='nii.gz',
                               **filters
                               ):
        if not _matches_keyword_filters(t1w_file, config):
            continue
        print(t1w_file)
        sub_info = layout.parse_file_entities(t1w_file)
        subject_id = f"sub-{sub_info['subject']}"
        subject_dict.setdefault(subject_id, []).append(t1w_file)
        print("Fetch subject:", subject_id)

    if not subject_dict:
        print("No standard T1w files found by BIDSLayout. Searching T1-like NIfTI files...")
        for subject, t1w_file in _find_t1_fallback_files(bids_dir, filters, config):
            if not subject:
                continue
            subject_id = f"sub-{subject}"
            subject_dict.setdefault(subject_id, []).append(t1w_file)
            print("Fetch fallback subject:", subject_id, t1w_file)

    with open(output_file, 'w') as f:
        for subject_id, t1w_files in subject_dict.items():
            # Write the subject ID followed by its T1w file paths, each on a new line
            f.write(f"{subject_id}:{t1w_files}\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Read MRI datasets in BIDS or raw format."
    )

    parser.add_argument("--bids_dir", help="directory of BIDS type", required=True)
    parser.add_argument("--output_file", type=str, required=True,
                        help="Output file to save the T1w list of file paths.")
    parser.add_argument('--config', type=str, default="{}", help='YAML configuration parameters')
    args = parser.parse_args()

    # debug
    # args.config = """
    #     # Filter out specific anatomy, only bids support.
    #     subject_id: null
    #     session_id: null
    #     task: null
    #     run_id: null
    # """
    config = yaml.safe_load(args.config)

    # # deepprep: get the parameters
    # try:
    #     redis_manager = RedisGlobalVariableManager()
    #     redis_manager.set_global_variable("MRI_IMPORT_CONFIG", args.config)
    #     my_variable = redis_manager.get_global_variable("MRI_IMPORT_CONFIG")
    # except Exception as e:
    #     print(e)

    process_bids(args.bids_dir, args.output_file, config)
