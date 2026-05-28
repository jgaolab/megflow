# MEGPrep One-Click Install Scripts

MEGPrep is officially distributed as a **Docker image** (`cmrlab/megprep`).
For Linux HPC environments where Docker daemon is unavailable, the Linux script supports an Apptainer/Singularity workflow by pulling from `docker://cmrlab/megprep:<tag>`.

## Script List

- Linux: `install_megprep_linux.sh`
- macOS: `install_megprep_macos.sh`
- Windows (PowerShell): `install_megprep_windows.ps1`

## What These Scripts Do

Each script automatically performs the following steps:

1. Check and install container runtime (Docker on Windows/macOS; Docker or Apptainer/Singularity on Linux).
2. Pull `cmrlab/megprep:<tag>` (default `latest`).
3. Run `-h` inside the container image to print help text and verify installation.
4. Validate basic inputs (for example, image tag cannot be empty).

## Usage

### Linux

```bash
bash scripts/install/install_megprep_linux.sh
bash scripts/install/install_megprep_linux.sh 0.0.3
bash scripts/install/install_megprep_linux.sh 0.0.3 apptainer
bash scripts/install/install_megprep_linux.sh 0.0.3 docker
```

Linux runtime mode argument (2nd arg):
- `auto` (default): use Docker if daemon is usable, otherwise fallback to Apptainer/Singularity
- `docker`: force Docker flow
- `apptainer`: force Apptainer/Singularity flow

Optional environment variable:
- `MEGPREP_SIF_PATH`: output path for pulled SIF image (default `./megprep_<tag>.sif`)

Notes:
- This script is Linux-only and exits early on non-Linux systems.
- In `auto` mode, Docker is preferred only when daemon is actually usable (`docker info` succeeds).
- If Docker is already usable, the script will not force a privileged Docker service start.

### macOS

```bash
bash scripts/install/install_megprep_macos.sh
bash scripts/install/install_megprep_macos.sh 0.0.3
```

Notes:
- This script is macOS-only and exits early on non-macOS systems.

### Windows PowerShell

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install\install_megprep_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\install\install_megprep_windows.ps1 -ImageTag 0.0.3
```

## Troubleshooting

- Docker CLI exists but `docker info` fails:
  - Start Docker Desktop (macOS/Windows), or ensure Docker daemon is running (Linux).
  - Confirm current user has permission to run Docker commands.
- Linux server/HPC without Docker daemon:
  - Use Apptainer mode directly:
    - `bash scripts/install/install_megprep_linux.sh <tag> apptainer`
- Package installation fails:
  - Re-run with proper privileges (`root` or `sudo`) and check network/package mirror access.
- Image tag issues:
  - Make sure the tag is not empty and exists in `cmrlab/megprep`.
