import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import mne
import numpy as np
from scipy.spatial.distance import cosine
from scipy.stats import pearsonr, spearmanr

mne.viz.set_browser_backend("matplotlib")


DEVICE_ALIASES = {
    "neuromag": "elekta",
    "megin": "elekta",
    "elekta": "elekta",
    "ctf": "ctf",
    "kit": "kit",
    "yokogawa": "kit",
    "4d": "4d",
    "bti": "4d",
    "magnes": "4d",
    "opm": "opm",
    "quanmag_opm": "opm",
    "quspin_opm": "opm",
    "quspin": "opm",
    "fieldline": "opm",
}

AUTO_DEVICE_VALUES = {"", "none", "null", "auto", "unknown", "meg_vendor_is_unknown"}


def normalize_device_type(device_type):
    """Normalize MEG vendor aliases to template device names."""
    if device_type is None:
        return "auto"

    value = str(device_type).strip().lower().replace("-", "_").replace(" ", "_")
    if value in AUTO_DEVICE_VALUES:
        return "auto"

    for key, normalized in DEVICE_ALIASES.items():
        if key in value:
            return normalized
    return value


def available_template_device_types(save_dir="./ica_templates"):
    """Return device types that have bundled template metadata."""
    if not os.path.exists(save_dir):
        return []

    devices = []
    for filename in os.listdir(save_dir):
        if filename.startswith("template_meta_") and filename.endswith(".json"):
            devices.append(filename[len("template_meta_") : -len(".json")])
    return sorted(devices)


def _normalize_match_text(value):
    return re.sub(r"[\s_/-]+", "", str(value).lower())


def infer_device_type_from_ica(ica, min_hits=3):
    """Infer a template device type from ICA channel names when config uses auto."""
    ch_names = getattr(ica, "ch_names", None)
    if not ch_names:
        info = getattr(ica, "info", None)
        if hasattr(info, "get"):
            ch_names = info.get("ch_names", [])
        else:
            ch_names = getattr(info, "ch_names", [])

    ch_names = [re.sub(r"[\s_]+", "", str(ch_name).upper()) for ch_name in ch_names]
    if not ch_names:
        return None

    device_patterns = {
        "opm": (
            re.compile(r"(?:OPM|QZFM|QZFG|FIELDLINE)"),
            re.compile(r"^FL\d{2,}[A-Z0-9-]*$"),
        ),
        "elekta": (
            re.compile(r"^MEG\d{4}$"),
        ),
        "ctf": (
            re.compile(r"^M[LRZ][A-Z]{1,2}\d{2,3}(?:-\d{3,5})?$"),
        ),
        "kit": (
            re.compile(r"^(?:MEG|AG)\d{3}$"),
        ),
        "4d": (
            re.compile(r"^A\d{1,3}$"),
        ),
    }

    scores = Counter()
    for ch_name in ch_names:
        for device_type, patterns in device_patterns.items():
            if any(pattern.search(ch_name) for pattern in patterns):
                scores[device_type] += 1
                break

    if not scores:
        return None

    (best_device, best_hits), *rest = scores.most_common()
    if best_hits < min_hits:
        return None

    if rest and rest[0][1] == best_hits:
        return None

    return best_device


def resolve_device_type_from_dataset_map(device_map, paths):
    """Resolve a device type from a dataset-name to device-type mapping."""
    if not isinstance(device_map, dict) or not device_map:
        return None, None

    path_values = [Path(path) for path in paths if path]
    path_text = " ".join(str(path) for path in path_values)
    normalized_path_text = _normalize_match_text(path_text)
    normalized_parts = {
        _normalize_match_text(part)
        for path in path_values
        for part in path.parts
        if str(part).strip()
    }

    default_device = None
    candidates = []
    for dataset_name, device_type in device_map.items():
        if str(dataset_name).strip().lower() in {"default", "*"}:
            default_device = device_type
            continue
        normalized_name = _normalize_match_text(dataset_name)
        if normalized_name:
            candidates.append((normalized_name, dataset_name, device_type))

    for normalized_name, dataset_name, device_type in sorted(candidates, key=lambda item: len(item[0]), reverse=True):
        if normalized_name in normalized_parts or normalized_name in normalized_path_text:
            return device_type, str(dataset_name)

    if default_device is not None:
        return default_device, "default"

    return None, None


def resolve_template_device_type(device_type, ica=None, save_dir="./ica_templates"):
    """Resolve configured/auto device type to an available template device."""
    requested = normalize_device_type(device_type)
    resolved = infer_device_type_from_ica(ica) if requested == "auto" else requested
    available = available_template_device_types(save_dir)

    if not resolved:
        return None, f"could not infer MEG vendor; available templates: {available}"

    if resolved not in available:
        return None, f"no templates for device type '{resolved}'; available templates: {available}"

    return resolved, None


