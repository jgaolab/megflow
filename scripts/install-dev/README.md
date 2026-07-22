# MEGFlow Local Development Install (Linux)

This directory contains local development install scripts that do **not** depend
on Docker image pulling.

> **Important:** This is a source installation. The installer automatically
> clones or updates the GitHub source under `~/.megflow-dev/src/megflow` by
> default. You do not need to clone the repository first or run from its root;
> download and execute the installer from any writable directory. Git and
> access to GitHub are required.

## Script List

- Linux (local development): `install_megflow_dev_linux.sh`

## What This Script Does

The script installs toolchains directly into a target directory:

1. Pull or update source code from `https://github.com/jgaolab/megflow.git`
2. Check Conda availability; auto-install **Miniconda** if Conda is missing
3. Reuse an existing named Conda environment `megflow` when found; otherwise create one under `<install-dir>/conda-envs/megflow`
4. Install dependencies from source `requirements.txt` unless `--skip-requirements` is used
5. Install or reuse **Nextflow** (prefer current system; otherwise install under `<install-dir>/nextflow/bin`)
6. Install or reuse **FreeSurfer** (enabled by default, installed under `<install-dir>/freesurfer/conda-env` if needed)
7. Verify `nextflow` / `freesurfer` / `conda` / Python env health
8. Generate `<install-dir>/env.sh` for one-command environment loading

## Usage

```bash
curl -fL -o install_megflow_dev_linux.sh https://raw.githubusercontent.com/jgaolab/megflow/main/scripts/install-dev/install_megflow_dev_linux.sh && bash install_megflow_dev_linux.sh
```

The downloaded installer remains in the current directory. Reuse it with
options when a non-default installation is needed:

```bash
bash install_megflow_dev_linux.sh --install-dir /data/megflow-dev
bash install_megflow_dev_linux.sh --no-freesurfer
```

Options:

- `--install-dir <dir>`: installation root (default `~/.megflow-dev`)
- `--no-freesurfer`: skip FreeSurfer installation
- `--with-freesurfer`: explicitly enable FreeSurfer installation (default)
- `--skip-requirements`: skip `requirements.txt` installation
- `--conda-prefix <dir>`: custom FreeSurfer Conda prefix (default `<install-dir>/freesurfer/conda-env`)
- `--repo-dir <dir>`: custom source directory (default `<install-dir>/src/megflow`)
- `--repo-url <url>`: custom git source URL
- `--miniconda-root <dir>`: custom Miniconda install path when Conda is missing

## After Installation

```bash
source <install-dir>/env.sh
cd <repo-dir>
nextflow info
python -c 'import mne; print(mne.__version__)'
```

If FreeSurfer is installed:

```bash
recon-all -version
```

Note: FreeSurfer runtime still requires a valid license file.
