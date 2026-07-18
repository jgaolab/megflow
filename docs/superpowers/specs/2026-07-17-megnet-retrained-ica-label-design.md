# Retrained MEGNet ICA Label Integration Design

Status: Draft for user review

Date: 2026-07-17

## Context

MEGFlow currently supports the original MNE-ICALabel MEGNet classifier in
`megflow/run_ica_label.py`. A retrained MEGNet ONNX model now lives under
`megflow/tools/megnet_retrained` and must become an independent, optional ICA
artifact detector.

The two MEGNet implementations must be independently configurable, may run in
the same task, and contribute their artifact components to the same final
union. The retrained detector is supplementary: a failure confined to that
detector must not discard results from the other enabled algorithms.

## Goals

- Add the retrained ONNX model as an importable backend used directly by
  `run_ica_label.py`.
- Rename the existing `ica_label` configuration key to `mne_icalabel` across
  all repository-owned configuration, examples, tests, and documentation.
- Add the Boolean `megnet_retrained` switch, defaulting to `false`.
- Allow the original and retrained MEGNet classifiers to run together.
- Merge retrained ECG/EOG classifications into `marked_components.txt` and
  `ecg_eog_scores.json` without duplicating component indices.
- Preserve method-level labels and probabilities for auditing.
- Add a standalone model-agreement tool and run it on SMN4Lang_single2.
- Preserve Nextflow caching correctness and Docker/source-run parity.

## Non-goals

- No compatibility alias or fallback for the old `ica_label` key.
- No hard rejection based on sampling rate or filter passband.
- No modification of the input raw FIF or ICA FIF files.
- No claim of classification accuracy without human ground-truth labels.
- No coupling of production inference to the model-comparison utility.

## Configuration Contract

The ICA-label configuration will expose two independent switches:

```groovy
ic_label = [
    mne_icalabel: true,
    megnet_retrained: false,
    // Existing MNE, rules, and category settings remain here.
]
```

All repository occurrences of the old `ica_label` key will be replaced with
`mne_icalabel`. Runtime code will read only `mne_icalabel`; it will not inspect
or translate the old key. A repository-wide test/search will guard against
accidentally retaining the old configuration spelling.

The retrained model's operational values, such as model path, class order,
target sampling rate, and safe batch defaults, remain implementation defaults
rather than public configuration until a real user-facing need appears.

## Architecture

### Importable retrained backend

The reusable preprocessing and ONNX inference logic will be exposed through a
package-level Python API under `megflow/tools/megnet_retrained`. The existing
standalone inference script will become a thin CLI adapter over that API, so
production and command-line inference use one implementation.

The API will accept the already loaded raw and ICA objects plus an optional
precomputed `ica_sources.fif`. It will return structured component predictions
instead of requiring `run_ica_label.py` to parse files emitted by a subprocess.
The result includes:

- canonical class labels for every component;
- four-class probabilities for every component;
- original and effective sampling rates;
- model identity, including a model file hash;
- component names/order used for inference.

When an existing ICA source file is supplied, the backend will validate its
component count, component order, and source identity before reuse. Otherwise,
it will compute sources from the loaded raw and ICA objects.

### Sampling behavior

Inference operates on an in-memory copy:

- `sfreq > 250 Hz`: resample the copy to 250 Hz;
- `sfreq == 250 Hz`: use the copy unchanged;
- `sfreq < 250 Hz`: keep the original sampling rate.

No sampling operation writes back to the input FIF. The 1-100 Hz training
condition is recorded/documented as model context only; it is not enforced as
an input restriction.

### Canonical classes

Both implementations are normalized to this order before merging or
comparison:

1. `brain_or_other`
2. `heart_beat`
3. `eye_blink`
4. `eye_movement`

This normalization is required because MNE-ICALabel's original MEGNet and the
retrained ONNX model expose different native class orders.

## Production Data Flow

For each raw/ICA pair, `run_ica_label.py` will:

1. Load and validate the shared raw and ICA inputs.
2. Run the existing MNE and rules-based detectors according to their switches.
3. Run original MEGNet when `mne_icalabel` is true.
4. Run retrained MEGNet when `megnet_retrained` is true.
5. Normalize successful model outputs to canonical classes.
6. Merge enabled detectors into the final component union.
7. Write `marked_components.txt` and the enriched
   `ecg_eog_scores.json` atomically.

Artifact mapping is:

- `heart_beat` -> ECG;
- `eye_blink` and `eye_movement` -> EOG;
- `brain_or_other` -> not excluded by that classifier.

