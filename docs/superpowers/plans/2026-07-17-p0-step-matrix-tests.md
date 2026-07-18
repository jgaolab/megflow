# P0 Step Matrix Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic Nextflow stage integration test with an explicit P0 matrix that proves exact process routing, step normalization, modifiers, scope restrictions, and output boundaries.

**Architecture:** Keep the expensive valid-mode coverage in one corpus `-stub-run`, but express every dataset as a declarative case with an exact expected process set and output contract. Separate anatomy-method routing, normalized aliases/modifiers, and fail-fast invalid configurations into focused tests so failures identify the broken contract directly.

**Tech Stack:** Python `unittest`, Nextflow 24.10.3 DSL2, repository stub processes, Sphinx/reStructuredText.

## Global Constraints

- Do not change scientific processing behavior while reorganizing the tests.
- Assert both required and forbidden scheduling through exact trace process sets.
- Keep report processes uncached and include their routing in every applicable step case.
- Keep CI memory directives at `512 MB` for all stub processes.
- Preserve dataset and recording isolation in corpus mode.

---

### Task 1: Declarative MEG Step Matrix

**Files:**
- Modify: `tests/test_nextflow_profile_integration.py`

**Interfaces:**
- Consumes: `write_config()`, `dataset_block()`, `create_dataset()`, and Nextflow `trace.txt` rows.
- Produces: `trace_processes_for_dataset(output_dir, dataset_name) -> set[str]` and a canonical `MEG_STEP_CASES` contract.

- [x] **Step 1: Add trace helpers and the expected process constants**

```python
def trace_processes_for_dataset(self, output_dir, dataset_name):
    prefix = f"{dataset_name}:"
    exact = f"{dataset_name})"
    return {
        row["name"].split(" (", 1)[0]
        for row in self.trace_rows(output_dir)
        if " (" in row["name"]
        and (row["name"].split(" (", 1)[1].startswith(prefix)
             or row["name"].endswith(exact))
    }
```

- [x] **Step 2: Replace the imperative stage assertions with matrix subtests**

The matrix must cover `report`, `meg_artifacts`, `meg_ica`, `meg_epochs`, `meg_epochs,skip_ica`, `meg_all`, and `all`. Each case compares the observed process set to the complete expected set and then checks its terminal artifact.

- [x] **Step 3: Run the MEG matrix and verify it passes**

Run:

```bash
MEGFLOW_NEXTFLOW=/tmp/megflow-validation-runtime/bin/nextflow \
  python -m unittest \
  tests.test_nextflow_profile_integration.NextflowProfileIntegrationTests.test_meg_step_matrix_schedules_exact_process_boundaries -v
```

Expected: every named subtest passes and no unexpected process appears.

### Task 2: Anatomy, Modifiers, and Scope Matrix

**Files:**
- Modify: `tests/test_nextflow_profile_integration.py`

**Interfaces:**
- Consumes: the trace helper from Task 1 and `parseMegPipelineSteps()` behavior in `nextflow/megflow.nf`.
- Produces: focused tests for anatomy methods, normalized aliases, legal `with_anatomy`, and fail-fast invalid combinations.

- [x] **Step 1: Add the exact anatomy-method matrix**

Cover BIDS FreeSurfer, DeepPrep, pseudo-MRI, non-BIDS NIfTI, and DICOM. Exact process sets must prove that unused reconstruction methods are absent.

- [x] **Step 2: Add normalized alias and modifier cases**

Cover `meg`, `artifacts`, `ica`, and `epochs` with mixed case/whitespace, plus `meg_artifacts,with_anatomy`, `meg_ica,with_anatomy`, and `meg_epochs,with_anatomy`.

- [x] **Step 3: Add fail-fast invalid cases**

Cover an empty step string, unknown primary, unknown modifier, `meg_ica,skip_ica`, and `meg_all,with_anatomy`. Retain and strengthen the recording-level stage-upgrade test.

- [x] **Step 4: Run the focused integration class**

```bash
MEGFLOW_NEXTFLOW=/tmp/megflow-validation-runtime/bin/nextflow \
  python -m unittest tests.test_nextflow_profile_integration -v
```

Expected: all profile integration tests pass with exact stage routing.

### Task 3: Publish the Revised P0 Test Contract

**Files:**
- Modify: `docs/source/reference/validation.rst`

**Interfaces:**
- Consumes: test names and matrices from Tasks 1-2.
- Produces: a P0 test catalog that distinguishes automated coverage from required real-data canaries.

- [x] **Step 1: Replace the broad stage-selection row with explicit P0 contracts**

Document exact scheduling, aliases/modifiers, dataset/recording scope rules, output deletion/mutation resume checks, failure-to-report barriers, QC threshold boundaries, and anatomy method isolation.

- [x] **Step 2: Build documentation with warnings as errors**

```bash
python -m sphinx -W --keep-going -b html docs/source /tmp/megflow-docs-step-matrix
```

Expected: exit status 0 and no Sphinx warnings.

### Task 4: Full Verification

**Files:**
- Verify: `tests/test_nextflow_execution_config.py`
- Verify: `tests/test_nextflow_profile_integration.py`
- Verify: `docs/source/reference/validation.rst`

**Interfaces:**
- Consumes: all changes from Tasks 1-3.
- Produces: fresh evidence that static contracts, runtime routing, formatting, and documentation agree.

- [x] **Step 1: Run static Nextflow configuration tests**

```bash
python -m unittest tests.test_nextflow_execution_config -v
```

- [x] **Step 2: Run the full Nextflow profile integration suite**

```bash
MEGFLOW_NEXTFLOW=/tmp/megflow-validation-runtime/bin/nextflow \
  python -m unittest tests.test_nextflow_profile_integration -v
```

- [x] **Step 3: Check the patch**

```bash
git diff --check
git diff -- tests/test_nextflow_profile_integration.py docs/source/reference/validation.rst
```

Expected: all commands exit 0; the diff contains only the matrix refactor, added P0 cases, and matching documentation.
