# Retrained MEGNet ICA Label Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the retrained MEGNet ONNX classifier as an independent, fail-soft ICA artifact detector, migrate the original classifier key to `mne_icalabel`, and measure model agreement on SMN4Lang_single2.

**Architecture:** Refactor the existing standalone retrained-model script around an importable inference backend and call that backend lazily from `run_ica_label.py`. Normalize both MEGNet outputs to one four-class schema, merge ECG/EOG scores deterministically, preserve method-level provenance in JSON, and keep a separate model-comparison CLI.

**Tech Stack:** Python 3.10, MNE-Python, MNE-ICALabel 0.8.1, NumPy, ONNX Runtime 1.20.1, Nextflow DSL2, unittest/pytest, Docker.

## Global Constraints

- Replace `ica_label` with `mne_icalabel` everywhere; do not retain a compatibility alias.
- Boolean `megnet_retrained` defaults to `false` and is independent of `mne_icalabel`.
- For retrained inference, resample an in-memory ICA-source copy only when `sfreq > 250 Hz`; keep `sfreq <= 250 Hz` unchanged.
- Do not enforce a 1-100 Hz passband and never modify input FIF files.
- A retrained-model-only failure must be logged and recorded in JSON without failing `run_IC_label`.
- Shared raw/ICA load failures and final-output write failures remain fatal.
- Successful enabled detectors contribute to one sorted component union.
- Duplicate ECG/EOG component scores are merged with the maximum score.
- Preserve method-level labels and original class probabilities in `ecg_eog_scores.json`.
- Validation reports model agreement, not accuracy, and computes only four-class component agreement plus artifact-set Jaccard.
- Work in the current SSHFS-synchronized checkout as requested; do not create a separate worktree that would bypass the remote path.
- Do not create git commits unless the user requests them.

---

### Task 1: Build an Importable Retrained-MEGNet Backend

**Files:**
- Create: `megflow/tools/megnet_retrained/__init__.py`
- Create: `megflow/tools/megnet_retrained/inference.py`
- Modify: `megflow/tools/megnet_retrained/runtime/preprocessing.py`
- Modify: `megflow/tools/megnet_retrained/infer_ica_artifacts.py`
- Test: `tests/test_megnet_retrained.py`

**Interfaces:**
- Produces: `PredictionResult`, `predict_components(raw, ica, *, ica_sources_file: Path | None = None, model_file: Path | None = None, device: str = "cpu", batch_size: int = 8, max_flat_windows: int = 128, intra_op_threads: int | None = None, ch_type: str = "auto") -> PredictionResult`, `canonical_labels(probabilities)`, and `SourceBundle` sampling metadata.
- Consumes: existing clean-topomap and temporal-window preprocessing helpers.

- [ ] **Step 1: Write failing backend tests**

Add tests that assert the canonical class order, argmax labels, and asymmetric sampling policy using a fake source object whose `resample()` calls are observable:

```python
def test_sources_above_250_hz_are_resampled_in_memory():
    sources = FakeSources(500.0)
    original, effective = prepare_source_sampling(sources, 250.0)
    assert original == 500.0
    assert effective == 250.0
    assert sources.resample_calls == [250.0]

def test_sources_below_250_hz_are_not_resampled():
    sources = FakeSources(200.0)
    original, effective = prepare_source_sampling(sources, 250.0)
    assert (original, effective) == (200.0, 200.0)
    assert sources.resample_calls == []
```

- [ ] **Step 2: Run tests and confirm the new API is missing**

Run:

```bash
python -m pytest tests/test_megnet_retrained.py -q
```

Expected: collection/import failure for the not-yet-created backend API.

- [ ] **Step 3: Implement the backend**

Move session creation, batching, class constants, model hashing, and prediction orchestration into `inference.py`. Keep ONNX Runtime import inside inference/session functions. Return a structured result with canonical labels, `(n_components, 4)` probabilities, source sampling metadata, provider metadata, and model SHA-256.

Change source preparation to this policy:

```python
source_sfreq = float(raw_sources.info["sfreq"])
original_sfreq = source_sfreq
if source_sfreq > target_sfreq and not np.isclose(source_sfreq, target_sfreq):
    raw_sources.resample(float(target_sfreq), npad="auto", verbose="error")
    source_sfreq = float(raw_sources.info["sfreq"])
```

Accept the loaded raw object instead of reopening the raw path. Preserve identity checks for a supplied `ica_sources.fif`.

- [ ] **Step 4: Convert the standalone script to a thin adapter**

Keep its existing CSV/JSON/text outputs, but call `predict_components()` and remove the old `--sfreq-policy` choice. The CLI follows the fixed asymmetric policy and records original/effective sampling rates.

- [ ] **Step 5: Run backend tests and syntax checks**

Run:

```bash
python -m pytest tests/test_megnet_retrained.py -q
python -m py_compile megflow/tools/megnet_retrained/__init__.py megflow/tools/megnet_retrained/inference.py megflow/tools/megnet_retrained/infer_ica_artifacts.py megflow/tools/megnet_retrained/runtime/preprocessing.py
```