# ============ Configuration Management Classes ============
class TemplateConfig:
    """Template configuration management class"""

    def __init__(self, dataset_name, device_type):
        """
        Parameters:
        -----------
        dataset_name : str
            Dataset name (for identification)
        device_type : str
            Device type: 'elekta', 'kit', 'ctf', '4d', 'opm', 'eeg'
        """
        self.dataset_name = dataset_name
        self.device_type = device_type
        self.subjects = {}
        self._validate_device_type()

    def _validate_device_type(self):
        """Validate device type"""
        valid_devices = ["elekta", "kit", "ctf", "4d", "opm", "eeg"]
        if self.device_type not in valid_devices:
            raise ValueError(f"device_type must be one of: {valid_devices}")

    def add_subject(self, subj_id, raw_path, ica_path, ecg_ics=None, eog_ics=None):
        """
        Add a subject's configuration

        Parameters:
        -----------
        subj_id : int or str
            Subject ID
        raw_path : str
            Raw data file path
        ica_path : str
            ICA file path
        ecg_ics : list
            ECG-related IC indices
        eog_ics : list
            EOG-related IC indices
        """
        self.subjects[subj_id] = {
            "raw_path": raw_path,
            "ica_path": ica_path,
            "labels": {"ecg": ecg_ics or [], "eog": eog_ics or []},
        }
        return self

    def add_subjects_batch(self, subjects_dict):
        """
        Batch add subjects

        Parameters:
        -----------
        subjects_dict : dict
            Format: {
                subj_id: {
                    'raw_path': str,
                    'ica_path': str,
                    'labels': {'ecg': [...], 'eog': [...]}
                }
            }
        """
        for subj_id, config in subjects_dict.items():
            self.subjects[subj_id] = config
        return self

    def add_subjects_from_pattern(self, subj_ids, raw_pattern, ica_pattern, labels_dict):
        """
        Batch add subjects from path patterns

        Parameters:
        -----------
        subj_ids : list
            List of subject IDs
        raw_pattern : str
            Raw path pattern, use {subj} as placeholder
            Example: "/data/sub-{subj:03d}_raw.fif"
        ica_pattern : str
            ICA path pattern, use {subj} as placeholder
        labels_dict : dict
            {subj_id: {'ecg': [...], 'eog': [...]}}
        """
        for subj_id in subj_ids:
            raw_path = raw_pattern.format(subj=subj_id)
            ica_path = ica_pattern.format(subj=subj_id)
            labels = labels_dict.get(subj_id, {"ecg": [], "eog": []})

            self.add_subject(
                subj_id=subj_id,
                raw_path=raw_path,
                ica_path=ica_path,
                ecg_ics=labels.get("ecg", []),
                eog_ics=labels.get("eog", []),
            )
        return self

    def get_summary(self):
        """Get configuration summary"""
        n_subjects = len(self.subjects)
        n_ecg_total = sum(len(s["labels"]["ecg"]) for s in self.subjects.values())
        n_eog_total = sum(len(s["labels"]["eog"]) for s in self.subjects.values())

        return {
            "dataset_name": self.dataset_name,
            "device_type": self.device_type,
            "n_subjects": n_subjects,
            "n_ecg_ics": n_ecg_total,
            "n_eog_ics": n_eog_total,
            "subjects": list(self.subjects.keys()),
        }

    def print_summary(self):
        """Print configuration summary"""
        summary = self.get_summary()
        print(f"\n{'=' * 70}")
        print(f"Template Configuration Summary")
        print(f"{'=' * 70}")
        print(f"Dataset Name: {summary['dataset_name']}")
        print(f"Device Type: {summary['device_type']}")
        print(f"Number of Subjects: {summary['n_subjects']}")
        print(f"Total ECG Templates: {summary['n_ecg_ics']}")
        print(f"Total EOG Templates: {summary['n_eog_ics']}")
        print(f"Subject List: {summary['subjects']}")
        print(f"{'=' * 70}\n")

    def save_config(self, save_path):
        """Save configuration to JSON file"""
        config_data = {"dataset_name": self.dataset_name, "device_type": self.device_type, "subjects": self.subjects}

        os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else ".", exist_ok=True)

        with open(save_path, "w") as f:
            json.dump(config_data, f, indent=2)

        print(f"✓ Configuration saved to: {save_path}")

    @classmethod
    def load_config(cls, load_path):
        """Load configuration from JSON file"""
        with open(load_path, "r") as f:
            config_data = json.load(f)

        config = cls(dataset_name=config_data["dataset_name"], device_type=config_data["device_type"])
        config.subjects = config_data["subjects"]

        print(f"✓ Configuration loaded from {load_path}")
        return config

    def to_dict(self):
        """Convert to dictionary format"""
        return {"dataset_name": self.dataset_name, "device_type": self.device_type, "subjects": self.subjects}


class MultiTemplateManager:
    """Manage multiple dataset template configurations"""

    def __init__(self):
        self.configs = []

    def add_config(self, config):
        """Add a configuration"""
        if not isinstance(config, TemplateConfig):
            raise TypeError("config must be a TemplateConfig instance")
        self.configs.append(config)
        return self

    def get_configs_by_device(self, device_type):
        """Get all configurations by device type"""
        return [c for c in self.configs if c.device_type == device_type]

    def get_config_by_dataset(self, dataset_name):
        """Get configuration by dataset name"""
        for config in self.configs:
            if config.dataset_name == dataset_name:
                return config
        return None

    def print_all_summaries(self):
        """Print all configuration summaries"""
        print(f"\n{'=' * 70}")
        print(f"All Template Configurations ({len(self.configs)} datasets)")
        print(f"{'=' * 70}")
        for i, config in enumerate(self.configs, 1):
            summary = config.get_summary()
            print(f"\nConfiguration {i}:")
            print(f"  Dataset: {summary['dataset_name']}")
            print(f"  Device: {summary['device_type']}")
            print(f"  Subjects: {summary['n_subjects']}")
            print(f"  ECG Templates: {summary['n_ecg_ics']}")
            print(f"  EOG Templates: {summary['n_eog_ics']}")
        print(f"{'=' * 70}\n")

    def save_all_configs(self, save_dir="./template_configs"):
        """Save all configurations"""
        os.makedirs(save_dir, exist_ok=True)

        for config in self.configs:
            filename = f"{config.dataset_name}_{config.device_type}_config.json"
            filepath = os.path.join(save_dir, filename)
            config.save_config(filepath)

    @classmethod
    def load_all_configs(cls, load_dir="./template_configs"):
        """Load all configurations from directory"""
        manager = cls()

        if not os.path.exists(load_dir):
            print(f"⚠️  Configuration directory does not exist: {load_dir}")
            return manager

        for filename in os.listdir(load_dir):
            if filename.endswith("_config.json"):
                filepath = os.path.join(load_dir, filename)
                try:
                    config = TemplateConfig.load_config(filepath)
                    manager.add_config(config)
                except Exception as e:
                    print(f"⚠️  Failed to load {filename}: {e}")

        print(f"\n✓ Loaded {len(manager.configs)} configurations")
        return manager


