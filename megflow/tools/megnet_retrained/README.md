# Retrained MEGNet inference

This directory contains the inference-only `official_megnet2020_retrained`
ONNX model. It classifies ICA components as Brain/other, ECG, EOG blink, or EOG
movement and does not require the PyTorch training stack.

## MEGFlow integration

The original MNE-ICALabel MEGNet and this retrained model are independent:

```groovy
ic_label: [
    ic_ecg: true,
    ic_eog: true,
    ic_outlier: false,
    mne_icalabel: true,
    megnet_retrained: false
]
```

Both may be enabled. The method switches select models; `ic_ecg` and `ic_eog`
are master category gates shared with the MNE and rule-based detectors. A model
prediction contributes to `marked_components.txt` only when its category gate
is enabled. If both gates are false, MEGNet inference is skipped. If one is
false, detections from that class are omitted from both the JSON and text
outputs and are not reassigned using another class probability.

ECG and EOG summary scores are merged into `ecg_eog_scores.json`; duplicate
method/component assignments retain the maximum score. Complete four-class
labels and probabilities remain available under `methods` when both model
categories are enabled. With either category disabled, method details contain
only enabled-category detections so the JSON and final marked list remain
consistent.

The former `ica_label` key is not a compatibility alias. Use `mne_icalabel`.
`megnet_retrained` is a Boolean switch; the former `[enabled: ...]` mapping
form is not accepted.

Retrained inference is fail-soft inside `run_ic_label`: a model-specific
preprocessing, loading, or inference error is logged and stored as a failed
method entry, while other enabled detectors continue. Shared input and output
errors remain task-level failures.

## Sampling behavior

Inference never changes the input raw, ICA, or ICA-source FIF files. It uses an
in-memory ICA-source object with this fixed policy:

- above 250 Hz: temporarily downsample to 250 Hz;
- exactly 250 Hz: use unchanged;
- below 250 Hz: use the original sampling rate.

The recommended training condition is 1-100 Hz at 250 Hz, but the passband and
sampling rate are not hard input restrictions.

## Standalone inference

Install the small inference dependency set when running outside the complete
MEGFlow environment:

```bash
python -m pip install -r requirements.txt
```

Generate ICA sources from matching raw and ICA files:

```bash
python infer_ica_artifacts.py \
  --raw-file /path/to/preprocessed_raw.fif \
  --ica-file /path/to/ica.fif \
  --output-dir /path/to/output
```

Reuse an existing source file:

```bash
python infer_ica_artifacts.py \
  --raw-file /path/to/preprocessed_raw.fif \
  --ica-file /path/to/ica.fif \
  --ica-sources-file /path/to/ica_sources.fif \
  --output-dir /path/to/output
```

A supplied `ica_sources.fif` is checked for recording length, original
sampling rate, first sample, component names/order, and agreement with sources
recomputed over a short segment.

Standalone outputs are:

- `component_predictions.csv`: four probabilities and final class per component
- `ica_labels.json`: ECG, EOG-blink, and EOG-movement component indices
- `artifact_ics.txt`: all predicted artifact component indices
- `prediction_metadata.json`: input, sampling, model hash, provider, and timing metadata

## Original-versus-retrained agreement

The comparison utility runs both models on the same raw and ICA input:

```bash
python compare_with_mne_megnet.py \
  --raw-file /path/to/preprocessed_raw.fif \
  --ica-file /path/to/ica.fif \
  --ica-sources-file /path/to/ica_sources.fif \
  --output-dir /path/to/comparison
```

It writes `component_comparison.csv` and `comparison.json`, including both
models' canonical labels/probabilities and disagreement indices. The two
summary metrics are four-class component agreement and non-brain artifact-set
Jaccard. These measure model agreement, not accuracy, because the command does
not receive human ground-truth labels.
