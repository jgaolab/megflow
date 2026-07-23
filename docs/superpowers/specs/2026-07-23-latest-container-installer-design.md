# Latest Container Installer Design

## Goal

Ensure the one-click installation commands always download the current
installer implementation while allowing users to choose the Docker image tag
independently.

## Version Semantics

The public commands use two deliberately separate sources:

- Installer source: the `main` branch under
  `https://raw.githubusercontent.com/jgaolab/megflow/main/scripts/install/`.
- Image version: `MEGFLOW_VERSION`, with `latest` in the recommended commands.

Changing `MEGFLOW_VERSION` therefore changes only the
`cplmeg/megflow:<tag>` image selected by the installer. It never constructs a
Git reference such as `vlatest`.

## Documentation Changes

Update the equivalent containerized one-click instructions in:

- `README.md`
- `docs/source/quickstart/installation.rst`
- `scripts/install/README.md`

The recommended Linux, macOS, Windows, and forced-Apptainer commands download
their installer from `main` and set `MEGFLOW_VERSION` to `latest`.

Retain a clearly labeled pinned-image example using
`MEGFLOW_VERSION=1.0.0`. The pinned example still downloads the current
installer from `main`; only the image tag is pinned.

Manual installer links also point to `main` so users do not inspect or save a
known-outdated release script.

## Non-Goals

- Do not change the installers' internal no-argument defaults.
- Do not move or recreate the existing `v1.0.0` Git tag.
- Do not change Docker image publishing or release automation.
- Do not edit generated HTML documentation.

## Verification

- Replace the old version-pinned documentation contract with a contract that
  requires `MEGFLOW_VERSION=latest` and `main/scripts/install` in all three
  documents.
- Require a retained `MEGFLOW_VERSION=1.0.0` pinned-image example.
- Reject `v${MEGFLOW_VERSION}/scripts/install` and `/v1.0.0/scripts/install`
  from the three public documents.
- Validate all documented shell commands and Docker entrypoint options.
- Run the installer test module and `git diff --check`.
