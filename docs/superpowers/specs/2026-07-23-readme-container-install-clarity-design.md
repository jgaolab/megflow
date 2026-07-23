# README Container Install Clarity Design

## Goal

Make the main README installation path immediately understandable: the
recommended platform commands already download and run the installer, while the
raw script links are an optional manual alternative rather than an additional
required step.

## Scope

This is a documentation-only change to the “Recommended: Containerized
One-Click Install” section in `README.md`. It will not modify installer scripts,
installation behavior, release versions, download URLs, or the detailed
installer documentation under `scripts/install/README.md`.

## Information Structure

The section introduction will explicitly state that each recommended command:

1. downloads the matching installer into the current writable directory; and
2. immediately runs that installer.

It will also state that users following the recommended command do not need to
download the installer separately.

The instructions will then be organized into three platform subsections:

### Linux

- Provide the Linux one-line command in its own Bash code block.
- Keep the optional `auto`, `docker`, `apptainer`, and `singularity` runtime
  explanation with the Linux command.
- Keep the forced-Apptainer example and the SIF behavior explanation within the
  Linux subsection.

### macOS

- Provide the macOS one-line command in its own Bash code block so its copy
  button copies only the macOS command.

### Windows PowerShell

- Tell users to run the command in Windows PowerShell or a PowerShell tab in
  Windows Terminal.
- Explicitly state that the command is not for Command Prompt (`cmd.exe`) or Git
  Bash because it uses PowerShell syntax.
- Provide the Windows command in its own PowerShell code block.

## Optional Manual Downloads

Move the Linux, macOS, and Windows raw installer links below the platform
commands. Relabel them as optional links for users who want to inspect the
script first or save it for separate manual execution. Do not present these
links as part of the normal one-click installation sequence.

## Verification

- Confirm each platform has a separate heading and code block.
- Confirm the automatic-download explanation precedes the platform commands.
- Confirm the optional manual links follow the commands.
- Confirm the Windows shell guidance names PowerShell and excludes Command
  Prompt and Git Bash.
- Run `git diff --check` on `README.md`.
- Run the focused installer documentation contract test:
  `python -m unittest tests.test_install_scripts.InstallerMetadataContractTests.test_container_install_docs_use_version_pinned_standalone_downloads`.

