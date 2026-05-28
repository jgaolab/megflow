# MEGPrep Local Development Install (Linux)

This directory contains local development install scripts that do **not** depend on Docker image pulling.

## Script List

- Linux (local development): `install_megprep_dev_linux.sh`

## What This Script Does

The script installs toolchains directly into a target directory:

1. Pull or update source code from `https://github.com/LiaoPan/megprep`
2. Check Conda availability; auto-install **Miniconda** if Conda is missing
3. Reuse an existing named Conda environment `megprep` when found; otherwise create one under `<install-dir>/conda-envs/megprep`
4. Install dependencies from source `requirements.txt` unless `--skip-requirements` is used
5. Install or reuse **Nextflow** (prefer current system; otherwise install under `<install-dir>/nextflow/bin`)
6. Install or reuse **FreeSurfer** (enabled by default, installed under `<install-dir>/freesurfer/conda-env` if needed)
7. Verify `nextflow` / `freesurfer` / `conda` / Python env health
8. Generate `<install-dir>/env.sh` for one-command environment loading

## Usage

```bash
bash scripts/install-dev/install_megprep_dev_linux.sh
bash scripts/install-dev/install_megprep_dev_linux.sh --install-dir /data/megprep-dev
bash scripts/install-dev/install_megprep_dev_linux.sh --no-freesurfer
```

Options:

- `--install-dir <dir>`: installation root (default `~/.megprep-dev`)
- `--no-freesurfer`: skip FreeSurfer installation
- `--with-freesurfer`: explicitly enable FreeSurfer installation (default)
- `--skip-requirements`: skip `requirements.txt` installation
- `--conda-prefix <dir>`: custom FreeSurfer Conda prefix (default `<install-dir>/freesurfer/conda-env`)
- `--repo-dir <dir>`: custom source directory (default `<install-dir>/src/megprep`)
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
