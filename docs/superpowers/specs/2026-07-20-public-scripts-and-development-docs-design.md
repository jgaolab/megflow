# Public Run Scripts and Development Documentation Design

## Goal

Make the scripts published by MEGFlow portable, consistently organized, parameterized, safe by default, and discoverable from the main README. Separate user-facing runnable examples from contributor-facing development helpers without touching the maintainer's server-specific scripts.

## Scope Boundary

This change will:

- add canonical user examples under `examples/run_scripts/`;
- move the public development helpers into `scripts/development/` while preserving their existing basenames;
- parameterize and harden those public helpers;
- rewrite the README runnable-example and Development guidance;
- update public RST references and validation coverage.

This change will not modify, rename, remove, stage, untrack, or ignore any server-specific script. In particular, it will not touch:

- root `run_MultiDatasets.sh`;
- root `run_MultiDatasets_sourcecode.sh`;
- `megflow/reports/test.sh`;
- ignored or untracked local `run_*.sh` files;
- `.gitignore` or the Git tracking state of those files.

`clean_docker.sh` is completely excluded. It will not be moved, modified, documented, tested, or executed. No implementation or verification command may run `docker system prune`, `docker image prune`, `docker rmi`, or any other Docker cleanup operation.

## Chosen Structure

```text
examples/
├── README.md
├── megflow/
├── opm_conversion/
└── run_scripts/
    ├── README.md
    ├── single_dataset_docker.sh
    ├── corpus_docker.sh
    ├── corpus_source.sh
    └── interactive_report.sh

scripts/
├── development/
│   ├── build_megflow.sh
│   ├── build_docs.sh
│   ├── docker2sif.sh
│   └── rm_none_docker.sh
├── install/
├── install-dev/
└── validation/
```

The public `scripts/cohort-dev/run_MultiDatasets.sh` logic becomes the starting point for `examples/run_scripts/corpus_docker.sh`. The existing server-specific root launchers are not used as source material and remain untouched.

The following public development helpers retain their current filenames:

| Current path | Canonical path |
|---|---|
| `build_megflow.sh` | `scripts/development/build_megflow.sh` |
| `build_docs.sh` | `scripts/development/build_docs.sh` |
| `docker2sif.sh` | `scripts/development/docker2sif.sh` |
| `rm_none_docker.sh` | `scripts/development/rm_none_docker.sh` |

No compatibility wrappers will be added at the old development-script paths; README and tests will point to the canonical paths.

## Common Public-Script Contract

Every new or hardened public Bash script must:

- use `#!/usr/bin/env bash` and `set -euo pipefail`;
- remain compatible with Bash 3.2 or newer;
- resolve the repository root from its own location rather than the caller's current directory;
- use lowercase `snake_case` filenames and `--kebab-case` long options;
- provide `--help` that succeeds without Docker, Nextflow, Conda, or Singularity being installed;
- reject unknown options and missing option values with an actionable message;
- quote all path and user-supplied values;
- contain no `/data/liaopan` path or hard-coded runtime installation path;
- validate required commands, files, directories, and writable destinations before launching work;
- provide `--dry-run` for commands that build, convert, or launch external runtimes;
- print a concise execution summary and the final output/report location;
- return `0` for success or a safe no-op, `1` for an external command failure, and `2` for invalid arguments or unmet preconditions.

CLI arguments take precedence over documented environment fallbacks, which take precedence over safe defaults.

## Runnable Examples

### `single_dataset_docker.sh`

Purpose: run a first single-dataset Docker analysis using the official entrypoint.

Required options:

- `--input DIR`
- `--output DIR`

Optional options:

- `--config FILE`, defaulting to the repository's `nextflow/quickstart.config`;
- `--smri DIR`;
- `--license FILE`;
- `--image IMAGE`, defaulting to `cplmeg/megflow:latest`;
- `--steps VALUE`, defaulting to `meg_ica`;
- `--anat-method freesurfer|deepprep|pseudomri`;
- `--resume`;
- `--dry-run`;
- `--help`.

The script checks Docker availability, readable input/config/license paths, and writable output/smri bind sources. It creates only explicitly supplied output/smri directories as the current user. It never recursively changes ownership or permissions.

### `corpus_docker.sh`

Purpose: run every immediate child of a corpus root through the official Docker `--corpus` entrypoint.

Required options:

- `--input DIR`
- `--output DIR`

Optional options:

- `--config FILE`, defaulting to `nextflow/nextflow_for_docker.config`;
- `--smri DIR`, defaulting to `<output>/smri`;
- `--license FILE`;
- `--image IMAGE`, defaulting to `cplmeg/megflow:latest`;
- `--steps VALUE`, defaulting to `meg_ica`;
- `--resume`;
- `--dry-run`;
- `--help`.

The script verifies that the corpus root contains at least one immediate dataset directory and mounts configuration/license files read-only. It prints the corpus report destination.

### `corpus_source.sh`

Purpose: run a corpus configuration with host Nextflow rather than Docker.

Required options:

- `--config FILE`.

Optional options:

- `--pipeline FILE`, defaulting to `nextflow/megflow.nf`;
- `--nextflow PATH_OR_COMMAND`, defaulting to `nextflow`;
- `--profile VALUE`, defaulting to `local,strict`;
- `--conda-env NAME`;
- `--work-dir DIR`;
- `--log-file FILE`;
- `--resume` or `--no-resume`, defaulting to resume;
- `--dry-run`;
- `--help`.