# ============ Template Creation Functions (Device-Based Storage) ============
def create_templates_from_config(config, save_dir="./ica_templates", mode="append"):
    """
    Create templates from configuration object(s) (stored by device type)

    Parameters:
    -----------
    config : TemplateConfig or list of TemplateConfig
        Template configuration object or list of configurations
    save_dir : str
        Directory to save templates
    mode : str
        'append': Append to existing templates (default)
        'overwrite': Overwrite existing templates
        'new': Create new templates (error if exists)

    Returns:
    --------
    ecg_templates : ndarray
    eog_templates : ndarray
    """
    # Convert single config to list
    if isinstance(config, TemplateConfig):
        configs = [config]
    elif isinstance(config, list):
        configs = config
    else:
        raise TypeError("config must be TemplateConfig or list of TemplateConfig")

    # Check all configs have the same device type
    device_types = set(c.device_type for c in configs)
    if len(device_types) > 1:
        raise ValueError(f"Configs contain multiple device types: {device_types}. Please create templates separately")

    device_type = configs[0].device_type

    os.makedirs(save_dir, exist_ok=True)

    # Template file paths (stored by device)
    ecg_filename = os.path.join(save_dir, f"ecg_templates_{device_type}.npy")
    eog_filename = os.path.join(save_dir, f"eog_templates_{device_type}.npy")
    meta_filename = os.path.join(save_dir, f"template_meta_{device_type}.json")

    # Handle existing templates
    existing_ecg = []
    existing_eog = []
    existing_meta = {"datasets": []}

    if mode == "new" and os.path.exists(meta_filename):
        raise FileExistsError(f"Template file already exists: {meta_filename}. Use mode='append' or 'overwrite'")

    if mode == "append" and os.path.exists(meta_filename):
        print(f"Detected existing templates, loading and appending...")
        if os.path.exists(ecg_filename):
            existing_ecg = list(np.load(ecg_filename))
        if os.path.exists(eog_filename):
            existing_eog = list(np.load(eog_filename))
        with open(meta_filename, "r") as f:
            existing_meta = json.load(f)
        print(f"  Existing ECG templates: {len(existing_ecg)}")
        print(f"  Existing EOG templates: {len(existing_eog)}")
        print(f"  From datasets: {[d['dataset_name'] for d in existing_meta.get('datasets', [])]}")

    print(f"\n{'=' * 70}")
    print(f"Creating/Updating Templates")
    print(f"{'=' * 70}")
    print(f"Device Type: {device_type}")
    print(f"Processing Mode: {mode}")
    print(f"Number of Datasets: {len(configs)}")
    print(f"{'=' * 70}\n")

    ecg_templates = existing_ecg.copy() if mode == "append" else []
    eog_templates = existing_eog.copy() if mode == "append" else []
    n_channels = None
    channel_names = None

    # Track metadata
    datasets_info = existing_meta.get("datasets", []) if mode == "append" else []
    existing_dataset_names = [d["dataset_name"] for d in datasets_info]

    for config in configs:
        dataset_name = config.dataset_name

        # Check if dataset already processed
        if mode == "append" and dataset_name in existing_dataset_names:
            print(f"⚠️  Dataset '{dataset_name}' already exists in templates, skipping")
            continue

        print(f"\nProcessing dataset: {dataset_name}")
        print(f"-" * 70)

        dataset_ecg_count = 0
        dataset_eog_count = 0
        processed_subjects = []

        for subj_id, subj_config in config.subjects.items():
            print(f"  Processing subject {subj_id}...")

            raw_path = subj_config["raw_path"]
            ica_path = subj_config["ica_path"]
            labels = subj_config["labels"]

            # Check file existence
            if not os.path.exists(raw_path):
                print(f"    ✗ Raw file does not exist, skipping: {raw_path}")
                continue

            if not os.path.exists(ica_path):
                print(f"    ✗ ICA file does not exist, skipping: {ica_path}")
                continue

            try:
                temp_raw = mne.io.read_raw(raw_path, preload=True, verbose=False)
                temp_ica = mne.preprocessing.read_ica(ica_path, verbose=False)
            except Exception as e:
                print(f"    ✗ Failed to read files, skipping: {e}")
                continue

            # Get topography matrix
            topo_maps = temp_ica.get_components()

            # Record channel information
            if n_channels is None:
                n_channels = topo_maps.shape[0]
                channel_names = temp_ica.ch_names
                print(f"    Number of channels: {n_channels}")
                print(f"    Channel names: {channel_names[:5]}... (showing first 5)")
            elif topo_maps.shape[0] != n_channels:
                print(
                    f"    ⚠️  Warning: Subject {subj_id} has {topo_maps.shape[0]} channels, expected {n_channels}, skipping!"
                )
                continue

            # Extract ECG topographies
            ecg_indices = labels.get("ecg", [])
            for idx in ecg_indices:
                if idx < topo_maps.shape[1]:
                    ecg_topo = topo_maps[:, idx]
                    ecg_templates.append(ecg_topo)
                    dataset_ecg_count += 1
                    print(f"    ✓ Added ECG IC: {idx}")
                else:
                    print(f"    ✗ Warning: ECG IC {idx} out of range (max: {topo_maps.shape[1] - 1})")

            # Extract EOG topographies
            eog_indices = labels.get("eog", [])
            for idx in eog_indices:
                if idx < topo_maps.shape[1]:
                    eog_topo = topo_maps[:, idx]
                    eog_templates.append(eog_topo)
                    dataset_eog_count += 1
                    print(f"    ✓ Added EOG IC: {idx}")
                else:
                    print(f"    ✗ Warning: EOG IC {idx} out of range (max: {topo_maps.shape[1] - 1})")

            processed_subjects.append(subj_id)

        # Record dataset information
        dataset_info = {
            "dataset_name": dataset_name,
            "n_subjects": len(processed_subjects),
            "subjects": processed_subjects,
            "n_ecg_ics": dataset_ecg_count,
            "n_eog_ics": dataset_eog_count,
            "added_time": datetime.now().isoformat(),
        }
        datasets_info.append(dataset_info)

        print(f"\n  Dataset '{dataset_name}' statistics:")
        print(f"    Processed subjects: {len(processed_subjects)}")
        print(f"    New ECG templates: {dataset_ecg_count}")
        print(f"    New EOG templates: {dataset_eog_count}")

    # Save templates
    print(f"\n{'=' * 70}")
    print(f"Saving Template Files")
    print(f"{'=' * 70}")

    if ecg_templates:
        ecg_templates = np.array(ecg_templates)
        np.save(ecg_filename, ecg_templates)
        print(f"✓ Saved {len(ecg_templates)} ECG templates to {os.path.basename(ecg_filename)}")
    else:
        ecg_templates = np.array([]).reshape(0, n_channels if n_channels else 1)
        print(f"✗ No ECG templates found")

    if eog_templates:
        eog_templates = np.array(eog_templates)
        np.save(eog_filename, eog_templates)
        print(f"✓ Saved {len(eog_templates)} EOG templates to {os.path.basename(eog_filename)}")
    else:
        eog_templates = np.array([]).reshape(0, n_channels if n_channels else 1)
        print(f"✗ No EOG templates found")

    # Save metadata
    meta_info = {
        "device_type": device_type,
        "n_channels": n_channels,
        "channel_names": channel_names,
        "n_ecg_templates": len(ecg_templates),
        "n_eog_templates": len(eog_templates),
        "n_datasets": len(datasets_info),
        "datasets": datasets_info,
        "last_updated": datetime.now().isoformat(),
    }

    with open(meta_filename, "w") as f:
        json.dump(meta_info, f, indent=2)
    print(f"✓ Saved metadata to {os.path.basename(meta_filename)}")

    # Print summary
    print(f"\n{'=' * 70}")
    print(f"Template Creation Complete")
    print(f"{'=' * 70}")
    print(f"Device Type: {device_type}")
    print(f"Number of Datasets: {len(datasets_info)}")
    print(f"Dataset List: {[d['dataset_name'] for d in datasets_info]}")
    print(f"Total ECG Templates: {len(ecg_templates)}")
    print(f"Total EOG Templates: {len(eog_templates)}")
    print(f"{'=' * 70}\n")

    return ecg_templates, eog_templates