Expected: all tests pass and compilation exits zero.

### Task 2: Integrate Both MEGNet Methods into `run_ica_label.py`

**Files:**
- Modify: `megflow/run_ica_label.py`
- Test: `tests/test_run_ica_label_megnet.py`

**Interfaces:**
- Consumes: `predict_components()` from Task 1 and `mne_icalabel.megnet.megnet_label_components(raw, ica)`.
- Produces: merged `marked_components.txt` and enriched `ecg_eog_scores.json`.

- [ ] **Step 1: Write failing merge and failure-isolation tests**

Cover maximum-score replacement, deterministic index ordering, independent switches, lazy retrained import/call behavior, class mapping, and method-local failure:

```python
def test_duplicate_component_score_keeps_maximum():
    scores = defaultdict(list, {"eog": [], "eog_indices": []})
    append_component_score(scores, "eog", 3, 0.61)
    append_component_score(scores, "eog", 3, 0.84)
    assert scores["eog_indices"] == [3]
    assert scores["eog"] == [0.84]

def test_retrained_failure_is_recorded_without_raising():
    result = run_retrained_detector(
        mock.sentinel.raw,
        mock.sentinel.ica,
        ica_sources_file=None,
        predictor=Mock(side_effect=RuntimeError("bad model")),
    )
    assert result.artifact_indices == []
    assert result.detail["status"] == "failed"
    assert result.detail["error"]["type"] == "RuntimeError"
```

- [ ] **Step 2: Run tests and verify they fail against current behavior**

Run:

```bash
python -m pytest tests/test_run_ica_label_megnet.py -q
```

Expected: failures because the old key, first-score behavior, and retrained branch still exist.

- [ ] **Step 3: Implement normalized method results and max-score merging**

Read only `config["mne_icalabel"]` for original MEGNet. Use its full probability API and normalize native order `brain/other, eye movement, heart beat, eye blink` into the canonical order. Add method details with `status`, labels, complete probabilities, and metadata.

Add `--ica_sources_file` and invoke the retrained backend only inside the enabled branch. Catch `Exception` around only retrained preprocessing/model inference, log the traceback, store concise error metadata, and continue.

Write nested JSON with `json.dump()` while retaining the existing summary keys:

```json
{
  "ecg_indices": [1],
  "ecg": [0.91],
  "eog_indices": [3],
  "eog": [0.88],
  "methods": {
    "mne_icalabel": {"status": "succeeded", "labels": [], "probabilities": []},
    "megnet_retrained": {"status": "failed", "error": {"type": "RuntimeError", "message": "bad model"}}
  }
}
```

- [ ] **Step 4: Run production-integration tests**

Run:

```bash
python -m pytest tests/test_run_ica_label_megnet.py tests/test_megnet_retrained.py -q
```

Expected: all tests pass.

### Task 3: Add the Standalone Model-Agreement Utility

**Files:**
- Create: `megflow/tools/megnet_retrained/compare_with_mne_megnet.py`
- Test: `tests/test_megnet_retrained_comparison.py`

**Interfaces:**
- Consumes: canonical retrained predictions and the original full-probability MNE MEGNet API.
- Produces: `component_comparison.csv` and `comparison.json`.

- [ ] **Step 1: Write failing metric and class-reordering tests**

```python
def test_agreement_and_artifact_jaccard():
    original = ["brain_or_other", "heart_beat", "eye_blink", "brain_or_other"]
    retrained = ["brain_or_other", "eye_movement", "eye_blink", "brain_or_other"]
    metrics = comparison_metrics(original, retrained)
    assert metrics["component_agreement"] == 0.75
    assert metrics["artifact_jaccard"] == 1.0

def test_empty_artifact_sets_have_unit_jaccard():
    metrics = comparison_metrics(["brain_or_other"], ["brain_or_other"])
    assert metrics["artifact_jaccard"] == 1.0
```

- [ ] **Step 2: Run tests and confirm the comparison module is absent**

Run:

```bash
python -m pytest tests/test_megnet_retrained_comparison.py -q
```

Expected: import failure.

- [ ] **Step 3: Implement comparison and outputs**

Load each input once, run both models on the same raw/ICA pair, reorder the original probability columns into canonical order, compute exact agreement/Jaccard definitions, and write per-component labels/probabilities plus disagreement flags. Include paths, sampling metadata, model hashes/versions, counts, and the disagreement index list in JSON.

- [ ] **Step 4: Run comparison tests and CLI help smoke test**

Run:

```bash
python -m pytest tests/test_megnet_retrained_comparison.py -q
python megflow/tools/megnet_retrained/compare_with_mne_megnet.py --help
```

Expected: tests pass and CLI usage exits zero.

### Task 4: Wire Nextflow Caching and Migrate Configuration

