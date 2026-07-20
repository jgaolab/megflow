# Cross-Platform Installer CI Design

## Goal

Validate the shipped Linux, macOS, and Windows installers on their native
GitHub-hosted operating systems without performing privileged package
installation, starting Docker Desktop, or downloading the MEGFlow image.

The CI results must expose one clearly named installer job per platform and
must not repeat the same installer contract in the general routing job.

## Current State

`nextflow-routing` runs the complete `test_install_scripts` module on Ubuntu.
Those tests use command stubs and a fake `uname` result to exercise both Linux
and macOS branches. This gives useful logic coverage but does not execute the
macOS installer under a native macOS Bash environment.

`windows-installer` is separate because it uses the native PowerShell parser to
validate the `.ps1` installer. That parser coverage is unique and must remain.

Running the complete installer test module again on both Ubuntu and macOS would
duplicate Linux, macOS, Windows, and metadata assertions. The design therefore
partitions contracts by platform before adding jobs.

## Test Partition

Refactor `tests/test_install_scripts.py` into a non-discovered helper base plus
four focused `unittest.TestCase` classes:

1. `InstallerMetadataContractTests`
   - verifies installer documentation uses current release examples;
   - runs only in the Linux installer job and in the complete local routing
     suite.
2. `LinuxInstallerContractTests`
   - parses the Linux distribution and Linux development installers with the
     native Bash available on the Ubuntu runner;
   - verifies default, tag-only, explicit Docker, explicit Apptainer, fallback,
     and invalid-runtime behavior with command stubs.
3. `MacOSInstallerContractTests`
   - parses the macOS installer with the native Bash available on the macOS
     runner;
   - verifies default-tag and explicit-tag Docker behavior with command stubs.
4. `WindowsInstallerContractTests`
   - verifies the PowerShell installer checks native Docker exit codes and uses
     the expected pull and help-run commands;
   - complements, but does not replace, native PowerShell AST parsing.

The helper base provides `_write_stub` and `_run_with_stubs` but contains no
`test_*` methods, so `unittest` does not create an extra suite.

## GitHub Actions Jobs

Add three explicit jobs to `.github/workflows/validation.yml`:

### `linux-installer`

- runner: `ubuntu-latest`;
- Python: 3.11 via `actions/setup-python@v6`;
- command: run `InstallerMetadataContractTests` and
  `LinuxInstallerContractTests` through `run_unittest_gate.py`;
- timeout: 10 minutes.

### `macos-installer`

- runner: `macos-latest`;
- Python: 3.11 via `actions/setup-python@v6`;
- command: run `MacOSInstallerContractTests` through
  `run_unittest_gate.py`;
- timeout: 10 minutes.

### `windows-installer`

- keep the current `windows-latest` runner and native PowerShell parser step;
- add a second step that runs `WindowsInstallerContractTests` through
  `run_unittest_gate.py`;
- keep the 10-minute timeout.

The jobs do not invoke the installers against real package managers or
container runtimes. Linux and macOS runtime commands remain stubbed; Windows
uses native parsing plus static Docker-call contracts.

## Removing CI Duplication

Remove the complete `test_install_scripts` module from `run_routing_ci()` in
`scripts/validation/run_validation.sh`, because the three platform jobs own
those PR/push contracts.

Keep `test_install_scripts` in `run_routing()` so a developer can still run all
installer contracts locally as part of the complete routing validation.

No installer contract is removed: it is either assigned to a native platform
job or retained in the local all-contract suite.

## Failure Semantics

All platform jobs use `run_unittest_gate.py`, which fails when a suite is empty,
skipped, or unsuccessful. The three jobs run independently, so one platform
failure does not prevent GitHub Actions from reporting the other platform
results.

No package-manager, Docker daemon, image registry, or GUI availability is
required. This keeps failures attributable to installer syntax and control
flow rather than external infrastructure.

## Repository Contracts

Update `tests/test_nextflow_execution_config.py` to require:

- `linux-installer` on `ubuntu-latest`;
- `macos-installer` on `macos-latest`;
- `windows-installer` on `windows-latest`;
- the exact platform-specific test class in each job;
- native Windows parser validation remains present;
- `test_install_scripts` is absent from `run_routing_ci()` and present in
  `run_routing()`.

Update `tests/test_validation_runner.py` only if class partitioning changes a
validator interface; the existing non-skipping gate tests remain authoritative.

## Verification

Verification will include:

1. a red test proving the current workflow lacks native Linux/macOS installer
   jobs and still duplicates the installer module in `routing-ci`;
2. all partitioned installer suites locally;
3. workflow and validation-runner contract modules;
4. YAML parsing when an available parser is present, plus repository workflow
   text contracts;
5. Bash syntax checks for validation and installer scripts; and
6. `git diff --check` over the scoped files.

Actual GitHub-hosted macOS and Windows execution occurs after the workflow is
pushed. Local verification proves the workflow contract and platform suite
selection but cannot impersonate GitHub-hosted operating systems.

## Scope

Expected implementation files:

- `.github/workflows/validation.yml`;
- `tests/test_install_scripts.py`;
- `scripts/validation/run_validation.sh`;
- `tests/test_nextflow_execution_config.py`;
- optionally `tests/test_validation_runner.py` if required by the refactor.

No installer behavior, image tag, package-manager command, Docker command, or
documentation content changes as part of this work.