def load_templates(device_type, save_dir="./ica_templates"):
    """
    Load templates for specified device type

    Parameters:
    -----------
    device_type : str
        Device type: 'elekta', 'kit', 'ctf', '4d', 'opm', 'eeg'
    save_dir : str
        Template directory

    Returns:
    --------
    ecg_templates : ndarray
    eog_templates : ndarray
    meta_info : dict
    """
    ecg_filename = os.path.join(save_dir, f"ecg_templates_{device_type}.npy")
    eog_filename = os.path.join(save_dir, f"eog_templates_{device_type}.npy")
    meta_filename = os.path.join(save_dir, f"template_meta_{device_type}.json")

    # Check file existence
    if not os.path.exists(meta_filename):
        raise FileNotFoundError(
            f"Template files for device type '{device_type}' not found!\n"
            f"Please run create_templates_from_config() first.\n"
            f"Looking for: {meta_filename}"
        )

    # Load metadata
    with open(meta_filename, "r") as f:
        meta_info = json.load(f)

    # Load templates
    ecg_templates = np.load(ecg_filename) if os.path.exists(ecg_filename) else np.array([])
    eog_templates = np.load(eog_filename) if os.path.exists(eog_filename) else np.array([])

    print(f"✓ Loaded templates:")
    print(f"  Device Type: {device_type}")
    print(f"  Number of Datasets: {meta_info.get('n_datasets', 0)}")
    print(f"  Dataset List: {[d['dataset_name'] for d in meta_info.get('datasets', [])]}")
    print(f"  ECG Templates: {len(ecg_templates)}")
    print(f"  EOG Templates: {len(eog_templates)}")
    print(f"  Number of Channels: {meta_info['n_channels']}")

    return ecg_templates, eog_templates, meta_info


def list_available_templates(save_dir="./ica_templates"):
    """List all available templates"""
    if not os.path.exists(save_dir):
        print(f"Template directory does not exist: {save_dir}")
        return

    print(f"\n{'=' * 70}")
    print(f"Available Templates")
    print(f"{'=' * 70}")

    meta_files = [f for f in os.listdir(save_dir) if f.startswith("template_meta_") and f.endswith(".json")]

    if not meta_files:
        print("No template files found")
        return

    for meta_file in sorted(meta_files):
        with open(os.path.join(save_dir, meta_file), "r") as f:
            meta = json.load(f)

        print(f"\nDevice Type: {meta['device_type']}")
        print(f"  ECG Templates: {meta['n_ecg_templates']}")
        print(f"  EOG Templates: {meta['n_eog_templates']}")
        print(f"  Number of Datasets: {meta.get('n_datasets', 0)}")
        print(f"  Dataset List: {[d['dataset_name'] for d in meta.get('datasets', [])]}")
        print(f"  Last Updated: {meta.get('last_updated', 'Unknown')}")

    print(f"{'=' * 70}\n")