**Files:**
- Modify: `nextflow/megflow.nf`
- Modify: `nextflow/nextflow.config`
- Modify: `nextflow/nextflow_corpus.config`
- Modify: `nextflow/nextflow_multi_dataset_demo.config`
- Modify: any additional repository-owned config/example found by the migration scan
- Test: `tests/test_nextflow_profile_integration.py`
- Test: `tests/test_megnet_retrained_nextflow_contract.py`

**Interfaces:**
- Consumes: the new `--ica_sources_file` CLI argument.
- Produces: source/Docker config parity and a process hash covering backend code plus `model.onnx`.

- [ ] **Step 1: Write failing textual contract tests**

Assert that all default config profiles contain `mne_icalabel: true` and `megnet_retrained: false`, the old boolean line is absent, `run_ic_label` passes `${ica_source}`, and its `filesSha256` list includes backend, preprocessing, and model paths.

- [ ] **Step 2: Run contract tests and confirm current failures**

Run:

```bash
python -m pytest tests/test_megnet_retrained_nextflow_contract.py -q
```

Expected: assertions fail on the old key and missing Nextflow wiring.

- [ ] **Step 3: Migrate configs and update the process script**

Use this block in every full default config:

```groovy
mne_icalabel: true,
megnet_retrained: false,
```

Pass `--ica_sources_file "${ica_source}"`. Extend only the `run_ic_label` command hash with `run_ica_label.py`, retrained package Python files, runtime preprocessing, and `model.onnx`, so model changes invalidate ICA labeling without needlessly changing unrelated process scripts.

- [ ] **Step 4: Run contract and Nextflow integration tests**

Run:

```bash
python -m pytest tests/test_megnet_retrained_nextflow_contract.py -q
python -m pytest tests/test_nextflow_profile_integration.py -q
```

Expected: all tests pass.

### Task 5: Update User Documentation and Tool Metadata

**Files:**
- Modify: `docs/source/reference/configuration_preprocessing.rst`
- Modify: `docs/source/details/pipeline_details.rst`
- Modify: `megflow/tools/megnet_retrained/README.md`
- Modify: `megflow/tools/megnet_retrained/requirements.txt`
- Modify: other user-facing examples returned by the old-key scan

**Interfaces:**
- Documents the exact runtime/config/output behavior implemented in Tasks 1-4.

- [ ] **Step 1: Update configuration and pipeline documentation**

Document the direct `mne_icalabel` rename, independent disabled retrained switch, simultaneous union behavior, asymmetric in-memory sampling behavior, fail-soft status, JSON method details, and comparison command. Do not show or recommend the removed key.

- [ ] **Step 2: Align the tool README and dependency pin**

Replace the obsolete strict `--sfreq-policy` guidance with the fixed runtime policy. Align the standalone requirements with the repository's ONNX Runtime 1.20.1 pin.

- [ ] **Step 3: Build docs and scan for stale configuration**

Run:

```bash
python -m sphinx -W -b html docs/source docs/_build/html
rg -n "^[[:space:]]*ica_label:[[:space:]]" nextflow docs scripts examples tests megflow
```

Expected: Sphinx exits zero; the migration scan returns no old boolean configuration key.

### Task 6: End-to-End Remote and Docker Verification

**Files:**
- Generated outside source tree: remote comparison output directory under `/data/liaopan/datasets/SMN4Lang_single2`
- No committed source outputs.

**Interfaces:**
- Validates all prior tasks in the actual Conda and Docker environments.

- [ ] **Step 1: Run focused and full relevant tests remotely**

Run with `/home/liaopan/anaconda3/envs/megprep/bin/python`:

```bash
python -m pytest tests/test_megnet_retrained.py tests/test_run_ica_label_megnet.py tests/test_megnet_retrained_comparison.py tests/test_megnet_retrained_nextflow_contract.py -q
python -m pytest tests/test_nextflow_profile_integration.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Compare models on SMN4Lang_single2**

Run the comparison utility against a matching preprocessed raw, ICA, and `ica_sources.fif` from SMN4Lang_single2. Confirm both output files exist and parse `comparison.json` to report component count, agreement, artifact-set sizes, Jaccard, and disagreement count.

- [ ] **Step 3: Exercise retrained production integration**

Run `run_ica_label.py` into a temporary output root with both classifiers enabled and non-destructive references to the same SMN4Lang inputs. Confirm `marked_components.txt` and `ecg_eog_scores.json` include both successful method records. Rely on the focused `run_retrained_detector(raw, ica, ica_sources_file=None, predictor=Mock(side_effect=RuntimeError("bad model")))` unit test for the failure branch so the remote model weight is never modified.

- [ ] **Step 4: Build and smoke-test Docker**

Build `cmrlab/megflow:1.0.0` from `megflow.Dockerfile` using cache. In the image, verify ONNX Runtime imports, the model file exists, both CLIs show help, and focused unit tests or equivalent direct imports pass.

- [ ] **Step 5: Final verification and diff audit**

Run:

```bash
git diff --check
git status --short
```

Review every changed file, confirm no generated comparison artifacts entered the repository, and summarize any residual model disagreement as an empirical result rather than a defect.
