
# MEGFlow: A Scalable and Reproducible Pipeline for Large-Scale MEG Preprocessing

[![Documentation Status](https://readthedocs.org/projects/megflow-docs/badge/?version=latest)](https://megflow-docs.readthedocs.io/)
[![Docker Pulls](https://img.shields.io/docker/pulls/cmrlab/megflow)](https://hub.docker.com/r/cmrlab/megflow)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

**MEGFlow** is a preprocessing pipeline for MEG (Magnetoencephalography) data, built on **MNE-Python** and **Nextflow**.

It supports containerized execution, staged workflows, quality-control reports, and corpus-scale processing for research environments where reproducibility and scalable execution are required.

---

## 📌 Key Features

### 🐳 Reproducible Runtime
Containerized environments through **Docker** and **Singularity** reduce runtime differences across computational setups and support cross-subject or cross-site studies.

### ⚡ Parallel Execution
MEGFlow uses **Nextflow** to schedule independent tasks concurrently and manage large preprocessing workloads.

### 🔗 Modular Workflow
The workflow is organized into configurable stages so users can run the full pipeline or stop at selected milestones.

### 🔎 Automated Detection Steps
MEGFlow includes automated steps that reduce repeated manual work:
*   Artifact rejection
*   ICA (Independent Component Analysis) component detection
*   Coregistration

### 📐 Quality Control Reports
The reporting tools summarize quality-control metrics for each processing stage and flag potential anomalies.

### ⚙️ Parameter Configuration
Configuration files expose dataset paths, preprocessing settings, workflow steps, and report options without requiring changes to pipeline code.

---

## `❯_` Installation

MEGFlow is officially distributed as a Docker container. We recommend using the
containerized installation workflow whenever possible, because it provides the
most reproducible environment and avoids most local dependency conflicts.

If Docker cannot be installed, the Docker daemon is unavailable, or the container
image cannot be pulled in your network environment, you can try the local
development installation workflow instead. The local workflow installs MEGFlow
from source without relying on a container image. Use this option cautiously,
because differences in system libraries, package versions, and local software
environments may lead to behavior that differs from the containerized workflow.

### Recommended: Containerized Install

The scripts under `scripts/install/` install or reuse a container runtime, pull
`cmrlab/megflow:<version>`, and verify the image by running the MEGFlow help
command.

```bash
# Linux
bash scripts/install/install_megflow_linux.sh
bash scripts/install/install_megflow_linux.sh 1.0.0

# macOS
bash scripts/install/install_megflow_macos.sh
bash scripts/install/install_megflow_macos.sh 1.0.0

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File .\scripts\install\install_megflow_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\install\install_megflow_windows.ps1 -ImageTag 1.0.0
```

On Linux, the installer can use Docker or Apptainer/Singularity:

```bash
bash scripts/install/install_megflow_linux.sh 1.0.0 docker
bash scripts/install/install_megflow_linux.sh 1.0.0 apptainer
```

For more details, see `scripts/install/README.md`.

### Alternative: Local Development Install

The scripts under `scripts/install-dev/` provide a source-based local
installation path for Linux environments where container installation is not
available or image pulling is blocked. This workflow installs or reuses Conda,
Nextflow, FreeSurfer, and MEGFlow source dependencies in a local installation
directory.

```bash
bash scripts/install-dev/install_megflow_dev_linux.sh
bash scripts/install-dev/install_megflow_dev_linux.sh --install-dir /data/megflow-dev
bash scripts/install-dev/install_megflow_dev_linux.sh --no-freesurfer
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
docker pull cmrlab/megflow:<version>
```

*(Replace `<version>` with the specific version tag, e.g., `1.0.0` or `latest`)*

---

## 💻 Usage

### Basic Command Structure
```bash
docker run --rm -it cmrlab/megflow:<version> [nextflow_options]
```

### Pipeline steps

The file [`nextflow/megflow.nf`](nextflow/megflow.nf) is controlled by **`params.megflow.defaults.steps`** plus optional dataset- or recording-level `steps` overrides in [`nextflow.config`](nextflow/nextflow.config). The default is **`meg_all`**. The Docker entrypoint also accepts `--steps` and writes the corresponding `params.megflow` runtime override.

| Primary `steps` | What it does |
| :--- | :--- |
| `meg_all` | **Default.** Full MEG processing (import → basic preprocessing → artifacts → ICA → epochs → covariance → coregistration → forward → source) using the existing **`fs_subjects_dir`**; does **not** run the T1/FreeSurfer/DeepPrep structural pipeline. |
| `all` | Run **structural imaging** (T1 import, recon, BEM; or Pseudo-MRI fallback when configured) **and** the full MEG chain in one go. |
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

**Note:** `do_fs`, `do_only_anatomy`, and top-level `params.steps` are no longer used by the Nextflow workflow. Put `steps` under `params.megflow.defaults`, a dataset profile, or a recording profile.

ICA per-component explained variance is optional and disabled by default:
set `params.megflow.defaults.ica.compute_explained_variance = true` when you want EVAR values in ICA
figure filenames and report captions. When disabled, ICA fitting, labeling,
interactive review, and static reports still work; EVAR-dependent rule checks
are skipped.

#### Basic preprocessing

The table above uses **basic preprocessing** for the first MEG-only signal steps (after import). They are defined in **`params.megflow.defaults.preproc`**; the repository default in [`nextflow/nextflow.config`](nextflow/nextflow.config) is:

- **Band-pass filter** (1–100 Hz, IIR Butterworth)
- **Notch filter** (50 Hz and 100 Hz)
- **Resample** (250 Hz sampling rate)

Optional **Maxwell / tSSS** for MEGIN/Elekta data is configured as an OSL
`maxwell_filter` stage; a positive `st_duration` enables tSSS. Use the
three-level [`nextflow_maxwell_tsss_example.config`](nextflow/nextflow_maxwell_tsss_example.config)
and the [configuration reference](docs/source/reference/configuration_preprocessing.rst#maxwell-filtering-and-tsss)
for calibration, cross-talk, ordering, bad-channel, and dataset/recording
override requirements. Maxwell/tSSS remains disabled in the shared defaults.
For **CTF** runs, if a matching `*_headshape.pos` is present next to the raw
file, **digitization from the headshape** is merged into the preprocessed FIF
after those steps.

For corpus runs with mixed line-noise frequencies, keep the default preprocessing shared and override only the relevant dataset profile:

```groovy
params.megflow.datasets = [
  US_60Hz_Dataset: [
    preproc: [steps: [
      [filter: [l_freq: 1.0, h_freq: 100.0, method: "iir", iir_params: [order: 5, ftype: "butter"]]],
      [notch_filter: [freqs: "60"]],
      [resample: [sfreq: 250]]
    ]]
  ]
]
```

NormMEG-QC has its own lightweight preprocessing setting,
`params.megflow.defaults.megqc.preproc`, so scoring stays aligned with the
configured reference space. The NormMEG-QC band-pass filter and sampling rate
are fixed at 1-100 Hz and 250 Hz for reference alignment; do not change those
values or the NMDQ score will no longer be comparable to the normative
reference. The scorer carries the same sequence internally, so an omitted or
empty `megqc.preproc` list still uses the reference defaults. Use
`megqc.meg_vendor = "auto"` by default so each recording is matched to the
appropriate reference device family. Vendor values are case-insensitive; the
examples use lowercase for consistency. If a corpus contains datasets whose
vendor is known and should be fixed explicitly, set it in the dataset profile:

```groovy
params.megflow.datasets = [
  CTF_Dataset: [megqc: [meg_vendor: "ctf"]],
  OPM_Artifacts: [megqc: [meg_vendor: "opm"]]
]
```

NormMEG-QC parallelism is controlled by Nextflow resources, not a separate
`megqc_n_jobs` config value. The `score_meg_quality` process passes `task.cpus`
to the scorer; tune it with the global `process.cpus` setting or a process
override:

```groovy
process {
  withName: score_meg_quality {
    cpus = 4
  }
}
```

To use the NMDQ score as a quality gate, raise `megqc.min_score`. Recordings below
that score are kept in the report but skipped for downstream MEG processing:

```groovy
params.megflow.defaults.megqc.enabled = true
params.megflow.defaults.megqc.min_score = 70.0    // processing gate
params.megflow.defaults.megqc.alarm_score = 60.0  // report warning only
```

Artifact review plots can use `artifacts.meg_vendor: auto`; MEGFlow will
infer the plotting vendor from channel names or raw metadata for each dataset.
DeepReject artifact detection is configured inside `artifacts.deepreject` and
is enabled by default in the bundled configs. BadChnNet first combines five-fold
predictions to identify bad channels. Those channels are then masked before
BadSegNet combines five-fold window probabilities and creates
`BAD_deepreject` intervals. MEGFlow merges these results with the other enabled
detectors, writes detector provenance to `*_bad_channels_description.json`, and
writes detailed inference provenance to `deepreject_summary.json`. The Docker
image includes the Torch runtime and bundled model weights; non-Docker local
environments must provide PyTorch. See the
[DeepReject reference](https://megflow-docs.readthedocs.io/en/latest/reference/deepreject.html)
for thresholds, modes, formulas, and output interpretation.

**Examples (local Nextflow):**

```bash
# Default: full MEG only, use existing FreeSurfer/DeepPrep subjects dir
nextflow run nextflow/megflow.nf \
  -c nextflow/nextflow.config \
  -resume

# Complete WAND + SMN4Lang + MEG-MASC example with per-dataset settings
bash run_MultiDatasets_sourcecode.sh

# To change the stage, set params.megflow.defaults.steps in the config:
#   params.megflow.defaults.steps = "all"
#   params.megflow.defaults.steps = "anatomy"
#   params.megflow.defaults.steps = "report"
```

Set `params.megflow.defaults.steps` in your `nextflow.config` for a project default. For Docker runs, the entrypoint's `--steps` option writes this override into the runtime config.

### Validation

Run the same validation gates used by GitHub Actions from an activated MEGFlow
environment:

```bash
export MEGFLOW_NEXTFLOW="$(command -v nextflow)"
bash scripts/validation/run_validation.sh all
```

Use `routing` for Nextflow 24.10.3 DAG, resume, failure, report, and config
contracts, or `scientific` for real synthetic MNE/OSL filtering, epochs,
covariance, source-call, MEGQC, DeepReject-input, and report tests. Requested
gates fail when dependencies are missing, no tests are discovered, or any test
is skipped. GitHub runs both gates for every push and pull request; its pinned
lightweight scientific dependencies are in `requirements_validation.txt`.

### Resume and interactive edits

MEGFlow relies on Nextflow `-resume` for normal task caching. Unchanged tasks
reuse the work cache, while input, script, or configuration changes invalidate
only the affected task chain.

Sidecar hashes are used for downstream invalidation. For example, editing
bad-channel/bad-segment files changes the hash that ICA receives, so downstream
tasks recompute even when the upstream artifact-detection task itself is cached.
Editable sidecars are hashed from their published locations, so interactive
report edits are preserved. Required published outputs also have task-local
cache guards. If a QC, preprocessing, artifact, ICA, epoch, covariance,
coregistration, forward, source, or anatomy result is deleted, a resumed run
invalidates its producing task and restores that output while unrelated
recordings remain cached. Static reports do not use resume cache and are
regenerated on every completed or lenient run.

### Workflow provenance in the static HTML report

Every run writes `preprocessed/logs/megflow_run_manifest.json`. The static HTML report reads this manifest to draw the dataset-level **Workflow** diagram and to show the run mode, runtime, input data, paths, and only the parameters relevant to the selected stage.

The report also bundles a plain-text config snapshot at
`static_html_report/data/nextflow.config.txt` when one can be found. It checks
`preprocessed/logs/`, the dataset output root, and the manifest launch directory
for `run_nextflow.config` or `nextflow.config`. Docker runs copy their runtime
config to `<output>/nextflow.config`, so it is normally available there; custom
source launchers should retain their project config alongside the output when a
portable snapshot is required.

For `--steps report`, MEGFlow regenerates only the static report. If an earlier `megflow_run_manifest.json` exists, the report build uses it to keep the previous pipeline workflow in the diagram and marks the current run as report-only in the generated report bundle, but it restores the original `preprocessed/logs/megflow_run_manifest.json` afterward so the preprocessing provenance is not overwritten.

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
docker run ... cmrlab/megflow:<tag> ... --static_task_log_mode all-command-log
```

Artifact Review in the static report packages one overview plot per subject by
default. The displayed window is controlled by
`static_artifact_overview_duration` (default: `200.0` seconds). Prefer setting
this value in the active Nextflow config file, for example
`nextflow.config` for source-code and Docker builds, so static report behavior stays reproducible with the saved
config snapshot.

### Corpus profiles: multiple datasets under one root

For a directory that contains many independent MEG datasets, set
`params.megflow.corpus_root` and optionally narrow it with
`dataset_include` / `dataset_exclude`. MEGFlow treats each immediate child
directory as one dataset, isolates each dataset's outputs under
`<output_dir>/datasets/<dataset_name>`, and builds a corpus-level static report
that links back to each dataset report.

```groovy
params.megflow.corpus_root = "/data/corpus"
params.megflow.dataset_include = ["WAND_Extracted", "SMN4Lang", "MEG-MASC"]
params.megflow.datasets = [
  WAND_Extracted: [
    fs_subjects_dir: "/data/corpus/WAND_Extracted/smri",
    meg_import: [task: ["visual"], subject_id: "first:10"],
    megqc: [meg_vendor: "ctf"],
    epochs: [event_source: "find_events", find_events: [stim_channel: "UPPT001"]]
  ],
  SMN4Lang: [
    fs_subjects_dir: "/data/corpus/SMN4Lang_smri",
    meg_import: [task: ["RDR"], subject_id: "first:10"],
    megqc: [meg_vendor: "elekta"],
    epochs: [event_source: "event_file", event_time_shift_sec: -10.6105]
  ],
  "MEG-MASC": [
    dataset_format: "bids",
    file_suffix: ".con",
    meg_import: [session_id: ["0"], task: ["0"], subject_id: "first:10"],
    megqc: [meg_vendor: "kit"],
    artifacts: [meg_vendor: "kit", deepreject: [mode: "lenient"]]
  ]
]
```

The runnable [`nextflow/nextflow_multi_dataset_demo.config`](nextflow/nextflow_multi_dataset_demo.config)
expands this pattern into complete defaults, event and covariance definitions,
digitization, coregistration, source labels, and process concurrency limits for
all three datasets.

Outputs are organized as:

- `/output/datasets/<dataset_name>/static_html_report/index.html` for the existing dataset-level report.
- `/output/smri/<dataset_name>/` for default dataset-isolated FreeSurfer/DeepPrep outputs when anatomy processing is enabled, or `<fs_subjects_root>/<dataset_name>/` when `params.megflow.fs_subjects_root` is set.
- `/output/corpus_static_html_report/index.html` for the cross-dataset corpus dashboard.
- `/output/corpus_static_html_report/nextflow/` for the corpus-level Nextflow report, timeline, trace, and driver log.

Use a milestone such as `meg_artifacts` or `meg_ica` for a quick first pass
across many public datasets, then resume selected datasets with a deeper step
when needed. Dataset-specific line-noise, vendor, epoch, covariance, and source
settings belong in the matching dataset profile. Task-specific settings belong
in that dataset's `recordings` profiles.

Dataset tuple channels and Nextflow's normal process parallelism handle
scheduling in one DAG. Tune process-level `maxForks`, CPU, and memory settings
in the Nextflow config according to available compute and I/O capacity.

The main config includes `local`, `docker`, `slurm`, `singularity`, `lenient`,
`strict`, and `debug` execution profiles. The `docker` profile containerizes the
complete source-launched workflow in the MEGFlow image; DeepPrep never launches
a nested container. Single-dataset runs write Nextflow observability
files under `static_html_report/nextflow/`; corpus runs use
`corpus_static_html_report/nextflow/`. MEGFlow launch wrappers pass the matching
`nextflow/nextflow.log` path through Nextflow's top-level `-log` option. Slurm
partition, account, QoS, work directory, queue size, and SIF settings are read
from `MEGFLOW_SLURM_*`, `MEGFLOW_SIF`, and `MEGFLOW_SINGULARITY_*` environment
variables. Source-launched Docker runs use `MEGFLOW_DOCKER_IMAGE` and
`MEGFLOW_DOCKER_RUN_OPTIONS`; see the configuration documentation for the
complete list and FreeSurfer license mount example.

### Using pipeline steps with Docker

The image entrypoint is [`nextflow/run_for_docker.sh`](nextflow/run_for_docker.sh) (installed in the container as `/program/nextflow/run.sh`). **Step selection uses the same values** as in the [Pipeline steps](#pipeline-steps) table above.

- **After the image name**, pass **`-s`** / **`--steps`**. The entrypoint writes this into the runtime `params.megflow` profile. If you omit it, the workflow uses **`params.megflow.defaults.steps`** from the config.
- **Modifiers** that contain commas must be **quoted for the shell**, e.g. `--steps 'meg_epochs,skip_ica'`.
- **Corpus mode** uses `--corpus`; in that mode `-i` / `--input` points to a directory whose immediate children are datasets, and `--fs_subjects_dir` is used as the base directory for per-dataset FreeSurfer outputs. Named profiles, `dataset_include`, `dataset_exclude`, and dataset-level module overrides from the mounted config are preserved.
- You can instead set **`params.megflow.defaults.steps = '...'`** inside the Nextflow file you mount at **`/program/nextflow/nextflow.config`**; a container **`--steps`** / **`-s`** argument **overrides** that for the run.
- **`-s`** here is the **MEGFlow** flag (input path is **`-i`**), not Docker’s **`-i`** (interactive). Typical pattern: `docker run ... cmrlab/megflow:<tag> -i /input -o /output ... --steps all`.
- The Docker entrypoint copies the mounted config to
  `/program/nextflow/run_nextflow.config`, applies command-line path overrides,
  runs Nextflow with that file, and copies it to `<output>/nextflow.config` for
  provenance and static-report packaging.
- The Docker entrypoint starts as root only long enough to prepare mounted output permissions, then drops to the host UID/GID inferred from `/input`; report-only runs that only mount `/output` infer ownership from `/output`.

**Docker output ownership**

You do **not** need to add Docker's `--user` flag or pre-create the output directory. If the host output path does not exist, Docker may create it as `root:root` before the container starts; MEGFlow fixes that at startup, then runs the pipeline as the host user inferred from `/input`. For interactive report runs such as `docker run ... -v /data/preprocessed:/output cmrlab/megflow:<version> -r`, ownership is inferred from `/output`. Outputs should therefore be writable by the submitting user, not owned by root.

Nextflow's `docker.runOptions = '-u $(id -u):$(id -g)'` syntax is valid when a
host Nextflow process launches a separate Docker container for each task. It is
not used by MEGFlow's distributed image, because Nextflow already runs inside
that outer container; enabling it there would require unsupported nested Docker.

If neither `/input` nor `/output` is owned by the user who should own generated files, pass the desired IDs explicitly:

```bash
docker run --rm -it \
  -e LOCAL_UID="$(id -u)" -e LOCAL_GID="$(id -g)" \
  -v /data/bids:/input -v /data/out:/output \
  cmrlab/megflow:<version> \
  -i /input -o /output
```

**Examples:**

```bash
# Full MEG only (explicit; same as default meg_all when config unchanged)
docker run --rm -it \
  -v /data/bids:/input -v /data/out:/output -v /data/smri:/smri \
  -v /data/license.txt:/fs_license.txt \
  cmrlab/megflow:1.0.0 \
  -i /input -o /output \
  --fs_license_file /fs_license.txt --fs_subjects_dir /smri \
  --steps meg_all

# Structural MRI + full MEG in one container run
docker run --rm -it \
  -v /data/bids:/input -v /data/out:/output -v /data/smri:/smri \
  -v /data/license.txt:/fs_license.txt \
  cmrlab/megflow:1.0.0 \
  -i /input -o /output \
  --fs_license_file /fs_license.txt --fs_subjects_dir /smri \
  --steps all

# Static HTML report only (existing preproc under preproc_dir)
docker run --rm -it \
  -v /data/bids:/input -v /data/out:/output -v /data/smri:/smri \
  cmrlab/megflow:1.0.0 \
  -i /input -o /output --fs_subjects_dir /smri \
  --steps report
```

### Main Options

| Option | Description |
| :--- | :--- |
| `-c`, `--config` | Specify the Nextflow config file (default: `nextflow.config`) |
| `-i`, `--input` | Specify the input directory |
| `-o`, `--output` | Specify the output directory (including report results) |
| `-s`, `--steps` | Sets the runtime `params.megflow` steps value (e.g. `all`, `meg_all`, `anatomy`, `report`). With **Docker**, pass this **after the image name**; see [Using pipeline steps with Docker](#using-pipeline-steps-with-docker). Same semantics as [Pipeline steps](#pipeline-steps). |
| `-r`, `--view-report` | Run Streamlit to view the report (does not run Nextflow) |
| `--corpus` | Treat the input directory as a collection of datasets, preserve matching named dataset profiles, run each selected child through the native dataset tuple DAG, and generate a corpus-level static report |
| `--static_task_log_mode` | Static report task log bundling mode: `all-command-log` (default), `failed`, or `none` |
| `--static_artifact_overview_duration` | Seconds represented by the single Artifact Review overview plot in the static report; default `200.0` |
| `--fs_license_file` | Specify the FreeSurfer license file path |
| `--fs_subjects_dir` | Specify the FreeSurfer `SUBJECTS_DIR` containing processed T1 results |
| `--t1_dir` | Specify the T1 image directory |
| `--t1_input_type` | Specify the T1 input type |
| `--t1_dicom_series_glob` | Optional relative glob for selecting DICOM series directories under each T1 DICOM root, e.g. `*T1*` or `*mprage*` |
| `--resume` | Resume the previous run (Nextflow option) |

### Example: Running a Full Pipeline
Example with input/output volumes and license files:

```bash
docker run --rm -it \
    -v /data/datasets/SMN4Lang:/input \
    -v /data/datasets/SMN4Lang/preprocessed:/output \
    -v /data/datasets/SMN4Lang/smri:/smri \
    -v /data/megflow/license.txt:/fs_license.txt \
    -v /data/megflow/nextflow/nextflow.config:/program/nextflow/nextflow.config \
    cmrlab/megflow:1.0.0 \
    -i /input \
    -o /output \
    --fs_license_file /fs_license.txt \
    --fs_subjects_dir /smri \
    --resume
```

For MEGFlow, the default **`steps`** is **`meg_all`** (MEG only, using existing `fs_subjects_dir`). To run **structural MRI + full MEG** together, use **`--steps all`** (or **`-s all`**) on the **`docker run ...`** command line, or set **`params.megflow.defaults.steps = 'all'`** in the mounted config. See [Using pipeline steps with Docker](#using-pipeline-steps-with-docker).

---

## 📐 Quality Control Reports

MEGFlow generates interactive quality control reports via Streamlit.

For corpus-mode outputs, pass the output root with `-o`. The Streamlit viewer
detects `datasets/<dataset_name>/` and adds a dataset selector in the sidebar;
each page then reads the selected dataset's `preprocessed/` tree.

### How to View Reports
Use the `-r` flag and map port `8501`:

```bash
docker run --rm -it -p 8501:8501 \
  -v /data/studies/LanguageStudy/megflow:/output \
  cmrlab/megflow:<version> -r
```

**Access via browser:**
`http://<server_ip>:8501` (or `http://localhost:8501` if running locally)

---

## 🐞 Bug Reports and Feedback

Please report bugs, unexpected behavior, or improvement suggestions through the **GitHub Issues** page.

When reporting a bug, please include:
1.  **System Information**: OS version, Docker version.
2.  **Command Used**: The exact command line you executed.
3.  **Logs**: The relevant part of the error log or traceback (please use code blocks).
4.  **Description**: A clear description of what you expected to happen versus what actually happened.

[Report an Issue](https://github.com/jgaolab/megflow/issues)

---

## 🛠️ Development

Contributions to MEGFlow are welcome. To contribute code or documentation:

1.  **Clone the repository:**
    ```bash
    git clone git@github.com:jgaolab/megflow.git
    cd megflow
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

    **Using the build script:**
    ```bash
    bash build_megflow.sh
    ```

    **Using Docker directly:**
    ```bash
    docker build -t megflow:local -f megflow.Dockerfile .
    ```

4.  **Submit a Pull Request:**
    *   Fork the repository.
    *   Create a new branch for your feature or fix.
    *   Commit your changes and push to your fork.
    *   Submit a Pull Request to the `main` branch.