## Merge Semantics

The existing summary fields in `ecg_eog_scores.json` remain available:

```json
{
  "ecg_indices": [],
  "ecg": [],
  "eog_indices": [],
  "eog": []
}
```

For each artifact type, component indices are unique and deterministically
sorted. If several methods assign the same component to the same artifact
type, the summary score is the maximum corresponding probability reported by
those methods.

The JSON will also gain method-level details. A successful method records its
labels, complete four-class probability vectors, sampling metadata, and model
metadata. A failed retrained method records a status and concise error details.
This preserves provenance while keeping existing report consumers on the
summary fields.

`marked_components.txt` contains the sorted union of all components selected
by successful enabled methods. A retrained-method failure contributes no
components but does not remove components selected by other methods.

## Failure Isolation

Retrained MEGNet has a method-local failure boundary around its preprocessing,
model loading, and inference:

- log a visible warning with exception type and concise message;
- record `status: failed` and the error in its JSON method detail;
- merge no retrained predictions for that item;
- continue the remaining detectors and write their outputs;
- do not fail or retry the Nextflow `run_IC_label` task solely for this error.

Failures in shared prerequisites remain fatal. Examples include an unreadable
raw file, an unreadable ICA file, or an inability to write the final outputs,
because no reliable task result can be produced in those cases.

This distinction prevents an optional supplementary model from blocking the
pipeline while still making its failure visible and auditable.

## Nextflow and Packaging

The `run_IC_label` process will pass its existing `ica_sources.fif` path to the
Python entry point for validated reuse. Its cache fingerprint will include the
retrained backend, preprocessing code, and ONNX model so code or weight changes
invalidate only the affected tasks.

The source environment and Docker image will include a compatible ONNX Runtime
dependency and package the model weight. The disabled default must not import
ONNX Runtime or load the model. Source and Docker configurations will expose
identical switches and defaults.

## Standalone Agreement Tool

A separate comparison command will accept one raw FIF, ICA FIF, optional ICA
sources FIF, and output directory. It will run the original and retrained
MEGNet implementations on the same inputs, normalize class orders, and emit:

- a component-level CSV with both labels and both probability vectors;
- a JSON summary with metric values and model metadata;
- an explicit list of components whose four-class labels disagree.

The metrics are:

```text
component agreement = matching four-class labels / component count

artifact Jaccard = |original artifact set intersect retrained artifact set|
                   / |original artifact set union retrained artifact set|
```

The artifact set contains all non-`brain_or_other` components. If both artifact
sets are empty, Jaccard is defined as `1.0`.

The result is described as model agreement, not accuracy. The first real-data
validation target is a representative SMN4Lang_single2 recording with its
matching raw, ICA, and ICA-sources files.

## Testing Strategy

Implementation will follow test-first changes covering:

- direct migration to `mne_icalabel` and absence of the old key;
- independent enable/disable behavior for both MEGNet methods;
- no ONNX import/model load while retrained inference is disabled;
- sampling behavior above, at, and below 250 Hz;
- class-order normalization;
- ECG/EOG mapping, deterministic union, and maximum-score merging;
- retrained-method soft failure with successful output from other methods;
- method-level success/failure JSON details;
- model comparison agreement and Jaccard edge cases;
- Nextflow ICA-source wiring and cache fingerprint inputs;
- source/Docker configuration parity.

After unit and integration tests, the standalone comparison will run in the
remote `megprep` Conda environment on SMN4Lang_single2. The delivered result
will report the measured component agreement, artifact Jaccard, component
counts, and disagreement count.

## Documentation Updates

Documentation will explain:

- the `mne_icalabel` rename and lack of an old-key alias;
- the independent Boolean `megnet_retrained` switch and disabled default;
- simultaneous model use and union semantics;
- in-memory asymmetric resampling behavior;
- method-local failure behavior;
- output JSON provenance fields;
- how to run and interpret the standalone agreement utility.

## Acceptance Criteria

- No repository-owned configuration or documentation uses the old
  `ica_label` key for the original MEGNet switch.
- Existing behavior is unchanged when `megnet_retrained` is false,
  apart from the intentional key rename.
- Enabling both models merges both outputs deterministically.
- A retrained-model-only failure is visible but does not fail `run_IC_label`.
- Input FIF files remain unchanged during inference.
- Source and Docker tests pass with matching configuration behavior.
- SMN4Lang_single2 comparison artifacts and the two requested metrics are
  produced successfully.