# ============ Similarity Calculator and Artifact Detector ============
class TopoSimilarityCalculator:
    """Calculate topography similarity using multiple methods"""

    @staticmethod
    def pearson_correlation(topo1, topo2):
        """Pearson correlation coefficient (most common)"""
        corr, _ = pearsonr(topo1.flatten(), topo2.flatten())
        return abs(corr)

    @staticmethod
    def spearman_correlation(topo1, topo2):
        """Spearman rank correlation (robust to outliers)"""
        corr, _ = spearmanr(topo1.flatten(), topo2.flatten())
        return abs(corr)

    @staticmethod
    def cosine_similarity(topo1, topo2):
        """Cosine similarity"""
        return 1 - cosine(topo1.flatten(), topo2.flatten())

    @staticmethod
    def euclidean_similarity(topo1, topo2):
        """Normalized Euclidean distance"""
        topo1_norm = (topo1 - topo1.min()) / (topo1.max() - topo1.min() + 1e-10)
        topo2_norm = (topo2 - topo2.min()) / (topo2.max() - topo2.min() + 1e-10)

        dist = np.linalg.norm(topo1_norm - topo2_norm)
        max_dist = np.sqrt(len(topo1.flatten()))
        return 1 - (dist / max_dist)

    @staticmethod
    def compute_all_similarities(topo1, topo2):
        """Compute all similarity metrics"""
        calc = TopoSimilarityCalculator

        similarities = {
            "pearson": calc.pearson_correlation(topo1, topo2),
            "spearman": calc.spearman_correlation(topo1, topo2),
            "cosine": calc.cosine_similarity(topo1, topo2),
            "euclidean": calc.euclidean_similarity(topo1, topo2),
        }

        similarities["mean"] = np.mean(list(similarities.values()))

        return similarities


class ICArtifactDetector:
    def __init__(self, ecg_templates, eog_templates, meta_info=None):
        """
        ecg_templates: shape (n_ecg_templates, n_channels)
        eog_templates: shape (n_eog_templates, n_channels)
        meta_info: dict (contains device type, channel names, etc.)
        """
        self.ecg_templates = ecg_templates
        self.eog_templates = eog_templates
        self.meta_info = meta_info or {}
        self.device_type = self.meta_info.get("device_type", None)
        self.template_n_channels = self.meta_info.get("n_channels", None)
        self.template_ch_names = self.meta_info.get("channel_names", None)
        self.calc = TopoSimilarityCalculator()

    def _align_channels(self, ica):
        """Align ICA channels with template channels"""
        if self.template_ch_names is None:
            raise ValueError("Template metadata missing channel names, cannot align channels")

        ica_ch_names = ica.ch_names

        common_channels = []
        template_indices = []
        ica_indices = []

        for i, ch_name in enumerate(self.template_ch_names):
            if ch_name in ica_ch_names:
                j = ica_ch_names.index(ch_name)
                common_channels.append(ch_name)
                template_indices.append(i)
                ica_indices.append(j)

        if len(common_channels) == 0:
            raise ValueError("No common channel names between ICA and templates!")

        print(f"  Channel alignment info:")
        print(f"    Template channels: {len(self.template_ch_names)}")
        print(f"    ICA channels: {len(ica_ch_names)}")
        print(f"    Common channels: {len(common_channels)}")

        if len(common_channels) < len(self.template_ch_names):
            missing = set(self.template_ch_names) - set(ica_ch_names)
            print(f"    ⚠️  {len(missing)} template channels missing in ICA: {list(missing)[:5]}...")

        if len(common_channels) < len(ica_ch_names):
            extra = set(ica_ch_names) - set(self.template_ch_names)
            print(f"    ⚠️  {len(extra)} ICA channels missing in template: {list(extra)[:5]}...")

        return np.array(template_indices), np.array(ica_indices)

    def classify_component(self, ic_topo, method="pearson", threshold=0.7, use_ensemble=True):
        """Classify a single IC component"""
        max_ecg_sim = 0
        max_eog_sim = 0

        ecg_sims = []
        if len(self.ecg_templates) > 0:
            for template in self.ecg_templates:
                if use_ensemble:
                    sims = self.calc.compute_all_similarities(ic_topo, template)
                    sim = sims[method]
                else:
                    if method == "pearson":
                        sim = self.calc.pearson_correlation(ic_topo, template)
                    elif method == "spearman":
                        sim = self.calc.spearman_correlation(ic_topo, template)
                    elif method == "cosine":
                        sim = self.calc.cosine_similarity(ic_topo, template)
                    elif method == "euclidean":
                        sim = self.calc.euclidean_similarity(ic_topo, template)

                ecg_sims.append(sim)
                max_ecg_sim = max(max_ecg_sim, sim)

        eog_sims = []
        if len(self.eog_templates) > 0:
            for template in self.eog_templates:
                if use_ensemble:
                    sims = self.calc.compute_all_similarities(ic_topo, template)
                    sim = sims[method]
                else:
                    if method == "pearson":
                        sim = self.calc.pearson_correlation(ic_topo, template)
                    elif method == "spearman":
                        sim = self.calc.spearman_correlation(ic_topo, template)
                    elif method == "cosine":
                        sim = self.calc.cosine_similarity(ic_topo, template)
                    elif method == "euclidean":
                        sim = self.calc.euclidean_similarity(ic_topo, template)

                eog_sims.append(sim)
                max_eog_sim = max(max_eog_sim, sim)

        if max_ecg_sim > threshold and max_ecg_sim > max_eog_sim:
            label = "ECG"
            similarity = max_ecg_sim
        elif max_eog_sim > threshold:
            label = "EOG"
            similarity = max_eog_sim
        else:
            label = "Brain"
            similarity = max(max_ecg_sim, max_eog_sim)

        details = {
            "ecg_max": max_ecg_sim,
            "eog_max": max_eog_sim,
            "ecg_mean": np.mean(ecg_sims) if ecg_sims else 0,
            "eog_mean": np.mean(eog_sims) if eog_sims else 0,
        }

        return label, similarity, details

    def classify_all_components(self, ica, method="pearson", threshold=0.7):
        """Classify all ICA components"""
        topo_maps = ica.get_components()

        print(f"\n{'=' * 70}")
        print(f"IC Classification Results (Method: {method}, Threshold: {threshold})")
        if self.device_type:
            print(f"Device Type: {self.device_type}")
        if self.meta_info.get("datasets"):
            datasets = [d["dataset_name"] for d in self.meta_info["datasets"]]
            print(f"Using templates from: {datasets}")
        print(f"{'=' * 70}")

        if self.template_n_channels is not None:
            if topo_maps.shape[0] != self.template_n_channels:
                print(f"⚠️  Channel count mismatch!")
                print(f"  Template channels: {self.template_n_channels}")
                print(f"  ICA channels: {topo_maps.shape[0]}")
                print(f"  Attempting channel alignment...\n")

                template_idx, ica_idx = self._align_channels(ica)

                aligned_ecg_templates = (
                    self.ecg_templates[:, template_idx] if len(self.ecg_templates) > 0 else self.ecg_templates
                )
                aligned_eog_templates = (
                    self.eog_templates[:, template_idx] if len(self.eog_templates) > 0 else self.eog_templates
                )
                aligned_topo_maps = topo_maps[ica_idx, :]

                print(f"  ✓ Channel alignment complete, using {len(template_idx)} common channels for classification\n")
            else:
                aligned_ecg_templates = self.ecg_templates
                aligned_eog_templates = self.eog_templates
                aligned_topo_maps = topo_maps
        else:
            aligned_ecg_templates = self.ecg_templates
            aligned_eog_templates = self.eog_templates
            aligned_topo_maps = topo_maps

        original_ecg = self.ecg_templates
        original_eog = self.eog_templates
        self.ecg_templates = aligned_ecg_templates
        self.eog_templates = aligned_eog_templates

        results = []
        bad_ics = []
        ecg_ics = []
        eog_ics = []

        print(f"{'IC':<5} {'Label':<8} {'Similarity':<10} {'ECG Max':<10} {'EOG Max':<10}")
        print(f"{'-' * 70}")

        for i in range(ica.n_components_):
            ic_topo = aligned_topo_maps[:, i]
            label, similarity, details = self.classify_component(ic_topo, method=method, threshold=threshold)

            results.append({"ic_index": i, "label": label, "similarity": similarity, "details": details})

            if label in ["ECG", "EOG"]:
                bad_ics.append(i)
            if label in ["ECG"]:
                ecg_ics.append(i)
            if label in ["EOG"]:
                eog_ics.append(i)

            print(f"{i:<5} {label:<8} {similarity:<10.3f} {details['ecg_max']:<10.3f} {details['eog_max']:<10.3f}")

        self.ecg_templates = original_ecg
        self.eog_templates = original_eog

        print(f"{'=' * 70}")
        print(f"Detected artifact components: {bad_ics}")
        print(f"{'=' * 70}\n")

        return results, bad_ics, ecg_ics, eog_ics


