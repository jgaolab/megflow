
# MEGPrep: A Scalable and Reproducible Pipeline for Large-Scale MEG Preprocessing

[![Documentation Status](https://readthedocs.org/projects/megprep/badge/?version=latest)](https://megprep.readthedocs.io/)
[![Docker Pulls](https://img.shields.io/docker/pulls/cmrlab/megprep)](https://hub.docker.com/r/cmrlab/megprep)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

**MEGPrep** is a fully automated preprocessing pipeline for MEG (Magnetoencephalography) data, built on the **MNE-Python** framework and leveraging the power of **Nextflow**.

It is specifically designed to address the challenges of large-scale MEG data processing with a strong emphasis on reproducibility, efficiency, and user-friendliness in various research environments.

---

## 🌟 Key Features

### 🛡️ Reliability and Robustness
Standardized environments through containerization (**Docker** and **Singularity**) guarantee consistent results across computational setups. This minimizes variability and ensures reproducibility across different systems, facilitating cross-subject and cross-site studies.

### ⚡ Acceleration and Parallelization
By using the **Nextflow** framework, MEGPrep dramatically accelerates the pipeline. It is optimized for high parallelization, capable of managing heavy workloads and significantly speeding up data processing through concurrent execution of tasks.

### 🧩 Modularity and Integrability
Designed with modularity in mind, enabling users to customize workflows easily. It integrates seamlessly with various libraries (including `mne-python`) for enhanced processing and analysis.

### 🤖 Automated Processes
Streamlines preprocessing with automated detection processes to reduce manual intervention:
*   Automatic Artifacts Rejection
*   ICA (Independent Component Analysis) Automatic Detection
*   Auto-coregistration

### 📊 Interoperability and Standards
Includes an interactive reporting feature based on **Streamlit**, allowing users to visualize quality control metrics at each step and receive alerts for anomalies.

### ⚙️ Parameter Configuration
Offers an easy-to-use configuration system. Researchers can adapt the preprocessing pipeline to unique datasets without complex coding.

---

## 🚀 Installation

MEGPrep is officially distributed as a Docker container. We recommend using the
containerized installation workflow whenever possible, because it provides the
most reproducible environment and avoids most local dependency conflicts.

If Docker cannot be installed, the Docker daemon is unavailable, or the container
image cannot be pulled in your network environment, you can try the local
development installation workflow instead. The local workflow installs MEGPrep
from source without relying on a container image. Use this option cautiously,
because differences in system libraries, package versions, and local software
environments may lead to behavior that differs from the containerized workflow.

### Recommended: Containerized One-Click Install

The scripts under `scripts/install/` install or reuse a container runtime, pull
`cmrlab/megprep:<version>`, and verify the image by running the MEGPrep help
command.

```bash
# Linux
bash scripts/install/install_megprep_linux.sh
bash scripts/install/install_megprep_linux.sh 0.0.3

# macOS
bash scripts/install/install_megprep_macos.sh
bash scripts/install/install_megprep_macos.sh 0.0.3

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File .\scripts\install\install_megprep_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\install\install_megprep_windows.ps1 -ImageTag 0.0.3
```

On Linux, the installer can use Docker or Apptainer/Singularity:

```bash
bash scripts/install/install_megprep_linux.sh 0.0.3 docker
bash scripts/install/install_megprep_linux.sh 0.0.3 apptainer
```

For more details, see `scripts/install/README.md`.

### Alternative: Local Development One-Click Install

The scripts under `scripts/install-dev/` provide a source-based local
installation path for Linux environments where container installation is not
available or image pulling is blocked. This workflow installs or reuses Conda,
Nextflow, FreeSurfer, and MEGPrep source dependencies in a local installation
directory.

```bash
bash scripts/install-dev/install_megprep_dev_linux.sh
bash scripts/install-dev/install_megprep_dev_linux.sh --install-dir /data/megprep-dev
bash scripts/install-dev/install_megprep_dev_linux.sh --no-freesurfer
```

After installation, load the generated environment:

```bash
source <install-dir>/env.sh
```

For more details, see `scripts/install-dev/README.md`.

### Manual Docker Pull

If you prefer to install manually, install Docker following the
[Docker official documentation](https://docs.docker.com/get-docker/) and pull the
image directly:

```bash
docker pull cmrlab/megprep:<version>
```

*(Replace `<version>` with the specific version tag, e.g., `0.0.3` or `latest`)*

---

## 💻 Usage

### Basic Command Structure
```bash
docker run --rm -it cmrlab/megprep:<version> [nextflow_options]
```

### Pipeline steps

The file [`nextflow/meg_anat_pipeline_for_docker.nf`](nextflow/meg_anat_pipeline_for_docker.nf) is controlled by **`params.steps`** in the config, or by **`--steps`** on the command line. The default in [`nextflow.config`](nextflow/nextflow.config) is **`meg_all`**.

| Primary `steps` | What it does |
| :--- | :--- |
| `meg_all` | **Default.** Full MEG processing (import → basic preprocessing → artifacts → ICA → epochs → covariance → coregistration → forward → source) using the existing **`fs_subjects_dir`**; does **not** run the T1/FreeSurfer/DeepPrep structural pipeline. |
| `all` | Run **structural imaging** (T1 import, recon, BEM) **and** the full MEG chain in one go. |
| `anatomy` | **Structural imaging only** (no MEG). |
| `meg_artifacts` | MEG up to **artifact detection** (after basic preprocessing), then the static HTML QC report. |
| `meg_ica` | Through **ICA** (fit, label, apply), then report. |
| `meg_epochs` | Through **epoching**, then report. |
| `report` | Regenerate the **static HTML** report only (scans existing `preproc_dir`; no MEG or MRI processes). |

**Aliases** (same effect as the long name): `meg` → `meg_all`, `artifacts` → `meg_artifacts`, `ica` → `meg_ica`, `epochs` → `meg_epochs`.

**Optional modifiers** (comma-separated, e.g. `--steps 'meg_epochs,skip_ica'`; first token is the mode above):

| Modifier | When it is valid | Effect |
| :--- | :--- | :--- |
| `skip_ica` | Only with **`meg_epochs`** | Skips ICA; builds epochs from `*_preproc-raw` files produced by basic preprocessing. Not available for `all` / `meg_all` (downstream forward/source expect ICA-clean raw). |
| `with_anatomy` | `meg_artifacts`, `meg_ica`, or `meg_epochs` (not `meg_all`) | Runs the structural pipeline **before** the selected MEG milestone in the same run. |

**Note:** `do_fs` and `do_only_anatomy` are legacy switches. The Nextflow workflow is now driven by **`steps`**; use `--steps anatomy`, `--steps all`, or `--steps meg_all` instead of editing those legacy flags.

ICA per-component explained variance is optional and disabled by default:
set `ica_compute_explained_variance = true` in the Nextflow config, or pass
`--ica_compute_explained_variance true`, when you want EVAR values in ICA
figure filenames and report captions. When disabled, ICA fitting, labeling,
interactive review, and static reports still work; EVAR-dependent rule checks
are skipped.

#### Basic preprocessing

The table above uses **basic preprocessing** for the first MEG-only signal steps (after import). They are defined in **`params.preproc_config`**; the repository default in [`nextflow/nextflow.config`](nextflow/nextflow.config) is:

- **Band-pass filter** (0.5–125 Hz, IIR Butterworth)
- **Notch filter** (50 Hz and 100 Hz)
- **Resample** (250 Hz sampling rate)

Optional **Maxwell / tSSS** for Elekta-style data is supported in the same YAML but commented out by default; enable it there and supply calibration paths when needed. For **CTF** runs, if a matching `*_headshape.pos` is present next to the raw file, **digitization from the headshape** is merged into the preprocessed FIF after those steps.

**Examples (local Nextflow):**

```bash
# Default: full MEG only, use existing FreeSurfer/DeepPrep subjects dir
nextflow run megprep/nextflow/meg_anat_pipeline_for_docker.nf \
  -c megprep/nextflow/nextflow.config

# Structural + MEG end-to-end
nextflow run megprep/nextflow/meg_anat_pipeline_for_docker.nf \
  -c megprep/nextflow/nextflow.config --steps all

# MRI only
nextflow run megprep/nextflow/meg_anat_pipeline_for_docker.nf \
  -c megprep/nextflow/nextflow.config --steps anatomy

# Rebuild static HTML report only
nextflow run megprep/nextflow/meg_anat_pipeline_for_docker.nf \
  -c megprep/nextflow/nextflow.config --steps report

# Optional: two-step “anatomy first, then MEG from artifacts”
nextflow run ... --steps anatomy
nextflow run ... --steps meg_artifacts -resume
```

Set `params.steps` in your `nextflow.config` for a project default; override with `--steps` when needed.

### Workflow provenance in the static HTML report

Every run writes `preprocessed/logs/megprep_run_manifest.json`. The static HTML report reads this manifest to draw the dataset-level **Workflow** diagram and to show the run mode, runtime, input data, paths, and only the parameters relevant to the selected stage.

The report also bundles a plain-text config snapshot at `static_html_report/data/nextflow.config.txt` when one can be found. The workflow first snapshots the actual Nextflow config files reported by `workflow.configFiles`; this covers custom local `-c /path/to/config` runs and Docker runs that use `/program/nextflow/run_nextflow.config`. It then falls back to `nextflow.config` / `run_nextflow.config` under the launch directory or project directory.

For `--steps report`, MEGPrep regenerates only the static report. If an earlier `megprep_run_manifest.json` exists, the report build uses it to keep the previous pipeline workflow in the diagram and marks the current run as report-only in the generated report bundle, but it restores the original `preprocessed/logs/megprep_run_manifest.json` afterward so the preprocessing provenance is not overwritten.

Subject pages also read the Nextflow `trace.txt` when available. `Task Details`
lists matched tasks in a collapsed table, while `Task Failure Details` appears
only when a failed or ignored task is detected and includes packaged
`.command.err`, `.command.log`, and `.command.out` excerpts. The amount of
task log content copied into the static report is controlled by
`static_task_log_mode`:

- `all-command-log` (default): copy `.command.err`, `.command.log`, and `.command.out` for failed or ignored tasks, and also copy `.command.log` for successful tasks.
- `failed`: copy `.command.err`, `.command.log`, and `.command.out` only for failed or ignored tasks when you want a smaller report package.
- `none`: do not copy `.command*` logs into the static report.

You can set this in `nextflow.config` or override it for a run:

```bash
nextflow run ... --static_task_log_mode all-command-log
docker run ... cmrlab/megprep:<tag> ... --static_task_log_mode all-command-log
```

Artifact Review in the static report packages one overview plot per subject by
default. The displayed window is controlled by
`static_artifact_overview_duration` (default: `200.0` seconds). Prefer setting
this value in the active Nextflow config file, for example
`nextflow.config` for source-code runs or `nextflow_for_docker.config` for
Docker builds, so static report behavior stays reproducible with the saved
config snapshot.

### Cohort mode: multiple datasets under one root

For a directory that contains many independent MEG datasets, use **`--cohort`**.
MEGPrep treats each immediate child directory as one dataset and runs the same
native dataset-tuple DAG used by single-dataset runs. Cohort mode isolates each
dataset's outputs, then builds a cohort-level static report that links back to
each dataset report. Nextflow shows the real process tasks for all datasets in
one run.
In cohort mode, FreeSurfer/DeepPrep outputs are also isolated by dataset under
`<fs_subjects_dir>/<dataset_name>` so repeated MRI subject IDs such as `sub-01`
do not overwrite each other.

```bash
docker run --rm -it \
  -v /data/liaopan/datasets:/input \
  -v /data/liaopan/megprep_cohort:/output \
  -v /data/liaopan/smri:/smri \
  -v /data/liaopan/megprep/license.txt:/fs_license.txt \
  cmrlab/megprep:0.0.3 \
  -i /input -o /output \
  --fs_license_file /fs_license.txt --fs_subjects_dir /smri \
  --steps meg_artifacts \
  --cohort
```

Outputs are organized as:

- `/output/datasets/<dataset_name>/static_html_report/index.html` for the existing dataset-level report.
- `/smri/<dataset_name>/` for that dataset's FreeSurfer/DeepPrep subject outputs when `--fs_subjects_dir /smri` is used.
- `/output/cohort_static_html_report/index.html` for the cross-dataset cohort dashboard.

For `--steps all` and anatomy-enabled modes, each dataset's T1 input defaults to
the same child dataset directory as the MEG input. If you pass `--t1_dir` and it
contains matching child directories, MEGPrep uses `--t1_dir/<dataset_name>` for
each run; otherwise it uses the provided `--t1_dir` for all datasets.

Use a milestone such as `--steps meg_artifacts` or `--steps meg_ica` for a quick
first pass across many public datasets, then resume selected datasets with a
deeper step when needed.

Dataset tuple channels and Nextflow's normal process parallelism handle
scheduling in one DAG. Tune process-level `maxForks`, CPU, and memory settings
in the Nextflow config according to available compute and I/O capacity.

### Using pipeline steps with Docker

The image entrypoint is [`nextflow/run_for_docker.sh`](nextflow/run_for_docker.sh) (installed in the container as `/program/nextflow/run.sh`). **Step selection uses the same values** as in the [Pipeline steps](#pipeline-steps) table above.

- **After the image name**, pass **`-s`** / **`--steps`** (forwarded to Nextflow as `--steps`). If you omit it, the workflow uses **`params.steps`** from the config (default in the baked-in image config is **`meg_all`**).
- **Modifiers** that contain commas must be **quoted for the shell**, e.g. `--steps 'meg_epochs,skip_ica'`.
- **Cohort mode** uses `--cohort`; in that mode `-i` / `--input` should point to a directory whose immediate children are datasets, and `--fs_subjects_dir` is used as the base directory for per-dataset FreeSurfer outputs.
- You can instead set **`steps = '...'`** inside the Nextflow file you mount at **`/program/nextflow/nextflow.config`**; a container **`--steps`** / **`-s`** argument **overrides** that for the run.
- **`-s`** here is the **MEGPrep** flag (input path is **`-i`**), not Docker’s **`-i`** (interactive). Typical pattern: `docker run ... cmrlab/megprep:<tag> -i /input -o /output ... --steps all`.
- The Docker entrypoint copies the mounted config to `/program/nextflow/run_nextflow.config`, applies command-line path overrides, runs Nextflow with that file, then copies it to `<output>/nextflow.config` and snapshots it into `preprocessed/logs/` for the static HTML report.
- The Docker entrypoint starts as root only long enough to prepare mounted output permissions, then drops to the host UID/GID inferred from `/input`; report-only runs that only mount `/output` infer ownership from `/output`.

**Docker output ownership**

You do **not** need to add Docker's `--user` flag or pre-create the output directory. If the host output path does not exist, Docker may create it as `root:root` before the container starts; MEGPrep fixes that at startup, then runs the pipeline as the host user inferred from `/input`. For interactive report runs such as `docker run ... -v /data/preprocessed:/output cmrlab/megprep:<version> -r`, ownership is inferred from `/output`. Outputs should therefore be writable by the submitting user, not owned by root.

If neither `/input` nor `/output` is owned by the user who should own generated files, pass the desired IDs explicitly:

```bash
docker run --rm -it \
  -e LOCAL_UID="$(id -u)" -e LOCAL_GID="$(id -g)" \
  -v /data/bids:/input -v /data/out:/output \
  cmrlab/megprep:<version> \
  -i /input -o /output
```

**Examples:**

```bash
# Full MEG only (explicit; same as default meg_all when config unchanged)
docker run --rm -it \
  -v /data/bids:/input -v /data/out:/output -v /data/smri:/smri \
  -v /data/license.txt:/fs_license.txt \
  cmrlab/megprep:0.0.3 \
  -i /input -o /output \
  --fs_license_file /fs_license.txt --fs_subjects_dir /smri \
  --steps meg_all

# Structural MRI + full MEG in one container run
docker run --rm -it \
  -v /data/bids:/input -v /data/out:/output -v /data/smri:/smri \
  -v /data/license.txt:/fs_license.txt \
  cmrlab/megprep:0.0.3 \
  -i /input -o /output \
  --fs_license_file /fs_license.txt --fs_subjects_dir /smri \
  --steps all

# Static HTML report only (existing preproc under preproc_dir)
docker run --rm -it \
  -v /data/bids:/input -v /data/out:/output -v /data/smri:/smri \
  cmrlab/megprep:0.0.3 \
  -i /input -o /output --fs_subjects_dir /smri \
  --steps report
```

### Main Options

| Option | Description |
| :--- | :--- |
| `-c`, `--config` | Specify the Nextflow config file (default: `nextflow.config`) |
| `-i`, `--input` | Specify the input directory |
| `-o`, `--output` | Specify the output directory (including report results) |
| `-s`, `--steps` | **Nextflow (`meg_anat_pipeline_for_docker.nf`):** sets `params.steps` (e.g. `all`, `meg_all`, `anatomy`, `report`). With **Docker**, pass this **after the image name**; see [Using pipeline steps with Docker](#using-pipeline-steps-with-docker). Same semantics as [Pipeline steps](#pipeline-steps). |
| `-r`, `--view-report` | Run Streamlit to view the report (does not run Nextflow) |
| `--cohort` | Treat the input directory as a collection of datasets, run each child through the native dataset tuple DAG, and generate a cohort-level static report |
| `--static_task_log_mode` | Static report task log bundling mode: `all-command-log` (default), `failed`, or `none` |
| `--static_artifact_overview_duration` | Seconds represented by the single Artifact Review overview plot in the static report; default `200.0` |
| `--fs_license_file` | Specify the FreeSurfer license file path |
| `--fs_subjects_dir` | Specify the FreeSurfer `SUBJECTS_DIR` containing processed T1 results |
| `--t1_dir` | Specify the T1 image directory |
| `--t1_input_type` | Specify the T1 input type |
| `--t1_dicom_series_glob` | Optional relative glob for selecting DICOM series directories under each T1 DICOM root, e.g. `*T1*` or `*mprage*` |
| `--resume` | Resume the previous run (Nextflow option) |

### Example: Running a Full Pipeline
Here is a comprehensive example mapping input/output volumes and license files:

```bash
docker run --rm -it \
    -v /data/datasets/SMN4Lang:/input \
    -v /data/datasets/SMN4Lang/preprocessed:/output \
    -v /data/datasets/SMN4Lang/smri:/smri \
    -v /data/megprep/license.txt:/fs_license.txt \
    -v /data/megprep/nextflow/nextflow.config:/program/nextflow/nextflow.config \
    cmrlab/megprep:0.0.3 \
    -i /input \
    -o /output \
    --fs_license_file /fs_license.txt \
    --fs_subjects_dir /smri \
    --resume
```

For MEGPrep, the default **`steps`** is **`meg_all`** (MEG only, using existing `fs_subjects_dir`). To run **structural MRI + full MEG** together, use **`--steps all`** (or **`-s all`**) on the **`docker run ...`** command line, or set **`steps = 'all'`** in the mounted config. See [Using pipeline steps with Docker](#using-pipeline-steps-with-docker).

---

## 📈 Quality Control Reports

MEGPrep generates interactive quality control reports via Streamlit.

### How to View Reports
Use the `-r` flag and map port `8501`:

```bash
docker run --rm -it -p 8501:8501 -v /data/liaopan/datasets/SMN4Lang/g:/output cmrlab/megprep:<version> -r
```

**Access via browser:**
👉 `http://<server_ip>:8501` (or `http://localhost:8501` if running locally)

---

## 🐛 Bug Reports & Feedback

If you encounter any bugs, anomalies, or have suggestions for improvements, please report them via the **GitHub Issues** page.

When reporting a bug, please include:
1.  **System Information**: OS version, Docker version.
2.  **Command Used**: The exact command line you executed.
3.  **Logs**: The relevant part of the error log or traceback (please use code blocks).
4.  **Description**: A clear description of what you expected to happen versus what actually happened.

👉 [Report an Issue](https://github.com/liaopan/megprep/issues)

---

## 🛠️ Development

We welcome contributions to MEGPrep! If you want to contribute code or improve documentation, please follow these steps:

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/liaopan/megprep.git
    cd megprep
    ```

2. **Environment Setup:**
    If you plan to develop or run the pipeline locally (outside Docker), you must install Nextflow.

    **Prerequisites:**
    *   **System**: Any POSIX-compatible system (Linux, macOS, etc.), or Windows through WSL.
    *   **Dependencies**: Bash 3.2+ and **Java 17** (up to 23).

    **Installation:**
    Please refer to the [Nextflow Official Documentation](https://www.nextflow.io/docs/latest/install.html).

    If you use SDKMAN (recommended), initialize it:
    ```bash
    source "$HOME/.sdkman/bin/sdkman-init.sh"
    ```

    **Configuration:**
    Ensure the Nextflow binary is in your PATH.
    *   Common location: `$HOME/.local/bin/nextflow`

    **Useful Nextflow Developer Commands:**

    *   **Check Installation**:
    ```bash
    nextflow info
    ```

    *   **Run with Trace** (creates an execution trace file):
    ```bash
    nextflow run <script.nf> -with-trace
    ```

3.  **Build Docker Image Locally (Optional):**
    If you modified the Dockerfile or dependencies, you can build the image manually using Docker or the provided helper script.

    **Using the build script (Recommended):**
    ```bash
    bash build_megprep.sh
    ```

    **Using Docker directly:**
    ```bash
    docker build -t megprep:local -f megprep.Dockerfile .
    ```

4.  **Submit a Pull Request:**
    *   Fork the repository.
    *   Create a new branch for your feature or fix.
    *   Commit your changes and push to your fork.
    *   Submit a Pull Request to the `main` branch.
