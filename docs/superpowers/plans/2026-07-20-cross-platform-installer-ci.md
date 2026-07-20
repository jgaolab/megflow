# Cross-Platform Installer CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task by task.

**Goal:** Add non-duplicated native Linux, macOS, and Windows installer validation while preserving complete local validation.

**Architecture:** Split installer contracts into platform-specific unittest classes. Assign each class to a native GitHub-hosted runner, retain the Windows PowerShell parser check, and remove the complete installer module only from the CI routing aggregate.

**Tech Stack:** GitHub Actions YAML, Python 3.11, `unittest`, Bash, PowerShell AST validation.

---

## Constraints

- Do not change installer behavior or documentation.
- Do not perform real package installation, Docker image pulls, or Docker Desktop execution.
- Keep `windows-installer` and its native PowerShell parser validation.
- Keep the complete `test_install_scripts` module in the full local validation route.
- Do not run the complete installer module again from `nextflow-routing` CI.

### Task 1: Add a failing workflow contract

**Files:**
- Modify: `tests/test_nextflow_execution_config.py`

**Step 1: Add a helper that extracts one workflow job body**

Use a multiline regular expression anchored at two-space YAML job indentation so assertions remain scoped to a single job.

**Step 2: Add `test_installer_validation_jobs_are_native_and_nonduplicated`**

Assert that:

- `linux-installer` uses `ubuntu-latest` and runs metadata plus Linux installer classes.
- `macos-installer` uses `macos-latest` and runs the macOS installer class.
- `windows-installer` uses `windows-latest`, preserves `validate_windows_installer.py`, and runs the Windows installer class.
- `routing-ci` no longer lists the complete `test_install_scripts` module.
- the full local `routing` group still lists the complete module.

**Step 3: Run the focused contract and confirm RED**

Run:

```bash
python3 -m unittest tests.test_nextflow_execution_config.NextflowExecutionConfigTests.test_installer_validation_jobs_are_native_and_nonduplicated
```

Expected: FAIL because Linux and macOS installer jobs do not yet exist.

### Task 2: Partition installer contracts by platform

**Files:**
- Modify: `tests/test_install_scripts.py`

**Step 1: Extract a test helper base**

Rename the existing class to `_InstallerContractTestCase` and leave only `_write_stub` and `_run_with_stubs` on it.

**Step 2: Create explicit contract classes**

- `InstallerMetadataContractTests`: release/documentation assertions.
- `LinuxInstallerContractTests`: Bash parsing for Linux/DEV installers and Linux runtime behavior.
- `MacOSInstallerContractTests`: Bash parsing and behavior for the macOS installer.
- `WindowsInstallerContractTests`: Windows installer static Docker exit-code contract.

**Step 3: Run all partitioned installer contracts**

Run:

```bash
python3 scripts/validation/run_unittest_gate.py test_install_scripts
```

Expected: PASS with no skipped or empty tests.

### Task 3: Add native CI jobs and remove aggregate duplication

**Files:**
- Modify: `.github/workflows/validation.yml`
- Modify: `scripts/validation/run_validation.sh`

**Step 1: Add Linux installer validation**

Create `linux-installer` on `ubuntu-latest`, set up Python 3.11, and run:

```bash
python scripts/validation/run_unittest_gate.py test_install_scripts.InstallerMetadataContractTests test_install_scripts.LinuxInstallerContractTests
```

**Step 2: Add macOS installer validation**

Create `macos-installer` on `macos-latest`, set up Python 3.11, and run only `test_install_scripts.MacOSInstallerContractTests`.

**Step 3: Extend Windows installer validation**

Keep the native parser step and add `test_install_scripts.WindowsInstallerContractTests`.

**Step 4: Remove only the duplicate CI aggregate entry**

Delete `test_install_scripts` from `run_routing_ci()` and leave `run_routing()` unchanged.

**Step 5: Run the focused workflow contract and confirm GREEN**

Run the Task 1 command again. Expected: PASS.

### Task 4: Verify the complete change

**Files:**
- Test: `tests/test_install_scripts.py`
- Test: `tests/test_nextflow_execution_config.py`
- Test: `tests/test_validation_runner.py`

**Step 1: Run related validation suites**

```bash
python3 scripts/validation/run_unittest_gate.py test_install_scripts test_nextflow_execution_config test_validation_runner
```

**Step 2: Check YAML and shell syntax**

```bash
python3 -c 'from pathlib import Path; import yaml; data=yaml.safe_load(Path(".github/workflows/validation.yml").read_text()); assert {"linux-installer", "macos-installer", "windows-installer"} <= set(data["jobs"])'
bash -n scripts/validation/run_validation.sh
bash -n install/install_megprep_linux.sh install/install_megprep_macos.sh install/install_megprep_DEV.sh
```

**Step 3: Run the Linux class in the project environment**

```bash
ssh liaopan@100.114.213.66 conda run -n megprep python /data/liaopan/megprep/scripts/validation/run_unittest_gate.py test_install_scripts.LinuxInstallerContractTests
```

**Step 4: Inspect the scoped diff**

```bash
git diff --check -- .github/workflows/validation.yml scripts/validation/run_validation.sh tests/test_install_scripts.py tests/test_nextflow_execution_config.py
git diff -- .github/workflows/validation.yml scripts/validation/run_validation.sh tests/test_install_scripts.py tests/test_nextflow_execution_config.py
```
