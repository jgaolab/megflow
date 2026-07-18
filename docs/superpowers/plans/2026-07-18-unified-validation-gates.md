# Unified Validation Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the same non-vacuous routing and scientific validation runnable automatically in GitHub Actions and locally with one command.

**Architecture:** Keep orchestration and scientific contracts as separate gates behind one shell runner. Nextflow tests use isolated launch directories and real trace/output assertions; scientific tests run synthetic MNE/OSL operations in a lightweight validation environment. GitHub and local users invoke the same runner so the two paths cannot drift.

**Tech Stack:** Bash, Python `unittest`, Nextflow 24.10.3, GitHub Actions, MNE-Python 1.8, vendored OSL-ephys.

## Global Constraints

- A missing Nextflow or scientific dependency must fail its requested gate, never silently skip it.
- Routing tests may use `-stub-run`, but must execute real Nextflow and assert trace statuses and filesystem effects.
- Scientific tests must execute real synthetic MNE/OSL computations and include explicit negative cases.
- The 32.8 GB production Docker image is not pulled for every GitHub validation run.
- Existing user data and unrelated worktree changes must not be modified.

---

### Task 1: Test Isolation Regressions

**Files:**
- Modify: `tests/test_deepreject_input.py`
- Modify: `tests/test_nextflow_profile_integration.py`
- Modify: `tests/test_nextflow_execution_config.py`

- [ ] Add static contracts requiring each Nextflow integration run to launch from its own output directory and requiring validation entrypoints to exist.
- [ ] Reproduce the full-suite OSL import pollution and shared Nextflow session failures.
- [ ] Scope fake OSL modules to the DeepReject import only.
- [ ] Launch Nextflow with `cwd=output_dir` so `.nextflow/cache` and history are test-local.
- [ ] Run the affected tests in full-suite order and verify the failures disappear.

### Task 2: Shared One-Command Runner

**Files:**
- Create: `scripts/validation/run_validation.sh`
- Create: `requirements_validation.txt`
- Modify: `tests/test_nextflow_execution_config.py`

- [ ] Add runner contract tests for `routing`, `scientific`, and `all` modes.
- [ ] Make `routing` preflight Nextflow, run static/routing/report-layout suites, and parse every shipped config.
- [ ] Make `scientific` preflight required imports and run the explicit non-Nextflow scientific suite.
- [ ] Make `all` execute both gates and optionally build docs when Sphinx is installed.
- [ ] Reject unknown modes and fail on unexpected unittest skips.

### Task 3: GitHub Actions Wiring

**Files:**
- Modify: `.github/workflows/validation.yml`
- Modify: `tests/test_nextflow_execution_config.py`

- [ ] Add a failing static test requiring all-branch push and pull-request triggers.
- [ ] Make the routing job invoke the shared runner with Nextflow 24.10.3.
- [ ] Add a scientific job that installs `requirements_validation.txt`, installs vendored OSL-ephys without replacing source files, and invokes the shared runner.
- [ ] Keep strict documentation build as a separate job.

### Task 4: Documentation and Final Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/source/reference/validation.rst`

- [ ] Document `bash scripts/validation/run_validation.sh all` and the distinction between stub routing and real scientific tests.
- [ ] Run deliberate invalid-step, injected-failure, QC-exclusion, deleted-output, and mutated-sidecar cases.
- [ ] Run the complete test discovery in the remote `megprep` environment with zero failures, errors, or unexpected skips.
- [ ] Validate the lightweight dependency set in a clean environment.
- [ ] Run Sphinx with warnings as errors and scoped `git diff --check`.
