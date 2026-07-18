# !/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Provide an inteface to label each ICA component into one of seven categories:
- Brain
- Muscle
- Eye
- Heart
- Line Noise
- Channel Noise
- Other
"""
import logging
import os
import json
import yaml
import argparse
import mne
import numpy as np
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tools.ica_classify.ICs_classification import classify_ics
from utils import set_random_seed
from collections import defaultdict

set_random_seed(2025)


CANONICAL_MEGNET_CLASSES = (
    "brain_or_other",
    "heart_beat",
    "eye_blink",
    "eye_movement",
)
MNE_MEGNET_NATIVE_CLASSES = (
    "brain_or_other",
    "eye_movement",
    "heart_beat",
    "eye_blink",
)
ICA_CATEGORY_DEFAULTS = {
    "ecg": True,
    "eog": True,
    "outlier": False,
}


@dataclass
class DetectorOutcome:
    artifact_indices: list
    ecg_indices: list
    eog_indices: list
    probabilities: object
    detail: dict



def calculate_flat_ratio(signal, threshold=0):
    """ check ecg/eog signals and calculate flat ratio
    """
    flat_count = 0  
    total_count = len(signal)  

    for i in range(1, total_count):  
        if abs(signal[i] - signal[i - 1]) <= threshold:  
            flat_count += 1  

    flat_ratio = flat_count / total_count  
    return flat_ratio


def unique_ints(values, max_value=None):
    result = []
    for value in values or []:
        try:
            idx = int(value)
        except Exception:
            continue
        if idx < 0:
            continue
        if max_value is not None and idx >= max_value:
            continue
        if idx not in result:
            result.append(idx)
    return result


def resolve_category_switches(config):
    resolved = {}
    for category, default in ICA_CATEGORY_DEFAULTS.items():
        key = f"ic_{category}"
        value = config.get(key, default)
        if not isinstance(value, bool):
            raise TypeError(f"{key} must be a boolean")
        resolved[category] = value
    return resolved


def filter_category_indices(category_indices, categories, n_components=None):
    return {
        category: (
            sorted(unique_ints(category_indices.get(category, []), n_components))
            if categories[category]
            else []
        )
        for category in ICA_CATEGORY_DEFAULTS
    }


def should_generate_labels(
    output_file,
    *,
    overwrite_existing=False,
    refresh_existing=False,
):
    return (
        bool(overwrite_existing)
        or bool(refresh_existing)
        or not Path(output_file).exists()
    )


def read_marked_component_indices(output_file):
    path = Path(output_file)
    if not path.is_file():
        return None
    return sorted(unique_ints(path.read_text(encoding="utf-8").splitlines()))


def read_marked_component_metadata(scores_file):
    path = Path(scores_file)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    metadata = payload.get("marked_components")
    return metadata if isinstance(metadata, dict) else None


def resolve_marked_component_output(
    *,
    auto_indices,
    existing_indices=None,
    previous_metadata=None,
    overwrite_existing=False,
    refresh_existing=False,
):
    auto_indices = sorted(unique_ints(auto_indices))
    if existing_indices is None or overwrite_existing:
        return auto_indices, "auto"

    existing_indices = sorted(unique_ints(existing_indices))
    if refresh_existing and isinstance(previous_metadata, dict):
        previous_mode = previous_metadata.get("mode")
        previous_written = previous_metadata.get(
            "written_indices",
            previous_metadata.get("auto_indices", []),
        )
        previous_written = sorted(unique_ints(previous_written))
        if previous_mode == "auto" and existing_indices == previous_written:
            return auto_indices, "auto"

    return existing_indices, "preserved_manual"


def append_component_score(scores_dict, kind, component_idx, score=0.5):
    index_key = f"{kind}_indices"
    if component_idx in scores_dict[index_key]:
        position = scores_dict[index_key].index(component_idx)
        current_score = (
            float(scores_dict[kind][position])
            if position < len(scores_dict[kind])
            else float("-inf")
        )
        if float(score) > current_score:
            if position < len(scores_dict[kind]):
                scores_dict[kind][position] = float(score)
            else:
                scores_dict[kind].append(float(score))
        return
    scores_dict[index_key].append(int(component_idx))
    scores_dict[kind].append(float(score))


def normalize_score_dict(scores_dict, n_components=None):
    normalized = {}
    for kind in ["ecg", "eog"]:
        indices = scores_dict.get(f"{kind}_indices", [])
        scores = scores_dict.get(kind, [])
        best_scores = {}
        for pos, component_idx in enumerate(indices):
            try:
                idx = int(component_idx)
            except Exception:
                continue
            if idx < 0 or (n_components is not None and idx >= n_components):
                continue
            try:
                score = float(scores[pos])
            except Exception:
                score = 0.5
            best_scores[idx] = max(score, best_scores.get(idx, float("-inf")))
        sorted_indices = sorted(best_scores)
        normalized[f"{kind}_indices"] = sorted_indices
        normalized[kind] = [best_scores[idx] for idx in sorted_indices]
    for key, values in scores_dict.items():
        if key not in normalized:
            normalized[key] = values
    return normalized


def finalize_score_payload(
    scores_dict,
    *,
    category_indices,
    written_indices,
    marked_output_mode,
    n_components,
):
    normalized_categories = {
        category: sorted(
            unique_ints(category_indices.get(category, []), n_components)
        )
        for category in ICA_CATEGORY_DEFAULTS
    }
    payload = normalize_score_dict(scores_dict, n_components)
    for category in ("ecg", "eog"):
        score_by_index = dict(
            zip(
                payload.get(f"{category}_indices", []),
                payload.get(category, []),
            )
        )
        payload[f"{category}_indices"] = normalized_categories[category]
        payload[category] = [
            float(score_by_index.get(component_idx, 0.5))
            for component_idx in normalized_categories[category]
        ]
    payload["outlier_indices"] = normalized_categories["outlier"]

    auto_indices = sorted(
        {
            component_idx
            for indices in normalized_categories.values()
            for component_idx in indices
        }
    )
    payload["marked_components"] = {
        "mode": marked_output_mode,
        "auto_indices": auto_indices,
        "written_indices": sorted(unique_ints(written_indices, n_components)),
    }
    return payload


def canonicalize_mne_megnet_probabilities(probabilities):
    probabilities = np.asarray(probabilities, dtype=np.float32)
    if probabilities.ndim != 2 or probabilities.shape[1] != 4:
        raise ValueError("MNE MEGNet probabilities must contain four class columns")
    native_index = {
        class_name: index for index, class_name in enumerate(MNE_MEGNET_NATIVE_CLASSES)
    }
    return probabilities[
        :,
        [native_index[class_name] for class_name in CANONICAL_MEGNET_CLASSES],
    ]


def detector_outcome_from_probabilities(method_name, probabilities, metadata=None):
    probabilities = np.asarray(probabilities, dtype=np.float32)
    if probabilities.ndim != 2 or probabilities.shape[1] != 4:
        raise ValueError("MEGNet probabilities must contain four class columns")
    if not np.isfinite(probabilities).all():
        raise ValueError("MEGNet probabilities contain non-finite values")

    label_indices = probabilities.argmax(axis=1)
    labels = [CANONICAL_MEGNET_CLASSES[index] for index in label_indices.tolist()]
    artifact_indices = [
        index for index, label in enumerate(labels) if label != "brain_or_other"
    ]
    ecg_indices = [
        index for index, label in enumerate(labels) if label == "heart_beat"
    ]
    eog_indices = [
        index
        for index, label in enumerate(labels)
        if label in {"eye_blink", "eye_movement"}
    ]
    detail = {
        "method": method_name,
        "status": "succeeded",
        "class_order": list(CANONICAL_MEGNET_CLASSES),
        "labels": labels,
        "probabilities": probabilities.astype(float).tolist(),
        "artifact_indices": artifact_indices,
        "ecg_indices": ecg_indices,
        "eog_indices": eog_indices,
        "metadata": dict(metadata or {}),
    }
    return DetectorOutcome(
        artifact_indices=artifact_indices,
        ecg_indices=ecg_indices,
        eog_indices=eog_indices,
        probabilities=probabilities,
        detail=detail,
    )


def filter_detector_outcome(outcome, categories):
    ecg_indices = list(outcome.ecg_indices) if categories["ecg"] else []
    eog_indices = list(outcome.eog_indices) if categories["eog"] else []
    artifact_indices = sorted(set(ecg_indices + eog_indices))
    labels = outcome.detail.get("labels", [])
    probabilities = outcome.probabilities
    detections = {}

    for category, indices in (("ecg", ecg_indices), ("eog", eog_indices)):
        category_detections = []
        for component_idx in indices:
            label = labels[component_idx]
            class_idx = CANONICAL_MEGNET_CLASSES.index(label)
            category_detections.append(
                {
                    "index": int(component_idx),
                    "label": label,
                    "score": float(probabilities[component_idx, class_idx]),
                }
            )
        if category_detections:
            detections[category] = category_detections

    detail = {
        key: value
        for key, value in outcome.detail.items()
        if key
        not in {
            "labels",
            "probabilities",
            "artifact_indices",
            "ecg_indices",
            "eog_indices",
        }
    }
    detail.update(
        {
            "artifact_indices": artifact_indices,
            "ecg_indices": ecg_indices,
            "eog_indices": eog_indices,
            "detections": detections,
        }
    )
    if categories["ecg"] and categories["eog"]:
        detail["labels"] = list(labels)
        detail["probabilities"] = outcome.detail.get("probabilities", [])
    return DetectorOutcome(
        artifact_indices=artifact_indices,
        ecg_indices=ecg_indices,
        eog_indices=eog_indices,
        probabilities=probabilities,
        detail=detail,
    )


def run_mne_megnet_detector(raw, ica, predictor=None):
    if predictor is None:
        from mne_icalabel.megnet import megnet_label_components

        predictor = megnet_label_components
    native_probabilities = predictor(raw, ica)
    probabilities = canonicalize_mne_megnet_probabilities(native_probabilities)
    try:
        package_version = version("mne-icalabel")
    except PackageNotFoundError:
        package_version = None
    return detector_outcome_from_probabilities(
        "mne_icalabel",
        probabilities,
        metadata={
            "backend": "mne_icalabel.megnet",
            "mne_icalabel_version": package_version,
            "native_class_order": list(MNE_MEGNET_NATIVE_CLASSES),
        },
    )


def run_retrained_detector(
    raw,
    ica,
    *,
    ica_sources_file=None,
    predictor=None,
):
    try:
        if predictor is None:
            from tools.megnet_retrained import predict_components

            predictor = predict_components
        result = predictor(
            raw,
            ica,
            ica_sources_file=ica_sources_file,
        )
        return detector_outcome_from_probabilities(
            "megnet_retrained",
            result.probabilities,
            metadata=result.metadata,
        )
    except Exception as exc:
        logging.exception("[MEGNet-Retrained] Inference failed: %s", exc)
        return DetectorOutcome(
            artifact_indices=[],
            ecg_indices=[],
            eog_indices=[],
            probabilities=None,
            detail={
                "status": "failed",
                "class_order": list(CANONICAL_MEGNET_CLASSES),
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            },
        )


def _retrained_enabled(config):
    enabled = config.get("megnet_retrained", False)
    if not isinstance(enabled, bool):
        raise TypeError("megnet_retrained must be a boolean")
    return enabled


def run_configured_megnet_detectors(
    config,
    raw,
    ica,
    *,
    ica_sources_file=None,
    mne_predictor=None,
    retrained_predictor=None,
):
    categories = resolve_category_switches(config)
    if not categories["ecg"] and not categories["eog"]:
        return {}

    outcomes = {}
    if config.get("mne_icalabel", True):
        outcomes["mne_icalabel"] = filter_detector_outcome(
            run_mne_megnet_detector(
                raw,
                ica,
                predictor=mne_predictor,
            ),
            categories,
        )
    if _retrained_enabled(config):
        outcomes["megnet_retrained"] = filter_detector_outcome(
            run_retrained_detector(
                raw,
                ica,
                ica_sources_file=ica_sources_file,
                predictor=retrained_predictor,
            ),
            categories,
        )
    return outcomes


def merge_detector_scores(scores_dict, outcome):
    if outcome.probabilities is None:
        return
    for component_idx in outcome.ecg_indices:
        append_component_score(
            scores_dict,
            "ecg",
            component_idx,
            outcome.probabilities[component_idx, 1],
        )
    for component_idx in outcome.eog_indices:
        class_idx = int(outcome.probabilities[component_idx].argmax())
        append_component_score(
            scores_dict,
            "eog",
            component_idx,
            outcome.probabilities[component_idx, class_idx],
        )


def collect_exclude_indices(
    config,
    n_components,
    ic_ecg=None,
    ic_eog=None,
    ic_outlier=None,
):
    categories = resolve_category_switches(config)
    filtered = filter_category_indices(
        {
            "ecg": ic_ecg,
            "eog": ic_eog,
            "outlier": ic_outlier,
        },
        categories,
        n_components,
    )
    exclude_idx = []
    for indices in filtered.values():
        exclude_idx.extend(indices)
    return sorted(unique_ints(exclude_idx, n_components))


def main():
    args = parse_arguments()

    # debug
    # args.config = """
    #     # detect artifact ICs
    #     ic_ecg: true
    #     ic_eog: true
    #     ic_outlier: true # detect artifact ICs by rules.
    #
    #     mne_icalabel: true # original MEGNet
    #     megnet_retrained: false
    #     mne_algorithm: true
    #     rules_algorithm: true
    #
    #     # mne_algorithm
    #     find_bads_eog:
    #         ch_name: null # or the ch_name of EOG.
    #         threshold: auto
    #         l_freq: 1
    #         h_freq: 10
    #         start: null
    #         stop: null
    #         measure: zscore
    #
    #     find_bads_ecg:
    #         ch_name: null # or the ch_name of ECG.
    #         threshold: auto
    #         method: ctps
    #         l_freq: 8
    #         h_freq: 16
    #         measure: zscore
    #
    #     find_bads_muscle:
    #         threshold: 0.5
    #         start: null
    #         stop: null
    #         l_freq: 7
    #         h_freq: 45
    #
    #     # rules_algorithm
    #     ICA_classify:
    #         meg_vendor: ctf
    #         explained_var:
    #             threshold: 0.1
    #             ch_type: mag
    #         find_ecg_ics:
    #             time_segment: 10 # seconds
    #             ts_ecg_num_max: 20 # Maximum number of heartbeats expected in the chosen time segment
    #             l_freq: 0.1
    #             h_freq: 10
    #             peak_threshod_coef: 0.4 #Indicates the threshold of the number of ecg signal peak interval (unit: index). (peak_threshod = 0.4 * fs) | # for 1 seconds
    #             peak_std_threshold_coef: 0.05 #Standard deviation threshold of ecg signal peak interval (unit: index). (peak_std_threshold = peak_std_threshold_coef * fs) | # for 1 seconds
    #         find_abnormal_psd_ics:
    #             attention_low_freq: 0
    #             attention_high_freq: 150
    #             le_high_freq: 12
    #             low_freq_energy_threshold: 0.8 # Threshold above which the component is flagged by low-frequency energy ratio
    # """

    # Parse YAML configuration
    config = yaml.safe_load(args.config) or {}
    categories = resolve_category_switches(config)


    mne_ic_labels = {'y_pred_proba': [], 'labels': [], 'index': []}

    # Load MEG file
    raw = mne.io.read_raw(args.raw_data_path, preload=True)

    raw_basename = Path(raw.filenames[0]).parent.name

    artifact_ic_output_file = os.path.join(args.output_dir, raw_basename, "marked_components.txt")
    scores_output_file = os.path.join(args.output_dir, raw_basename, "ecg_eog_scores.json")

    os.makedirs(os.path.dirname(artifact_ic_output_file), exist_ok=True)
    existing_marked_components = read_marked_component_indices(
        artifact_ic_output_file
    )
    previous_marked_metadata = read_marked_component_metadata(scores_output_file)

    # Standalone runs preserve manual labels unless overwrite is explicit.
    if not should_generate_labels(
        artifact_ic_output_file,
        overwrite_existing=args.overwrite_existing,
        refresh_existing=args.refresh_existing,
    ):
        print(f"The file {artifact_ic_output_file} already exists, and the data will not be overwritten.")
    else:
        ic_ecg = []
        ic_eog = []
        ic_outlier = []
        scores_dict = {
            'ecg': [],
            'ecg_indices': [],
            'eog': [],
            'eog_indices': [],
            'outlier_indices': [],
        }
        scores_dict = defaultdict(list, scores_dict)
        # Load the ICA file
        ica = mne.preprocessing.read_ica(args.ica_file)
        n_components = int(ica.n_components_)

        if config.get('mne_algorithm',True):
            # mne-python
            # find which ICs match the EOG pattern
            if categories["eog"]:
                try:
                    # check eog flat.
                    if config["find_bads_eog"]['ch_name'] is not None:
                        for ref_ch_name in config["find_bads_eog"]['ch_name']:
                            logging.info("EOG Ref Channel " + ref_ch_name + "")
                            config["find_bads_eog"]['ch_name'] = ref_ch_name
                            print("EOG Ref Channel: " + ref_ch_name + "")
                            print("Measure Methods:",config["find_bads_eog"]['measure'])
                            print("Reference Channel Name: ",config["find_bads_eog"]['ch_name'])
                            eog_signal = raw.copy().pick(ref_ch_name).get_data()
                            flat_ratio = calculate_flat_ratio(eog_signal)
                            logging.info("The flat ratio of eog signal:",flat_ratio)
                            if flat_ratio > 0.1:
                                config["find_bads_eog"]['ch_name'] = None

                            eog_indices, eog_scores = ica.find_bads_eog(raw,**config.get("find_bads_eog", {}))
                            logging.info("EOG indices:{}, {}".format(eog_indices,eog_scores))
                            print(f"EOG indices({ref_ch_name}):{eog_indices}_eog_scores:{eog_scores}")
                            mne_ic_labels['index'].extend(eog_indices)
                            mne_ic_labels['labels'].extend(['EOG']*len(eog_indices))
                            mne_ic_labels['y_pred_proba'].extend(eog_scores[eog_indices])
                            ic_eog.extend(eog_indices)
                            for component_idx in eog_indices:
                                append_component_score(scores_dict, "eog", component_idx, eog_scores[component_idx])
                except Exception as e:
                    logging.error(f"[MNE-Python] Error:{e}")

            ic_eog = list(set(ic_eog))
            print(f"[MNE-Python]ic_eog:{ic_eog}")
            # find which ICs match the ECG pattern
            if categories["ecg"]:
                try:
                    # check ecg flat.
                    if config["find_bads_ecg"]['ch_name'] is not None:
                        ecg_signal = raw.copy().pick(config["find_bads_ecg"]['ch_name']).get_data()
                        flat_ratio = calculate_flat_ratio(ecg_signal)
                        print("The flat ratio of ecg signal:", flat_ratio)
                        if flat_ratio > 0.1:
                            config["find_bads_ecg"]['ch_name'] = None
                    ecg_indices, ecg_scores = ica.find_bads_ecg(raw, **config.get("find_bads_ecg", {}))
                    print("ECG indices:", ecg_indices,ecg_scores)
                    mne_ic_labels['index'].extend(ecg_indices)
                    mne_ic_labels['labels'].extend(['ECG'] * len(ecg_indices))
                    mne_ic_labels['y_pred_proba'].extend(ecg_scores[ecg_indices])
                    ic_ecg.extend(ecg_indices)
                    for component_idx in ecg_indices:
                        append_component_score(scores_dict, "ecg", component_idx, ecg_scores[component_idx])
                except Exception as e:
                    logging.error(e)

            if categories["outlier"]:
                try:
                    # Muscle-related ICs
                    muscle_indices, muscle_scores = ica.find_bads_muscle(raw,**config.get("find_bads_muscle", {}))
                    print("Muscle indices:", muscle_indices,muscle_scores)
                    mne_ic_labels['index'].extend(muscle_indices)
                    mne_ic_labels['labels'].extend(['MUSCLE'] * len(muscle_indices))
                    mne_ic_labels['y_pred_proba'].extend(muscle_scores[muscle_indices])
                    ic_outlier.extend(muscle_indices)
                except RuntimeError as e:
                    logging.error(e)

            print("mne_ic_labels:",mne_ic_labels)

        if config.get("rules_algorithm",True) and any(categories.values()):
            print("#"*50,"[ICA_classify]","#"*50)
            # ICA_classify[custom]
            marked_ics = []
            marked_ics_dict = {}
            try:
                ica_fit_file = args.ica_file
                ica_root_dir = Path(args.ica_file).parent
                ica_source_file = ica_root_dir / "ica_sources.fif"
                explained_var_file = ica_root_dir / "ica_explained_var.jl"
                ica_classify_config = dict(config.get("ICA_classify",{}) or {})
                ica_classify_config.update({
                    "collect_ecg_rules": categories["ecg"],
                    "collect_eog_rules": categories["eog"],
                    "collect_outlier_rules": categories["outlier"],
                })
                marked_ics,marked_ics_dict = classify_ics(ica_source_file,ica_fit_file,explained_var_file,ica_classify_config)
                rule_categories = filter_category_indices(
                    {
                        "ecg": marked_ics_dict.get('ic_ecg', []),
                        "eog": marked_ics_dict.get('ic_eog', []),
                        "outlier": marked_ics_dict.get('ic_outlier', []),
                    },
                    categories,
                    n_components,
                )
                rule_ecg = rule_categories["ecg"]
                rule_eog = rule_categories["eog"]
                rule_outlier = rule_categories["outlier"]
                ic_ecg.extend(rule_ecg)
                ic_eog.extend(rule_eog)
                ic_outlier.extend(rule_outlier)
                for component_idx in rule_ecg:
                    append_component_score(scores_dict, "ecg", component_idx, 0.5)  # rule-based score placeholder
                for component_idx in rule_eog:
                    append_component_score(scores_dict, "eog", component_idx, 0.5)  # rule-based score placeholder
                scores_dict['outlier_indices'].extend(rule_outlier)

                print("ic_ecg:",ic_ecg)
                print("ic_eog:",ic_eog)
                print("ic_outlier:",ic_outlier)

            except Exception as e:
                logging.error(f"ICA_classify Error:{e}")

        ica_sources_file = (
            Path(args.ica_sources_file)
            if args.ica_sources_file
            else Path(args.ica_file).parent / "ica_sources.fif"
        )
        if not ica_sources_file.is_file():
            ica_sources_file = None
        megnet_outcomes = run_configured_megnet_detectors(
            config,
            raw,
            ica,
            ica_sources_file=ica_sources_file,
        )
        scores_dict["methods"] = {
            method_name: outcome.detail
            for method_name, outcome in megnet_outcomes.items()
        }
        for method_name, outcome in megnet_outcomes.items():
            merge_detector_scores(scores_dict, outcome)
            ic_ecg.extend(outcome.ecg_indices)
            ic_eog.extend(outcome.eog_indices)
            print(
                f"[{method_name}] Component labels: {outcome.artifact_indices} "
                f"(status={outcome.detail['status']})"
            )

        # marked artifact IC
        category_indices = filter_category_indices(
            {
                "ecg": ic_ecg,
                "eog": ic_eog,
                "outlier": ic_outlier,
            },
            categories,
            n_components,
        )
        exclude_idx = collect_exclude_indices(
            config,
            n_components,
            ic_ecg=category_indices["ecg"],
            ic_eog=category_indices["eog"],
            ic_outlier=category_indices["outlier"],
        )
        print(f"run_ica_label - Exclude ICs:{exclude_idx}")

        written_indices, marked_output_mode = resolve_marked_component_output(
            auto_indices=exclude_idx,
            existing_indices=existing_marked_components,
            previous_metadata=previous_marked_metadata,
            overwrite_existing=args.overwrite_existing,
            refresh_existing=args.refresh_existing,
        )
        scores_dict = finalize_score_payload(
            scores_dict,
            category_indices=category_indices,
            written_indices=written_indices,
            marked_output_mode=marked_output_mode,
            n_components=n_components,
        )
        temporary_scores_file = f"{scores_output_file}.tmp"
        with open(temporary_scores_file, "w", encoding="utf-8") as handle:
            json.dump(scores_dict, handle, ensure_ascii=False, indent=4)
            handle.write("\n")
        os.replace(temporary_scores_file, scores_output_file)

        if marked_output_mode == "auto" or not os.path.exists(artifact_ic_output_file):
            temporary_marked_file = f"{artifact_ic_output_file}.tmp"
            with open(temporary_marked_file, "w", encoding="utf-8") as handle:
                for idx in written_indices:
                    handle.write(f"{idx}\n")
            os.replace(temporary_marked_file, artifact_ic_output_file)
        else:
            print(
                "Existing manually edited ICA components were preserved; "
                "automatic detector details were refreshed in "
                f"{scores_output_file}."
            )

        print(f"Labelled ICA saved to {args.output_dir}")

def parse_arguments():
    parser = argparse.ArgumentParser(description="Automatically label ICA components as artifacts using mne-icalabel.")
    parser.add_argument('--raw_data_path', required=True, help='Path to raw data file')
    parser.add_argument('--ica_file', required=True, help='Path to the precomputed ICA file.')
    parser.add_argument('--ica_sources_file', default=None, help='Optional matching precomputed ICA sources FIF.')
    parser.add_argument('--output_dir', required=True, help='Path to save the ICA-labelled file.(marked_components.txt)')
    existing_output_group = parser.add_mutually_exclusive_group()
    existing_output_group.add_argument('--overwrite-existing', action='store_true', help='Recompute and replace any existing ICA label outputs.')
    existing_output_group.add_argument('--refresh-existing', action='store_true', help='Refresh automatic outputs while preserving detected manual component edits.')
    parser.add_argument('--config', type=str, default="{}", help='YAML configuration parameters')
    return parser.parse_args()


if __name__ == "__main__":
    main()
