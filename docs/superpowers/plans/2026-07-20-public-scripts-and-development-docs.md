# Public Scripts and Development Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish portable user run examples and safe contributor helpers in clear subdirectories, then make the README and validation contracts point to them.

**Architecture:** User launchers live in `examples/run_scripts/`; contributor helpers retain their basenames under `scripts/development/`; validation uses Python unittest plus harmless executable stubs. Existing server-specific scripts are isolated by a strict no-touch boundary.

**Tech Stack:** Bash 3.2+, Python 3.11 `unittest`, GitHub Actions validation, Sphinx/RST, Docker/Nextflow command-line contracts.

## Global Constraints

- Do not modify, rename, remove, stage, untrack, or ignore root `run_MultiDatasets.sh`, root `run_MultiDatasets_sourcecode.sh`, `megflow/reports/test.sh`, ignored local scripts, or `.gitignore`.
- Do not modify, move, document, test, source, or execute `clean_docker.sh`.
- Never run `docker rmi`, `docker system prune`, `docker image prune`, any other Docker cleanup command, or `rm_none_docker.sh --yes`, including through a stub.
- Preserve the basenames `build_megflow.sh`, `build_docs.sh`, `docker2sif.sh`, and `rm_none_docker.sh`.
- Every canonical public Bash script uses `#!/usr/bin/env bash`, `set -euo pipefail`, Bash 3.2-compatible syntax, `--help`, quoted values, and no `/data/liaopan` or absolute Singularity installation path.
- Use `apply_patch` for every file creation, edit, and deletion.

---

### Task 1: Establish the public-script contract in RED

**Files:**
- Create: `tests/test_public_shell_scripts.py`
- Test: `tests/test_public_shell_scripts.py`

**Interfaces:**
- Consumes: repository paths only.
- Produces: `PublicShellScriptContractTests`, reusable `_run_script()` and `_write_stub()` helpers, and the canonical script path lists used by later tasks.

- [ ] **Step 1: Record a clean baseline**

Run:

```bash
python3 scripts/validation/run_unittest_gate.py test_documentation_config_examples test_docker_image_namespace test_nextflow_execution_config test_validation_runner
```

Expected: existing related tests pass before path changes.

- [ ] **Step 2: Add structural and safe-execution tests**

Create the test module with these canonical constants and contracts:

```python
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SCRIPTS = (
    REPO_ROOT / "examples/run_scripts/single_dataset_docker.sh",
    REPO_ROOT / "examples/run_scripts/corpus_docker.sh",
    REPO_ROOT / "examples/run_scripts/corpus_source.sh",
    REPO_ROOT / "examples/run_scripts/interactive_report.sh",
)
DEVELOPMENT_SCRIPTS = (
    REPO_ROOT / "scripts/development/build_megflow.sh",
    REPO_ROOT / "scripts/development/build_docs.sh",
    REPO_ROOT / "scripts/development/docker2sif.sh",
    REPO_ROOT / "scripts/development/rm_none_docker.sh",
)
PUBLIC_SCRIPTS = RUN_SCRIPTS + DEVELOPMENT_SCRIPTS

class PublicShellScriptContractTests(unittest.TestCase):
    def _write_stub(self, root: Path, name: str, body: str) -> Path:
        path = root / name
        path.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body), encoding="utf-8")
        path.chmod(0o755)
        return path

    def _run_script(self, script: Path, *args: str, env=None, cwd=None):
        return subprocess.run(
            ["bash", str(script), *args],
            cwd=cwd or REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_canonical_public_scripts_exist_and_parse(self):
        self.assertTrue(all(path.is_file() for path in PUBLIC_SCRIPTS))
        result = subprocess.run(
            ["bash", "-n", *(str(path) for path in PUBLIC_SCRIPTS)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_public_scripts_share_the_portable_contract(self):
        for path in PUBLIC_SCRIPTS:
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("#!/usr/bin/env bash\n"), path)
            self.assertIn("set -euo pipefail", text, path)
            self.assertNotIn("/data/liaopan", text, path)
            self.assertNotIn("/opt/singularity", text, path)
            result = self._run_script(path, "--help")
            self.assertEqual(result.returncode, 0, f"{path}: {result.stderr}")

    def test_cleanup_helper_is_preview_first_and_clean_docker_is_out_of_scope(self):
        text = DEVELOPMENT_SCRIPTS[-1].read_text(encoding="utf-8")
        self.assertIn('APPLY=false', text)
        self.assertIn('--yes', text)
        self.assertIn('if [ "$APPLY" != true ]', text)
        self.assertNotIn("clean_docker.sh", text)
```

