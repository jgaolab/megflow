# Resume Lineage and Failure Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make resume behavior detect missing published process outputs without overwriting intentional artifact/ICA sidecar edits, and prove that lenient processing failures still schedule uncached dataset and corpus reports.

**Architecture:** Add focused two-recording Nextflow stub regressions before changing the workflow. Treat generated outputs and user-editable sidecars differently: deleting a required generated output reruns its owner and descendants, while editing a bad-segment or ICA-label sidecar preserves the edit and invalidates only consumers. Keep report processes as ordinary `cache false` Nextflow processes released by a channel-closing barrier.

**Tech Stack:** Python `unittest`, Nextflow 24.10.3 DSL2, repository stub processes, Sphinx/reStructuredText.

## Global Constraints

- Do not migrate or rewrite scientific algorithms while fixing task lineage.
- Do not regenerate intentionally edited bad-channel, bad-segment, or ICA-label sidecars.
- Keep unaffected datasets and recordings cached.
- Reports remain normal Nextflow processes and never use resume cache.
- Strict mode may terminate immediately; lenient mode must close channels and submit reports.

---

### Task 1: Prove Published-Output Resume Semantics

**Files:**
- Modify: `tests/test_nextflow_profile_integration.py`

- [x] Add a two-recording baseline and unchanged-resume assertion.
- [x] Edit one recording's bad-segment sidecar and assert its generator remains cached while ICA and descendants rerun.
- [x] Delete one recording's generated epoch output and assert `epochs` plus dependent processes rerun while the other recording stays cached.
- [x] Run the focused test and preserve the failing trace as root-cause evidence.

### Task 2: Repair External-Output Validation

**Files:**
- Modify: `nextflow/megflow.nf`
- Modify: `tests/test_nextflow_execution_config.py` if a static contract is needed.

- [x] Add the smallest reusable output-validity mechanism that works on baseline and `-resume` without forcing an unchanged second run.
- [x] Apply it first to the failing owner process, then extend it consistently to required generated outputs.
- [x] Keep content hashes on editable sidecars as downstream lineage inputs only.
- [x] Run focused resume tests.

### Task 3: Prove Lenient Failure-to-Report Closure

**Files:**
- Modify: `tests/test_nextflow_profile_integration.py`
- Modify: `nextflow/megflow.nf` only if the regression fails.

- [x] Let the integration config select strict or lenient behavior and inject deterministic stub failures.
- [x] Test failed recordings beside one successful recording.
- [x] Test all recordings failing or being excluded before the terminal stage.
- [x] Assert dataset and corpus report processes complete without deadlock and remain uncached.

### Task 4: Align the Validation Contract

**Files:**
- Modify: `docs/source/reference/validation.rst`

- [x] Clarify generated-output deletion versus user-editable sidecar mutation.
- [x] Document strict termination separately from lenient report completion.
- [x] Build the docs with warnings as errors.

### Task 5: Full Verification

- [x] Run `tests.test_nextflow_execution_config`.
- [x] Run `tests.test_nextflow_profile_integration` with Nextflow 24.10.3.
- [x] Run relevant Python/unit tests for report and lineage helpers.
- [x] Run scoped `git diff --check` and review only intended changes.
