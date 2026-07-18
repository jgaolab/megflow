# MEGFlow One-Click Install Scripts

MEGFlow is officially distributed as a **Docker image** (`cplmeg/megflow`).
For Linux HPC environments where Docker daemon is unavailable, the Linux script supports an Apptainer/Singularity workflow by pulling from `docker://cplmeg/megflow:<tag>`.

## Script List

- Linux: `install_megflow_linux.sh`
- macOS: `install_megflow_macos.sh`
- Windows (PowerShell): `install_megflow_windows.ps1`

## What These Scripts Do

Each script automatically performs the following steps:

1. Check and, when supported by the host package manager, install a container
   runtime (Docker on Windows/macOS; Docker or Apptainer/Singularity on Linux).
2. Pull `cplmeg/megflow:<tag>` (default `latest`).
3. Run `-h` inside the container image to print help text and verify installation.
4. Validate basic inputs (for example, image tag cannot be empty).

## Usage

### Linux

```bash
bash scripts/install/install_megflow_linux.sh
bash scripts/install/install_megflow_linux.sh 1.0.0
bash scripts/install/install_megflow_linux.sh 1.0.0 apptainer
bash scripts/install/install_megflow_linux.sh 1.0.0 docker
```

Linux runtime mode argument (2nd arg):
- `auto` (default): use Docker if daemon is usable, otherwise fallback to Apptainer/Singularity
- `docker`: force Docker flow
- `apptainer`: force Apptainer/Singularity flow

Optional environment variable:
- `MEGFLOW_SIF_PATH`: output path for pulled SIF image (default `./megflow_<tag>.sif`)

Notes:
- This script is Linux-only and exits early on non-Linux systems.
- In `auto` mode, Docker is preferred only when daemon is actually usable (`docker info` succeeds).
- If Docker is already usable, the script will not force a privileged Docker service start.
- If Apptainer/Singularity is absent, package-manager installation is
  best-effort. Managed HPC systems and distributions without a configured
  package may require an administrator-provided runtime.

### macOS

```bash
bash scripts/install/install_megflow_macos.sh
bash scripts/install/install_megflow_macos.sh 1.0.0
```

Notes:
- This script is macOS-only and exits early on non-macOS systems.

### Windows PowerShell

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install\install_megflow_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\install\install_megflow_windows.ps1 -ImageTag 1.0.0
```

## Troubleshooting

- Docker CLI exists but `docker info` fails:
  - Start Docker Desktop (macOS/Windows), or ensure Docker daemon is running (Linux).
  - Confirm current user has permission to run Docker commands.
- Linux server/HPC without Docker daemon:
  - Use Apptainer mode directly:
    - `bash scripts/install/install_megflow_linux.sh <tag> apptainer`
- Package installation fails:
  - Re-run with proper privileges (`root` or `sudo`) and check network/package mirror access.
- Image tag issues:
  - Make sure the tag is not empty and exists in `cplmeg/megflow`.