Do not add any test that passes `--yes` to `rm_none_docker.sh`.

- [ ] **Step 3: Run the new module and verify RED**

Run:

```bash
python3 scripts/validation/run_unittest_gate.py test_public_shell_scripts
```

Expected: FAIL because the canonical directories and scripts do not exist.

- [ ] **Step 4: Commit the failing contract**

```bash
git add tests/test_public_shell_scripts.py
git commit -m "test: define public shell script contracts"
```

### Task 2: Implement the four runnable examples

**Files:**
- Create: `examples/README.md`
- Create: `examples/run_scripts/README.md`
- Create: `examples/run_scripts/single_dataset_docker.sh`
- Create: `examples/run_scripts/corpus_docker.sh`
- Create: `examples/run_scripts/corpus_source.sh`
- Create: `examples/run_scripts/interactive_report.sh`
- Delete: `scripts/cohort-dev/run_MultiDatasets.sh`
- Test: `tests/test_public_shell_scripts.py`

**Interfaces:**
- Consumes: `nextflow/quickstart.config`, `nextflow/nextflow_for_docker.config`, `nextflow/megflow.nf`, and the production image entrypoint options.
- Produces: four standalone CLIs with the exact option names in the design spec.

- [ ] **Step 1: Add focused argument-assembly tests before implementation**

Extend `PublicShellScriptContractTests` with harmless Docker/Nextflow stubs. Capture arguments in `MEGFLOW_TEST_CALLS` and assert:

```python
self.assertIn("--corpus", calls)
self.assertIn("--steps\nmeg_ica", calls)
self.assertIn("-r", report_calls)
self.assertIn("8501:8501", report_calls)
self.assertIn("-profile\nlocal,strict", source_calls)
```

Use `--dry-run` for launchers whenever command capture is not needed. No real Docker or Nextflow process may start.

- [ ] **Step 2: Run the focused tests and verify RED**

```bash
python3 scripts/validation/run_unittest_gate.py test_public_shell_scripts.PublicShellScriptContractTests
```

Expected: FAIL because the runnable scripts are missing.

- [ ] **Step 3: Implement common launcher behavior independently in each readable script**

Each launcher must define these Bash 3.2-compatible helpers directly:

```bash
die() {
    printf 'Error: %s\n' "$*" >&2
    exit 2
}

require_value() {
    [ "$#" -ge 2 ] && [ -n "$2" ] || die "$1 requires a value"
}

print_command() {
    printf 'Command:'
    printf ' %q' "$@"
    printf '\n'
}
```

Parse only the options specified in the design. Resolve `REPO_ROOT` with `BASH_SOURCE`, create only explicit writable output/smri paths, use read-only mounts for config/license, adapt `-it`/`-i`, and pass all MEGFlow options after the image name.

- [ ] **Step 4: Write the example navigation**

`examples/README.md` links `run_scripts/`, `megflow/`, and `opm_conversion/`. `examples/run_scripts/README.md` provides a choose-by-goal table, one complete invocation per script, the common safety behavior, and links to `nextflow/quickstart.config` and the formal docs.

- [ ] **Step 5: Remove only the public cohort-dev launcher**

Delete `scripts/cohort-dev/run_MultiDatasets.sh` with `apply_patch`. Confirm the three excluded server scripts and `.gitignore` have no diff.

- [ ] **Step 6: Run the runnable-example contracts**

```bash
python3 scripts/validation/run_unittest_gate.py test_public_shell_scripts
bash -n examples/run_scripts/*.sh
```

Expected: runnable-example tests pass; development-script existence assertions still fail until Task 3 if kept in the same module, so run qualified runnable test methods when necessary.

- [ ] **Step 7: Commit the runnable examples**

```bash
git add examples/README.md examples/run_scripts scripts/cohort-dev/run_MultiDatasets.sh tests/test_public_shell_scripts.py
git commit -m "feat: add portable run script examples"
```

