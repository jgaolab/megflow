# README Container Install Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the main README container installation section so users understand that the recommended commands automatically download and run the installer, can copy one platform command at a time, and know exactly where to run the Windows command.

**Architecture:** Replace only the existing “Recommended: Containerized One-Click Install” block in `README.md`. Use three platform-specific subsections, keep Linux-only runtime guidance beside the Linux command, and move raw installer links into a clearly optional manual-download subsection after the automatic commands.

**Tech Stack:** GitHub-flavored Markdown, Bash command examples, Windows PowerShell command example, Python `unittest` documentation contracts.

## Global Constraints

- Modify only the main README installation section; do not modify installer scripts or installation behavior.
- Preserve release version `1.0.0`, all installer URLs, image naming, and every executable command.
- Give Linux, macOS, and Windows PowerShell separate headings and code blocks.
- Keep `auto`, `docker`, `apptainer`, `singularity`, the forced-Apptainer example, and SIF behavior inside the Linux subsection.
- State that the recommended commands automatically download and immediately run the installer, so separate download links are unnecessary for normal installation.
- State that the Windows command runs in Windows PowerShell or a PowerShell tab in Windows Terminal, not Command Prompt (`cmd.exe`) or Git Bash.
- Place direct installer links after the platform commands and label them optional for inspection or later manual execution.
- Do not modify `scripts/install/README.md`, the Sphinx documentation, or unrelated README sections.

---

### Task 1: Reorganize the container one-click installation section

**Files:**
- Modify: `README.md:77-113`
- Test unchanged contract: `tests/test_install_scripts.py`

**Interfaces:**
- Consumes: the existing version-pinned Linux, macOS, and Windows installer commands.
- Produces: a command-first README section with one copyable block per platform and an optional manual-download path.

- [ ] **Step 1: Confirm the new platform structure is absent before editing**

Run:

```bash
rg -n '^#### (Linux|macOS|Windows PowerShell|Optional: Inspect or Download the Installer Manually)$' README.md
```

Expected before the change: no matching four-heading structure in the current
README installation section.

- [ ] **Step 2: Replace the approved README section**

Replace the content from `### Recommended: Containerized One-Click Install`
through the existing `For more details, see scripts/install/README.md.` line
with this exact Markdown:

````markdown
### Recommended: Containerized One-Click Install

The commands below automatically download the matching installer into the
current writable directory and run it immediately. You do not need to clone the
MEGFlow repository or download the installer separately.

Set `MEGFLOW_VERSION` once to download the installer from the same Git release
and pull the matching `cplmeg/megflow` image tag. Use the release number without
a leading `v`, for example `1.0.0`.

#### Linux

Run the following command in a terminal:

```bash
MEGFLOW_VERSION=1.0.0 && curl -fL -o install_megflow_linux.sh "https://raw.githubusercontent.com/jgaolab/megflow/v${MEGFLOW_VERSION}/scripts/install/install_megflow_linux.sh" && bash install_megflow_linux.sh "${MEGFLOW_VERSION}"
```

The optional second argument selects `auto` (default), `docker`, `apptainer`,
or `singularity`. For example, force Apptainer with:

```bash
MEGFLOW_VERSION=1.0.0 && curl -fL -o install_megflow_linux.sh "https://raw.githubusercontent.com/jgaolab/megflow/v${MEGFLOW_VERSION}/scripts/install/install_megflow_linux.sh" && bash install_megflow_linux.sh "${MEGFLOW_VERSION}" apptainer
```

The Apptainer/Singularity path does not use a Docker daemon. It downloads the
published OCI layers from Docker Hub and converts them into
`./megflow_<version>.sif` (or `MEGFLOW_SIF_PATH`).

#### macOS

Run the following command in Terminal:

```bash
MEGFLOW_VERSION=1.0.0 && curl -fL -o install_megflow_macos.sh "https://raw.githubusercontent.com/jgaolab/megflow/v${MEGFLOW_VERSION}/scripts/install/install_megflow_macos.sh" && bash install_megflow_macos.sh "${MEGFLOW_VERSION}"
```

#### Windows PowerShell

Open **Windows PowerShell**, or open a **PowerShell** tab in Windows Terminal,
and paste the complete command below. Do not run it in Command Prompt
(`cmd.exe`) or Git Bash because it uses PowerShell syntax.

```powershell
$MEGFLOW_VERSION = "1.0.0"; $ErrorActionPreference = "Stop"; Invoke-WebRequest -Uri "https://raw.githubusercontent.com/jgaolab/megflow/v${MEGFLOW_VERSION}/scripts/install/install_megflow_windows.ps1" -OutFile "install_megflow_windows.ps1"; powershell -ExecutionPolicy Bypass -File .\install_megflow_windows.ps1 -ImageTag $MEGFLOW_VERSION
```

#### Optional: Inspect or Download the Installer Manually

The commands above already download the installer automatically. Use these
direct links only if you want to inspect a script first or save it for later
manual execution:

[Linux installer](https://raw.githubusercontent.com/jgaolab/megflow/v1.0.0/scripts/install/install_megflow_linux.sh),
[macOS installer](https://raw.githubusercontent.com/jgaolab/megflow/v1.0.0/scripts/install/install_megflow_macos.sh), and
[Windows installer](https://raw.githubusercontent.com/jgaolab/megflow/v1.0.0/scripts/install/install_megflow_windows.ps1).

For more details, see `scripts/install/README.md`.
````

- [ ] **Step 3: Verify the structure and Markdown whitespace**

Run:

```bash
rg -n '^#### (Linux|macOS|Windows PowerShell|Optional: Inspect or Download the Installer Manually)$|automatically download|Command Prompt|Git Bash' README.md
git diff --check -- README.md
```

Expected: the four headings appear once in Linux → macOS → Windows → optional
manual-download order; automatic behavior and Windows shell guidance are found;
`git diff --check` exits `0` with no output.

- [ ] **Step 4: Run the installer documentation contract**

Run:

```bash
python -m unittest tests.test_install_scripts.InstallerMetadataContractTests.test_container_install_docs_use_version_pinned_standalone_downloads
```

Expected: one test passes with output ending in `OK`.

- [ ] **Step 5: Review and commit only the approved files**

Run:

```bash
git diff -- README.md
git add README.md
git commit -m "docs: clarify one-click installation"
```

Expected: the implementation commit contains only `README.md`; the design and
implementation plan remain in their earlier dedicated commits.