The config remains authoritative for corpus input, output, dataset profiles, and scientific parameters. The script must not silently select the server-specific demo config. It validates the pipeline/config, resolves Nextflow, derives default work/log paths from the configured output when possible, and prints the exact shell-escaped command in dry-run mode.

### `interactive_report.sh`

Purpose: open the Streamlit report viewer for existing output without running Nextflow.

Required options:

- `--output DIR`.

Optional options:

- `--smri DIR`;
- `--image IMAGE`, defaulting to `cplmeg/megflow:latest`;
- `--port PORT`, defaulting to `8501`;
- `--dry-run`;
- `--help`.

The script validates the output and optional anatomy directories, verifies that the port is an integer from 1 through 65535, adapts Docker TTY flags to the current environment, runs the image with `-r`, and prints the viewer URL.

## Development Helpers

### `build_megflow.sh`

The script builds `megflow.Dockerfile` from the repository root regardless of the caller's working directory.

Options:

- `--image NAME`, default `cplmeg/megflow`;
- `--tag TAG`, default `local` so development builds do not overwrite a release tag;
- `--dockerfile FILE`, default `megflow.Dockerfile`;
- `--platform VALUE`;
- `--no-cache`;
- `--dry-run`;
- `--help`.

It checks the Docker client, daemon, Dockerfile, and build context before launching the build.

### `build_docs.sh`

Options:

- `--clean`;
- `--strict`;
- `--output DIR`, default `docs/build/html`;
- `--help`.

The script checks Python/Sphinx dependencies, optionally removes only the resolved documentation output directory, and uses `python -m sphinx`. Strict mode matches CI with `-W --keep-going`. It never depends on the caller's current directory.

### `docker2sif.sh`

Options:

- `--image IMAGE`, default `cplmeg/megflow:local`;
- `--output FILE`, defaulting to a sanitized image/tag `.sif` filename;
- `--runtime auto|apptainer|singularity`, default `auto` with Apptainer preferred;
- `--force`;
- `--dry-run`;
- `--help`.

The script discovers the runtime on `PATH`, verifies the local Docker image, and refuses to overwrite an existing output unless `--force` is explicit. It does not build or pull an image automatically.

### `rm_none_docker.sh`

Purpose: preview and, only with explicit confirmation, remove dangling Docker image IDs.

Options:

- `--yes`, required before deletion;
- `--help`.

Default execution is preview-only. It lists dangling IDs and prints the opt-in command without deleting anything. An empty result exits successfully. The implementation uses explicit parsed IDs and does not use unguarded command substitution.

Automated tests and verification may run only `--help`, preview, and static contract checks for this script. They must not exercise its `--yes` branch, even with a stubbed Docker executable. The implementation session itself must not run `docker rmi`, any Docker prune command, or `clean_docker.sh`.

## Documentation Design

The main README gains a compact `Runnable Examples` table linking four user goals to `examples/run_scripts/`. It shows one first-run command and delegates full options and troubleshooting to `examples/run_scripts/README.md`.

`examples/README.md` becomes the public examples index and links run scripts, MEGFlow notebooks/configs, and OPM conversion examples.

The README Development section is rewritten in this order:

1. prerequisites;
2. local development setup;
3. public developer-script reference;
4. building the Docker image;
5. building and strictly validating documentation;
6. validation and regression-test modes;
7. advanced local Docker-to-SIF conversion;
8. dangling-image cleanup safety;
9. pull-request workflow.

The developer-script reference records each script's purpose, command/options, prerequisites, outputs or side effects, platform limitations, and safety notes. The validation description lists routing, scientific, native Linux/macOS/Windows installer, and strict documentation jobs.

Public references in README, `docs/source/reference/examples_profiles.rst`, `docs/source/reference/configuration_execution.rst`, `docs/source/reference/validation.rst`, and the header of `nextflow/nextflow_multi_dataset_demo.config` are updated to canonical public paths. Server-script contents remain untouched.

## Validation Design

Add `tests/test_public_shell_scripts.py` and update path-sensitive existing contracts. Validation will:

- run `bash -n` on the canonical public scripts;
- assert the standard shebang, strict mode, help contract, and portable path rules;
- verify help and invalid-argument behavior without external runtimes;
- use harmless command stubs to capture Docker launch, Docker build, SIF conversion, and source Nextflow argument assembly;
- verify dry-run modes do not call external commands;
- statically verify `rm_none_docker.sh` is preview-only unless `--yes` is present;
- run only the preview branch of `rm_none_docker.sh` with a harmless `docker images` stub that returns no image IDs;
- never invoke `docker rmi`, any prune command, `clean_docker.sh`, or the `--yes` branch;
- assert that canonical public scripts contain no server-specific or hard-coded runtime paths;
- verify every README/RST script reference resolves to a tracked file.

`test_public_shell_scripts` is assigned to both `routing-ci` and the complete local `routing` gate. CI will not build the large Docker image, build a real SIF, launch a real container, or perform cleanup.

## Acceptance Criteria

- Four canonical user examples exist under `examples/run_scripts/` and work from any current directory.
- Four public development helpers exist under `scripts/development/` with their original basenames.
- New/hardened public scripts are parameterized, portable, self-documenting, and safe by default.
- No canonical public script contains server-specific paths or an absolute Singularity installation path.
- No Docker cleanup action is executed during implementation or verification.
- `clean_docker.sh`, server-specific scripts, `.gitignore`, and their Git state are unchanged.
- README and RST references point to canonical public paths and the Development section documents every in-scope helper.
- Public-shell contract tests, related existing tests, Bash syntax checks, and strict Sphinx documentation build pass.