### Task 3: Move and harden the four development helpers

**Files:**
- Create: `scripts/development/build_megflow.sh`
- Create: `scripts/development/build_docs.sh`
- Create: `scripts/development/docker2sif.sh`
- Create: `scripts/development/rm_none_docker.sh`
- Delete: `build_megflow.sh`
- Delete: `build_docs.sh`
- Delete: `docker2sif.sh`
- Delete: `rm_none_docker.sh`
- Test: `tests/test_public_shell_scripts.py`

**Interfaces:**
- Consumes: Docker CLI, Python/Sphinx, and Apptainer/Singularity only after preflight checks.
- Produces: the four canonical helper CLIs while preserving basenames.

- [ ] **Step 1: Add helper behavior tests before implementation**

Add tests that use harmless stubs or dry-run output to assert:

```python
self.assertIn("build", build_output)
self.assertIn("cplmeg/megflow:local", build_output)
self.assertIn("python", docs_output)
self.assertIn("sphinx", docs_output)
self.assertIn("docker-daemon://cplmeg/megflow:local", sif_output)
```

For `rm_none_docker.sh`, test only:

- static source assertions for the `--yes` guard;
- `--help`;
- preview execution with a harmless `docker images` stub that returns no IDs.

Never invoke the helper with `--yes`; never provide a stub implementation for `docker rmi`.

- [ ] **Step 2: Run the focused tests and verify RED**

```bash
python3 scripts/validation/run_unittest_gate.py test_public_shell_scripts
```

Expected: FAIL because `scripts/development/` does not yet contain the helpers.

- [ ] **Step 3: Implement `build_megflow.sh` and `build_docs.sh`**

Implement the exact interfaces from the spec. `build_megflow.sh` defaults to `cplmeg/megflow:local`, validates `docker info` only outside dry-run, and prints the assembled `docker build` command. `build_docs.sh` uses the active Python, validates Sphinx imports, confines `--clean` to the resolved output under `docs/build`, and runs `python -m sphinx` with strict flags only when selected.

- [ ] **Step 4: Implement `docker2sif.sh`**

Discover `apptainer` then `singularity`, sanitize `/` and `:` into `_` for the default output, verify `docker image inspect` only outside dry-run, refuse an existing output without `--force`, and assemble:

```bash
"$RUNTIME_BIN" build ${FORCE:+--force} "$OUTPUT" "docker-daemon://$IMAGE"
```

Build the optional `--force` argument with an array rather than relying on the shown parameter expansion when empty.

- [ ] **Step 5: Implement preview-first `rm_none_docker.sh` without executing cleanup**

The source must initialize `APPLY=false`, parse only `--yes` and `--help`, obtain dangling IDs through `docker images --filter dangling=true --quiet`, print them, and exit before any deletion unless `APPLY=true`. Do not execute the `--yes` branch during implementation or verification.

- [ ] **Step 6: Delete only the four old public helper paths**

Use `apply_patch` deletions for the old root files. Do not touch `clean_docker.sh` or any server-script path.

- [ ] **Step 7: Run public helper contracts**

```bash
python3 scripts/validation/run_unittest_gate.py test_public_shell_scripts
bash -n scripts/development/build_megflow.sh scripts/development/build_docs.sh scripts/development/docker2sif.sh scripts/development/rm_none_docker.sh
```

Expected: PASS. These commands must not include `--yes` or any Docker cleanup invocation.

- [ ] **Step 8: Commit development helpers**

```bash
git add build_megflow.sh build_docs.sh docker2sif.sh rm_none_docker.sh scripts/development tests/test_public_shell_scripts.py
git commit -m "build: organize development helper scripts"
```

### Task 4: Rewrite public navigation and Development documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/source/reference/examples_profiles.rst`
- Modify: `docs/source/reference/configuration_execution.rst`
- Modify: `docs/source/reference/validation.rst`
- Modify: `nextflow/nextflow_multi_dataset_demo.config`
- Modify: `tests/test_documentation_config_examples.py`
- Modify: `tests/test_docker_image_namespace.py`
- Modify: `tests/test_nextflow_execution_config.py`

