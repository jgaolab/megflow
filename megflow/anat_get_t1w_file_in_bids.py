#! /usr/bin/env python3
import argparse
import bids
import yaml
from pathlib import Path
import re
import warnings
warnings.filterwarnings('ignore', category=UserWarning)


def _normalize_filter(value):
    if value is None:
        return None
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]
    normalized = []
    for item in values:
        text = str(item).strip()
        if text.startswith('sub-'):
            text = text[4:]
        if text.startswith('ses-'):
            text = text[4:]
        if text:
            normalized.append(text)
    return normalized or None


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
    root = Path(bids_dir)
    candidates = []
    seen = set()

    for pattern in _fallback_t1_patterns(config):
        for path in root.glob(f'sub-*/**/{pattern}'):
            if not path.is_file() or 'derivatives' in path.parts:
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

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="DeepPrep: sMRI and fMRI PreProcessing workflows"
    )

    parser.add_argument("--bids-dir", help="directory of BIDS type: /mnt/ngshare2/BIDS/MSC", required=True)
    # parser.add_argument('--subject-ids', type=str, nargs='+', default=[], help='specified subject_id')
    parser.add_argument('--config', type=str, default="{}", help='YAML configuration parameters')
    args = parser.parse_args()

    # if len(args.subject_ids) != 0:
    #     subject_ids = [subject_id[4:] if subject_id.startswith('sub-') else subject_id for subject_id in args.subject_ids]
    # else:
    #     subject_ids = args.subject_ids

    config = yaml.safe_load(args.config)

    print("config:",config)
    if config is not None:
        filters = {
            'subject': _normalize_filter(config.get('subject_id')),
            'session': _normalize_filter(config.get('session_id')),
            'task': _normalize_filter(config.get('task')),
            'run': _normalize_filter(config.get('run_id'))
        }

        filters = {key: value for key, value in filters.items() if value is not None}
    else:
        filters = {}

    ignore_pattern = [r'(?!sub-).*']
    layout = bids.BIDSLayout(args.bids_dir, derivatives=False, ignore=ignore_pattern, validate=False)

    subject_dict = {}

    for t1w_file in layout.get(return_type='filename',
                               suffix="T1w",
                               extension='.nii.gz',
                               **filters):
        if not _matches_keyword_filters(t1w_file, config):
            continue

        sub_info = layout.parse_file_entities(t1w_file)
        subject_id = f"sub-{sub_info['subject']}"
        subject_dict.setdefault(subject_id, []).append(t1w_file)

    if not subject_dict:
        for subject, t1w_file in _find_t1_fallback_files(args.bids_dir, filters, config):
            if not subject:
                continue
            subject_dict.setdefault(f"sub-{subject}", []).append(t1w_file)

    for subject_id, t1w_files in sorted(subject_dict.items()):
        with open(f'{subject_id}', 'w') as f:
            f.write(subject_id + '\n')
            f.write('\n'.join(t1w_files))