def plot_ica_results(ica, raw, bad_ics, save_dir=None):
    """Plot ICA results visualizations"""
    try:
        import matplotlib

        if save_dir is not None:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        print("\nPlotting visualizations...")

        fig = ica.plot_components(picks=range(ica.n_components_), show=False)  # min(20, ica.n_components_)
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
            plt.savefig(os.path.join(save_dir, "ica_components.png"), dpi=150, bbox_inches="tight")
            print(f"  ✓ Saved IC component topographies to: {os.path.join(save_dir, 'ica_components.png')}")
            plt.close(fig)
        else:
            plt.show()

        if bad_ics:
            try:
                sources = ica.get_sources(raw)
                fig, axes = plt.subplots(len(bad_ics), 1, figsize=(12, 2 * len(bad_ics)))
                if len(bad_ics) == 1:
                    axes = [axes]

                for idx, ic in enumerate(bad_ics):
                    data = sources.get_data()[ic, :10000]
                    times = sources.times[:10000]
                    axes[idx].plot(times, data)
                    axes[idx].set_ylabel(f"IC {ic}")
                    axes[idx].set_title(f"Independent Component {ic} (Artifact)")

                axes[-1].set_xlabel("Time (s)")
                plt.tight_layout()

                if save_dir:
                    plt.savefig(os.path.join(save_dir, "bad_ics_timeseries.png"), dpi=150, bbox_inches="tight")
                    print(f"  ✓ Saved artifact IC time series to: {os.path.join(save_dir, 'bad_ics_timeseries.png')}")
                    plt.close(fig)
                else:
                    plt.show()
            except Exception as e:
                print(f"  ⚠️  Error plotting time series: {e}")

        print("  ✓ Visualization complete")

    except Exception as e:
        print(f"  ⚠️  Visualization failed: {e}")


def _get_ic_status(
    ic: int, votes: int, min_votes: int, total_methods: int, ecg_list: List[int], eog_list: List[int]
) -> str:
    """
    Get status label for an IC component.

    Parameters
    ----------
    ic : int
        IC component index
    votes : int
        Number of votes received
    min_votes : int
        Minimum vote threshold
    total_methods : int
        Total number of methods
    ecg_list : list
        List of ECG artifact ICs
    eog_list : list
        List of EOG artifact ICs

    Returns
    -------
    str
        Status description string
    """
    if votes < min_votes:
        return "✗ Retained"

    if ic in ecg_list:
        return "✓ Marked as ECG artifact"
    elif ic in eog_list:
        return "✓ Marked as EOG artifact"
    else:
        return "✓ Marked as artifact"