**Interfaces:**
- Consumes: canonical paths created by Tasks 2 and 3.
- Produces: public documentation with no promoted dependency on server-specific launchers.

- [ ] **Step 1: Update path contracts first and verify RED**

Set the documented source-runner constants to:

```python
REPO_ROOT / "examples" / "run_scripts" / "corpus_source.sh"
```

Set the Docker build helper path to:

```python
REPO_ROOT / "scripts" / "development" / "build_megflow.sh"
```

Add assertions that README links all four run examples and all four in-scope development helpers, and that it does not mention `clean_docker.sh`.

Run the three modified modules and confirm they fail against the old docs before editing prose.

- [ ] **Step 2: Add the concise README Runnable Examples section**

Insert a choose-by-goal table in Usage with links to the four scripts, show one single-dataset command, and link the complete run-script guide.

- [ ] **Step 3: Replace the README Development section**

Write the nine subsections defined in the spec. Commands must use `scripts/development/<basename>`. Document `rm_none_docker.sh` as preview-only by default and explicitly warn that deletion requires `--yes`. Do not mention `clean_docker.sh`.

- [ ] **Step 4: Update RST and config comments**

Replace promoted `run_MultiDatasets_sourcecode.sh` commands with `examples/run_scripts/corpus_source.sh --config nextflow/nextflow_multi_dataset_demo.config` and translate old environment overrides into the new CLI options. Update validation docs to list native Linux, macOS, and Windows installer jobs.

- [ ] **Step 5: Run documentation/path contracts**

```bash
python3 scripts/validation/run_unittest_gate.py test_documentation_config_examples test_docker_image_namespace test_nextflow_execution_config
```

Expected: PASS.

- [ ] **Step 6: Commit documentation**

```bash
git add README.md docs/source/reference/examples_profiles.rst docs/source/reference/configuration_execution.rst docs/source/reference/validation.rst nextflow/nextflow_multi_dataset_demo.config tests/test_documentation_config_examples.py tests/test_docker_image_namespace.py tests/test_nextflow_execution_config.py
git commit -m "docs: document runnable examples and developer tools"
```

### Task 5: Wire validation and complete verification

**Files:**
- Modify: `scripts/validation/run_validation.sh`
- Modify: `tests/test_validation_runner.py` only if an explicit routing assertion is needed
- Test: all scoped files

**Interfaces:**
- Consumes: `test_public_shell_scripts` from Task 1.
- Produces: CI and complete local routing ownership for the new test module.

- [ ] **Step 1: Add the new test module to both routing gates**

Add `test_public_shell_scripts` once to the static module list in `run_routing_ci()` and once to the full list in `run_routing()`. Do not add it to any installer-platform job.

- [ ] **Step 2: Run related unittest validation**

```bash
python3 scripts/validation/run_unittest_gate.py test_public_shell_scripts test_documentation_config_examples test_docker_image_namespace test_nextflow_execution_config test_validation_runner
```

Expected: all discovered tests pass with no skips.

- [ ] **Step 3: Run syntax and strict documentation checks**

```bash
bash -n examples/run_scripts/*.sh scripts/development/*.sh scripts/validation/run_validation.sh
python3 -m sphinx -W --keep-going -b html docs/source docs/build/html
```

If the current Python lacks the pinned documentation dependencies, use the existing project environment that provides `requirements_doc.txt`; do not install unrelated packages.

- [ ] **Step 4: Verify the no-touch and no-cleanup boundary**

Run read-only diff checks only:

```bash
git diff --quiet -- clean_docker.sh run_MultiDatasets.sh run_MultiDatasets_sourcecode.sh megflow/reports/test.sh .gitignore
git diff --check
```

Expected: the first command exits `0`; the second reports no whitespace errors. Do not run any excluded script.

- [ ] **Step 5: Inspect the complete scoped diff**

```bash
git status --short
git diff --stat
git diff -- examples scripts/development README.md docs/source nextflow/nextflow_multi_dataset_demo.config tests scripts/validation/run_validation.sh
```

Confirm no unrelated user change is staged or modified.

- [ ] **Step 6: Commit validation wiring**

```bash
git add scripts/validation/run_validation.sh tests/test_validation_runner.py
git commit -m "ci: validate public shell script contracts"
```