def find_ecg_eog_ics(ica_file, device_type: str = "elekta") -> Dict[str, List[int]]:
    """
    Identify ECG and EOG artifact components in ICA decomposition.

    Uses multiple correlation methods to classify ICA components, determining
    final artifact components through a voting mechanism.

    Parameters
    ----------
    ica_file : The file of mne.preprocessing.ICA
        Fitted ICA object file.
    device_type : str, optional
        Type of MEG/EEG device. Default is 'elekta'.
        Other options may include 'neuromag', 'ctf', etc., depending on
        available templates.

    Returns
    -------
    dict
        Dictionary containing two keys:
        - 'ic_eog': List of EOG artifact component indices
        - 'ic_ecg': List of ECG artifact component indices
    """
    # Constants definition
    SAVE_DIR = Path(__file__).parent / "ica_templates"
    CORRELATION_THRESHOLD = 0.6
    MIN_VOTES = 2
    METHODS = ["pearson", "spearman", "cosine", "mean"]
    ica = mne.preprocessing.read_ica(ica_file, verbose=False)
    device_type, skip_reason = resolve_template_device_type(device_type, ica=ica, save_dir=SAVE_DIR)
    if device_type is None:
        print(f"Template similarity skipped: {skip_reason}")
        return {"ic_ecg": [], "ic_eog": []}

    # Load all templates for specified device
    ecg_templates, eog_templates, meta_info = load_templates(device_type=device_type, save_dir=SAVE_DIR)

    # Create artifact detector
    detector = ICArtifactDetector(ecg_templates, eog_templates, meta_info=meta_info)

    # Classify using different methods
    all_results = {}
    ecg_ics_all = []
    eog_ics_all = []

    for method in METHODS:
        print(f"\nUsing {method.upper()} method:")
        results, bad_ics, ecg_ics, eog_ics = detector.classify_all_components(
            ica, method=method, threshold=CORRELATION_THRESHOLD
        )
        all_results[method] = bad_ics
        ecg_ics_all.extend(ecg_ics)
        eog_ics_all.extend(eog_ics)

    # Remove duplicates
    ecg_ics_all = list(set(ecg_ics_all))
    eog_ics_all = list(set(eog_ics_all))

    # Ensemble results using voting
    print("\n" + "=" * 70)
    print("Ensemble results (voting method)")
    print("=" * 70)

    # Count how many times each IC was marked as artifact
    all_bad_ics = []
    for bad_ics in all_results.values():
        all_bad_ics.extend(bad_ics)

    ic_votes = Counter(all_bad_ics)

    # Determine final artifact ICs (identified by at least MIN_VOTES methods)
    final_bad_ics = [ic for ic, votes in ic_votes.items() if votes >= MIN_VOTES]

    # Print voting results
    print(f"\nVoting results:")
    for ic, votes in sorted(ic_votes.items()):
        status = _get_ic_status(ic, votes, MIN_VOTES, len(METHODS), ecg_ics_all, eog_ics_all)
        print(f"  IC {ic}: {votes}/{len(METHODS)} methods identified as artifact [{status}]")

    # Classify final artifact ICs
    ecg_artifacts = []
    eog_artifacts = []

    for ic in final_bad_ics:
        if ic in ecg_ics_all:
            ecg_artifacts.append(ic)
        elif ic in eog_ics_all:
            eog_artifacts.append(ic)

    print(f"\nFinal artifact ICs (at least {MIN_VOTES} methods): {final_bad_ics}")

    return {"ic_eog": sorted(eog_artifacts), "ic_ecg": sorted(ecg_artifacts)}


# ============ Complete Workflow Examples ============
if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("Example 1: Create templates from first dataset")
    print("=" * 70)

    # Configuration 1: BTH dataset |elekta
    config_bth = TemplateConfig("BTH_lifespan", "elekta")

    labels_bth = {
        1: {"ecg": [5, 17, 70], "eog": [41]},
        4: {"ecg": [19, 76], "eog": [0]},
        5: {"ecg": [2], "eog": [0]},
        6: {"ecg": [9], "eog": []},
        12: {"ecg": [2, 4], "eog": [0]},
    }

    config_bth.add_subjects_from_pattern(
        subj_ids=[1, 4, 5, 6, 12],
        raw_pattern="/home/changpsyshi1/changping/lifespan-meeg/derivatives_rest/process_1/BTH/sub-{subj:03d}_ecr_raw_tsss_mc_preprocessed.fif",
        ica_pattern="/home/changpsyshi1/changping/lifespan-meeg/derivatives_rest/process_4/BTH/sub-{subj:03d}_ecr_raw_tsss_mc/ica.fif",
        labels_dict=labels_bth,
    )

    # Create templates (first time)
    ecg_templates, eog_templates = create_templates_from_config(
        config=config_bth,
        save_dir="./ica_templates",
        mode="overwrite",  # First time creation
    )

    # Configuration 2: MEG-MASC dataset | KIT
    config_bth = TemplateConfig("MEG-MASC_lifespan", "kit")

    labels_bth = {
        "01": {"ecg": [1, 5], "eog": [0, 2, 3, 4]},
        "02": {"ecg": [1, 3], "eog": [0, 5, 9, 10]},
    }

    config_bth.add_subjects_from_pattern(
        subj_ids=["01", "02"],
        raw_pattern="/home/changpsyshi1/changping/lifespan-meeg/derivatives_rest/process_1/MEG-MASC/sub-{subj}_ses-0_task-0_meg_preprocessed.fif",
        ica_pattern="/home/changpsyshi1/changping/lifespan-meeg/preproc/demo/kit/sub-{subj}/ica.fif",
        labels_dict=labels_bth,
    )

    # add into templates
    ecg_templates, eog_templates = create_templates_from_config(
        config=config_bth, save_dir="./ica_templates", mode="overwrite"
    )
    # Configuration 3: HCP-MEG |4D
    config_bth = TemplateConfig("HCP-MEG_lifespan", "4d")

    labels_bth = {
        "100307": {"ecg": [1, 7], "eog": [3, 14]},
        "102816": {"ecg": [0, 1, 2, 3, 5], "eog": [4, 12, 15]},
    }

    config_bth.add_subjects_from_pattern(
        subj_ids=["100307", "102816"],
        raw_pattern="/home/changpsyshi1/changping/lifespan-meeg/preproc/{subj}_3-Resting.fif",
        ica_pattern="/home/changpsyshi1/changping/lifespan-meeg/preproc/demo/4d/{subj}/ica.fif",
        labels_dict=labels_bth,
    )

    # add into templates
    ecg_templates, eog_templates = create_templates_from_config(
        config=config_bth, save_dir="./ica_templates", mode="overwrite"
    )

    # Configuration 4: WAND dataset | CTF
    config_bth = TemplateConfig("WAND_lifespan", "ctf")

    labels_bth = {
        # '01945': {'ecg': [4], 'eog': [0,5]},
        "06180": {"ecg": [0, 2, 4], "eog": [1, 3]},
    }

    config_bth.add_subjects_from_pattern(
        subj_ids=["06180"],  #'01945' 通道数少一个ML051-3305，但ICA数量是274
        raw_pattern="/home/changpsyshi1/changping/lifespan-meeg/derivatives_rest/process_1/WAND/sub-{subj}_ses-01_task-resting_preprocessed.fif",
        ica_pattern="/home/changpsyshi1/changping/lifespan-meeg/preproc/demo/ctf/sub-{subj}/ica.fif",
        labels_dict=labels_bth,
    )

    # add into templates
    ecg_templates, eog_templates = create_templates_from_config(
        config=config_bth, save_dir="./ica_templates", mode="overwrite"
    )

    # print("\n" + "="*70)
    # print("Example 2: Append another dataset's templates (same device)")
    # print("="*70)

    # Configuration 2: Another elekta dataset
    # config_other = TemplateConfig('OtherStudy', 'elekta')

    # labels_other = {
    #     101: {'ecg': [2], 'eog': [0, 1]},
    #     102: {'ecg': [5], 'eog': [3]},
    # }

    # config_other.add_subjects_from_pattern(
    #     subj_ids=[101, 102],
    #     raw_pattern="/path/to/other/sub-{subj:03d}_raw.fif",
    #     ica_pattern="/path/to/other/sub-{subj:03d}_ica.fif",
    #     labels_dict=labels_other
    # )

    # Append to existing templates (commented out because paths don't exist)
    # ecg_templates, eog_templates = create_templates_from_config(
    #     config=config_other,
    #     save_dir='./ica_templates',
    #     mode='append'  # Append mode
    # )

    # print("\n" + "="*70)
    # print("Example 3: Process multiple datasets simultaneously")
    # print("="*70)

    # Process multiple datasets at once (commented out because second dataset paths don't exist)
    # ecg_templates, eog_templates = create_templates_from_config(
    #     config=[config_bth, config_other],  # Pass list of configurations
    #     save_dir='./ica_templates',
    #     mode='overwrite'
    # )

    print("\n" + "=" * 70)
    print("View available templates")
    print("=" * 70)

    list_available_templates("./ica_templates")

    print("\n" + "=" * 70)
    print("Load templates and classify")
    print("=" * 70)

    # Load all templates for elekta device
    ecg_templates, eog_templates, meta_info = load_templates(device_type="elekta", save_dir="./ica_templates")

    # Classify new subject
    test_subj = 5
    raw_path = f"/home/changpsyshi1/changping/lifespan-meeg/derivatives_rest/process_1/BTH/sub-{test_subj:03d}_ecr_raw_tsss_mc_preprocessed.fif"
    ica_path = f"/home/changpsyshi1/changping/lifespan-meeg/derivatives_rest/process_4/BTH/sub-{test_subj:03d}_ecr_raw_tsss_mc/ica.fif"

    # test_subj = 110033
    # raw_path = f"/home/changpsyshi1/changping/lifespan-meeg/derivatives_rest/process_1/CAM-CAN/sub-CC{test_subj}_task-rest_meg_preprocessed.fif"
    # ica_path = f"/home/changpsyshi1/changping/lifespan-meeg/derivatives_rest/process_4/CAM-CAN/sub-CC{test_subj}_task-rest_meg/ica.fif"

    test_raw = mne.io.read_raw(raw_path, preload=True, verbose=False)
    test_ica = mne.preprocessing.read_ica(ica_path, verbose=False)

    # Create detector
    detector = ICArtifactDetector(ecg_templates, eog_templates, meta_info=meta_info)

    # Classify using different methods
    methods = ["pearson", "spearman", "cosine", "mean"]
    all_results = {}

    for method in methods:
        print(f"\nUsing {method.upper()} method:")
        results, bad_ics, _, _ = detector.classify_all_components(test_ica, method=method, threshold=0.6)
        all_results[method] = bad_ics

    # Ensemble using voting
    print("\n" + "=" * 70)
    print("Ensemble results (voting method)")
    print("=" * 70)

    all_bad_ics = []
    for method, bad_ics in all_results.items():
        all_bad_ics.extend(bad_ics)

    ic_votes = Counter(all_bad_ics)
    min_votes = 2
    final_bad_ics = [ic for ic, votes in ic_votes.items() if votes >= min_votes]

    print(f"\nVoting results:")
    for ic, votes in sorted(ic_votes.items()):
        status = "✓ Marked as artifact" if votes >= min_votes else "✗ Retained"
        print(f"  IC {ic}: {votes}/{len(methods)} methods identified as artifact [{status}]")

    print(f"\nFinal artifact ICs (at least {min_votes} methods): {final_bad_ics}")

    # Apply ICA to remove artifacts
    if final_bad_ics:
        test_ica.exclude = final_bad_ics
        raw_clean = test_ica.apply(test_raw.copy())
        print(f"\n✓ Applied ICA to remove artifacts")
    else:
        print(f"\n⚠️  No artifacts detected, no cleaning needed")

    # Visualize
    plot_ica_results(test_ica, test_raw, final_bad_ics, save_dir="./ica_plots")

    print("\n✓ Complete!")
