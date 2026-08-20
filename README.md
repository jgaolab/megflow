
# MEGFlow: A Scalable and Reproducible Pipeline for Large-Scale MEG Preprocessing

[![Documentation Status](https://readthedocs.org/projects/megflow-docs/badge/?version=latest)](https://megflow-docs.readthedocs.io/)
[![Docker Pulls](https://img.shields.io/docker/pulls/cplmeg/megflow)](https://hub.docker.com/r/cplmeg/megflow)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

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

### 🔎 Automated Processing and Review
MEGFlow includes automated steps that reduce repeated manual work:
*   Bad-channel and bad-segment detection
*   ICA (Independent Component Analysis) component detection and labeling
*   MEG-MRI coregistration

### 📐 Quality Control Reports
The reporting tools summarize quality-control metrics for each processing stage and flag potential anomalies.

### ⚙️ Parameter Configuration
Configuration files expose dataset paths, preprocessing settings, workflow steps, and report options without requiring changes to pipeline code.

---

## Tested Versions and Runtime

MEGFlow `1.0.0` has been tested with Nextflow `24.10.3`, MNE-Python `1.8.0`,
Python `3.10/3.11`, and Java `17`.

The distributed image also starts under Nextflow `26.04+`. MEGFlow uses DSL2
but currently selects the compatible v1 syntax parser because the workflow
still contains dynamic Groovy constructs that are not accepted by the v2
parser. The Docker entrypoint sets `NXF_SYNTAX_PARSER=v1` automatically. For a
direct source launch with Nextflow 26, export the same variable before running
the pipeline.

For basic use, we recommend at least **8 CPU cores, 32 GB RAM, and 100 GB of
free disk space**, in addition to space for the input data and generated
results. For multi-dataset processing, **16 or more CPU cores, 64 GB RAM, and
SSD storage** are recommended.

The first Docker installation usually takes **20–90 minutes**, mainly depending
on the Docker image download speed. Demo processing may take **tens of minutes
to several hours**, depending on the data size, selected steps, hardware
resources, and configured parallelism.

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

### Recommended: Containerized One-Click Install

The commands below automatically download the matching installer into the
current writable directory and run it immediately. You do not need to clone the
MEGFlow repository or download the installer separately.

The commands always download the current installer from the `main` branch.
`MEGFLOW_VERSION` selects only the `cplmeg/megflow` image tag passed to that
installer. The recommended value is `latest`; use a published version such as
`1.0.0` when you need to pin the image.

#### Linux

Run the following command in a terminal:

```bash
MEGFLOW_VERSION=latest && curl -fL -o install_megflow_linux.sh "https://raw.githubusercontent.com/jgaolab/megflow/main/scripts/install/install_megflow_linux.sh" && bash install_megflow_linux.sh "${MEGFLOW_VERSION}"
```

The optional second argument selects `auto` (default), `docker`, `apptainer`,
or `singularity`. For example, force Apptainer with:

```bash
MEGFLOW_VERSION=latest && curl -fL -o install_megflow_linux.sh "https://raw.githubusercontent.com/jgaolab/megflow/main/scripts/install/install_megflow_linux.sh" && bash install_megflow_linux.sh "${MEGFLOW_VERSION}" apptainer
```

The Apptainer/Singularity path does not use a Docker daemon. It downloads the
published OCI layers from Docker Hub and converts them into
`./megflow_<version>.sif` (or `MEGFLOW_SIF_PATH`).

#### macOS

Run the following command in Terminal:

```bash
MEGFLOW_VERSION=latest && curl -fL -o install_megflow_macos.sh "https://raw.githubusercontent.com/jgaolab/megflow/main/scripts/install/install_megflow_macos.sh" && bash install_megflow_macos.sh "${MEGFLOW_VERSION}"
```

#### Windows PowerShell

Open **Windows PowerShell**, or open a **PowerShell** tab in Windows Terminal,
and paste the complete command below. Do not run it in Command Prompt
(`cmd.exe`) or Git Bash because it uses PowerShell syntax.

```powershell
$MEGFLOW_VERSION = "latest"; $ErrorActionPreference = "Stop"; Invoke-WebRequest -Uri "https://raw.githubusercontent.com/jgaolab/megflow/main/scripts/install/install_megflow_windows.ps1" -OutFile "install_megflow_windows.ps1"; powershell -ExecutionPolicy Bypass -File .\install_megflow_windows.ps1 -ImageTag $MEGFLOW_VERSION
```

#### Optional: Pin an Image Version

To install a specific published image while still using the current installer,
set `MEGFLOW_VERSION` to that image tag:

```bash
MEGFLOW_VERSION=1.0.0 && curl -fL -o install_megflow_linux.sh "https://raw.githubusercontent.com/jgaolab/megflow/main/scripts/install/install_megflow_linux.sh" && bash install_megflow_linux.sh "${MEGFLOW_VERSION}"
```

#### Optional: Inspect or Download the Installer Manually

The commands above already download the installer automatically. Use these
direct links only if you want to inspect a script first or save it for later
manual execution:

[Linux installer](https://raw.githubusercontent.com/jgaolab/megflow/main/scripts/install/install_megflow_linux.sh),
[macOS installer](https://raw.githubusercontent.com/jgaolab/megflow/main/scripts/install/install_megflow_macos.sh), and
[Windows installer](https://raw.githubusercontent.com/jgaolab/megflow/main/scripts/install/install_megflow_windows.ps1).

For more details, see `scripts/install/README.md`.

### Alternative: Local Development Install

> **Important:** This is a source installation. The installer automatically
> clones or updates the GitHub source under `~/.megflow-dev/src/megflow` by
> default. You do not need to clone the repository first or run from its root;
> download and execute the installer from any writable directory. Git and
> access to GitHub are required.

This workflow installs or reuses Conda, Nextflow, FreeSurfer, and MEGFlow source
dependencies in a local installation directory.

```bash
curl -fL -o install_megflow_dev_linux.sh https://raw.githubusercontent.com/jgaolab/megflow/main/scripts/install-dev/install_megflow_dev_linux.sh && bash install_megflow_dev_linux.sh
```

After downloading it, rerun `bash install_megflow_dev_linux.sh` with options
such as `--install-dir /data/megflow-dev` or `--no-freesurfer` when needed.

After installation, load the generated environment:

```bash
source <install-dir>/env.sh
```

For more details, see `scripts/install-dev/README.md`.

### Manual Docker Pull

If you prefer to install manually, install Docker following the
[Docker official documentation](https://docs.docker.com/get-docker/). Browse the
[MEGFlow images and available version tags on Docker Hub](https://hub.docker.com/r/cplmeg/megflow),
then pull the selected image directly:

```bash
MEGFLOW_VERSION=1.0.0 && docker pull "cplmeg/megflow:${MEGFLOW_VERSION}"
```

---

## 💻 Usage

### Basic Command Structure
```bash
docker run --rm -it cplmeg/megflow:<version> [megflow_options]
```

### Runnable Examples

Choose a public script by goal. The relative commands below assume the current
directory is the repository root. Launchers that use bundled configuration or
pipeline files resolve the repository root themselves; from another directory,
use an absolute script path and absolute paths for inputs such as `--config`.
Each script offers `--help` plus `--dry-run` where it launches an external
runtime.

| Goal | Public script |
| :--- | :--- |
| Process one dataset with the official Docker entrypoint | [single-dataset Docker run](examples/run_scripts/single_dataset_docker.sh) |
| Process one dataset from a SIF with Apptainer or SingularityCE | [single-dataset SIF run](examples/run_scripts/single_dataset_sif.sh) |
| Process every immediate dataset directory with Docker corpus mode | [Docker corpus run](examples/run_scripts/corpus_docker.sh) |
| Run a configured corpus with host Nextflow | [source corpus run](examples/run_scripts/corpus_source.sh) |
| Open the Streamlit viewer for existing output | [interactive report viewer](examples/run_scripts/interactive_report.sh) |

Docker-backed launchers default to `cplmeg/megflow:1.0.0`. Use their
`--image` option only when deliberately selecting another published tag.

For a first single-dataset run, provide host paths for the input and output:

```bash
bash examples/run_scripts/single_dataset_docker.sh \
  --input /data/meg_dataset \
  --output /data/megflow_output \
  --resume
```

For an installed Apptainer or SingularityCE runtime, use the same input and
output paths with a local SIF:

```bash
bash examples/run_scripts/single_dataset_sif.sh \
  --input /data/meg_dataset \
  --output /data/megflow_output \
  --sif /data/megflow_1.0.0.sif \
  --resume
```

The [complete run-script guide](examples/run_scripts/README.md) covers every
option, expected output, and troubleshooting guidance.

### Pipeline steps

The file [`nextflow/megflow.nf`](nextflow/megflow.nf) is controlled by **`params.megflow.defaults.steps`** plus optional dataset- or recording-level `steps` overrides in [`nextflow.config`](nextflow/nextflow.config). The default is **`meg_all`**. The Docker entrypoint also accepts `--steps` and writes the corresponding `params.megflow` runtime override.

| Primary `steps` | What it does |
| :--- | :--- |
| `meg_all` | **Default.** Full MEG processing (import → NMDQ score when **`megqc.enabled` = `true`** [default] → basic preprocessing → artifacts → ICA → epochs → covariance → coregistration → forward → source) using the existing **`fs_subjects_dir`**; does **not** run the T1/FreeSurfer/DeepPrep structural pipeline. |
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
| `skip_ica` | Only with **`meg_epochs`** | Skips ICA; loads the detected bad-channel and bad-segment sidecars into `*_preproc-raw` before building epochs. Not available for `all` / `meg_all` (downstream forward/source expect ICA-clean raw). |
| `with_anatomy` | `meg_artifacts`, `meg_ica`, or `meg_epochs` (not `meg_all`) | Runs the structural and selected MEG branches in the same workflow. They may execute concurrently; downstream steps wait for anatomy only when required. |

**Note:** `do_fs`, `do_only_anatomy`, and top-level `params.steps` are no longer used by the Nextflow workflow. Put `steps` under `params.megflow.defaults`, a dataset profile, or a recording profile.

ICA per-component explained variance is optional and disabled by default:
set `compute_explained_variance = true` inside the nested `defaults { ica { ... } }`
block when you want EVAR values in ICA
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
params {
  megflow {
    datasets {
      US_60Hz_Dataset {
        preproc {
          steps = [
            [filter: [l_freq: 1.0, h_freq: 100.0, method: "iir", iir_params: [order: 5, ftype: "butter"]]],
            [notch_filter: [freqs: "60"]],
            [resample: [sfreq: 250]]
          ]
        }
      }
    }
  }
}
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
params {
  megflow {
    datasets {
      CTF_Dataset {
        megqc {
          meg_vendor = "ctf"
        }
      }
      OPM_Artifacts {
        megqc {
          meg_vendor = "opm"
        }
      }
    }
  }
}
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
params {
  megflow {
    defaults {
      megqc {
        enabled = true
        min_score = 70.0    // processing gate
        alarm_score = 70.0  // report warning only
      }
    }
  }
}
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

DeepReject applies the following model-only input recipe by default; the main
workflow FIF is not modified:

```groovy
params {
  megflow {
    defaults {
      artifacts {
        deepreject {
          preproc = [
            [filter: [l_freq: 1.0, h_freq: 100.0, method: "iir", iir_params: [order: 5, ftype: "butter"]]],
            [notch_filter: [freqs: 50]],
            [resample: [sfreq: 250]]
          ]
        }
      }
    }
  }
}
```

**Warning:** A custom recipe or disabled preprocessing departs from the
**model-validated default**. Missing, `null`, or `[]` selects the built-in
recipe; a non-empty `preproc` list replaces it completely, while `false` or
`off` disables it. Upsampling runs normally but **cannot recreate unavailable
source information**; DeepReject records that and narrower source bandwidth as
limitations in `deepreject_summary.json`.

**Examples (local Nextflow):**

```bash
# Default: full MEG only, use existing FreeSurfer/DeepPrep subjects dir
nextflow run nextflow/megflow.nf \
  -c nextflow/nextflow.config \
  -resume

# Complete WAND + SMN4Lang + MEG-MASC example with per-dataset settings
bash examples/run_scripts/corpus_source.sh \
  --config nextflow/nextflow_multi_dataset_demo.config

# To change the stage, edit the nested defaults block shown below.
```

```groovy
params {
  megflow {
    defaults {
      steps = "all"  // Or "anatomy" / "report" for those milestones.
    }
  }
}
```

Set `params.megflow.defaults.steps` in your `nextflow.config` for a project default. For Docker runs, the entrypoint's `--steps` option writes this override into the runtime config.

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

Set this in the active `nextflow.config` so source and Docker runs use the same
saved configuration:

```groovy
params {
  megflow {
    defaults {
      report {
        static_task_log_mode = "all-command-log"
      }
    }
  }
}
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
params {
  megflow {
    corpus_root = "/data/corpus"
    dataset_include = ["WAND", "SMN4Lang", "MEG-MASC"]
    datasets {
      WAND {
        fs_subjects_dir = "/data/corpus/WAND/smri"
        meg_import {
          task = ["visual"]
          subject_id = "first:10"
        }
        megqc {
          meg_vendor = "ctf"
        }
        epochs {
          event_source = "find_events"
          find_events {
            stim_channel = "UPPT001"
          }
        }
      }
      SMN4Lang {
        fs_subjects_dir = "/data/corpus/SMN4Lang_smri"
        meg_import {
          task = ["RDR"]
          subject_id = "first:10"
        }
        megqc {
          meg_vendor = "elekta"
        }
        epochs {
          event_source = "event_file"
          event_time_shift_sec = -10.6105
        }
      }
      MEG_MASC {
        dataset_format = "bids"
        file_suffix = ".con"
        meg_import {
          session_id = ["0"]
          task = ["0"]
          subject_id = "first:10"
        }
        megqc {
          meg_vendor = "kit"
        }
        artifacts {
          meg_vendor = "kit"
          deepreject {
            mode = "lenient"
          }
        }
      }
    }
  }
}
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
scheduling in one DAG. Local runs default to `"auto"` CPU, memory, and task
capacity, using the resources visible to the host or outer container. A fixed
workstation budget can be supplied in an additive config:

```groovy
params {
  megflow {
    execution {
      local_cpus = 16
      local_memory = "48 GB"
      local_max_tasks = 3
    }
  }
}
```

`local_max_tasks = N` maps to the local executor `queueSize`. Actual
concurrency may be lower because CPU, memory, the workflow DAG, and per-process
`maxForks` limits all apply cumulatively. Keep `maxForks` for stages that need
an additional process-specific cap:

```groovy
process {
  withName: detect_artifacts {
    maxForks = 2
  }
}
```

Native OMP, MKL, OpenBLAS, and NumExpr threads default to `task.cpus` for each
task. `score_meg_quality` and `detect_artifacts` use one native thread per
outer worker. Inside `detect_artifacts`, the DeepReject allocator keeps
`fold_workers * cpu_threads <= task.cpus`; detailed artifact-image workers are
also capped at `task.cpus`. Advanced users can override `beforeScript` globally
or in a process selector after validating the native library's threading
behavior.

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
- Pass **`--anat-method deepprep`** after the image name to select the anatomy implementation for one run. Valid values are `freesurfer`, `deepprep`, and `pseudomri`; omitting it preserves the configured `anatomy.method`.
- **Modifiers** that contain commas must be **quoted for the shell**, e.g. `--steps 'meg_epochs,skip_ica'`.
- **Corpus mode** uses `--corpus`; in that mode `-i` / `--input` points to a directory whose immediate children are datasets, and `--fs_subjects_dir` is used as the base directory for per-dataset FreeSurfer outputs. Named profiles, `dataset_include`, `dataset_exclude`, and dataset-level module overrides from the mounted config are preserved.
- You can instead set **`steps = '...'`** inside the nested **`params { megflow { defaults { ... } } }`** block in the Nextflow file mounted at **`/program/nextflow/nextflow.config`**; a container **`--steps`** / **`-s`** argument **overrides** that for the run.
- **`-s`** here is the **MEGFlow** flag (input path is **`-i`**), not Docker’s **`-i`** (interactive). Typical pattern: `docker run ... cplmeg/megflow:<tag> -i /input -o /output ... --steps all`.
- The container entrypoint copies the mounted config to
  `<output>/.nextflow-launch/run_nextflow.config`, applies command-line path
  overrides, runs Nextflow with that writable file, and copies it to
  `<output>/nextflow.config` for provenance and static-report packaging.
- The Docker entrypoint starts as root only long enough to prepare mounted output permissions, then drops to the host UID/GID inferred from `/input`; report-only runs that only mount `/output` infer ownership from `/output`.

**Docker output ownership**

You do **not** need to add Docker's `--user` flag or pre-create the output directory. If the host output path does not exist, Docker may create it as `root:root` before the container starts; MEGFlow fixes that at startup, then runs the pipeline as the host user inferred from `/input`. For interactive report runs such as `docker run ... -v /data/preprocessed:/output cplmeg/megflow:<version> -r`, ownership is inferred from `/output`. Outputs should therefore be writable by the submitting user, not owned by root.

Pre-create every other writable bind-mount source as the submitting user,
especially the structural directory used by `-v /data/smri:/smri`. Docker may
otherwise create a missing host path as `root:root`, leaving `/smri` unwritable
after MEGFlow drops privileges. Before anatomy or source processing, run
`mkdir -p /data/smri` and confirm `test -w /data/smri` succeeds.

Nextflow's `docker.runOptions = '-u $(id -u):$(id -g)'` syntax is valid when a
host Nextflow process launches a separate Docker container for each task. It is
not used by MEGFlow's distributed image, because Nextflow already runs inside
that outer container; enabling it there would require unsupported nested Docker.

If neither `/input` nor `/output` is owned by the user who should own generated files, pass the desired IDs explicitly:

```bash
docker run --rm -it \
  -e LOCAL_UID="$(id -u)" -e LOCAL_GID="$(id -g)" \
  -v /data/bids:/input -v /data/out:/output \
  cplmeg/megflow:<version> \
  -i /input -o /output
```

**Examples:**

```bash
# Full MEG only (explicit; same as default meg_all when config unchanged)
docker run --rm -it \
  -v /data/bids:/input -v /data/out:/output -v /data/smri:/smri \
  -v /data/license.txt:/fs_license.txt \
  cplmeg/megflow:1.0.0 \
  -i /input -o /output \
  --fs_license_file /fs_license.txt --fs_subjects_dir /smri \
  --steps meg_all

# Structural MRI + full MEG in one container run
docker run --rm -it \
  -v /data/bids:/input -v /data/out:/output -v /data/smri:/smri \
  -v /data/license.txt:/fs_license.txt \
  cplmeg/megflow:1.0.0 \
  -i /input -o /output \
  --fs_license_file /fs_license.txt --fs_subjects_dir /smri \
  --steps all

# Static HTML report only (existing preproc under preproc_dir)
docker run --rm -it \
  -v /data/bids:/input -v /data/out:/output -v /data/smri:/smri \
  cplmeg/megflow:1.0.0 \
  -i /input -o /output --fs_subjects_dir /smri \
  --steps report
```

### Using MEGFlow with Apptainer or Singularity

The Linux installer creates a local SIF that can run the same MEGFlow
entrypoint. Bind host directories to the container paths used in the command:

```bash
mkdir -p /data/out

apptainer run --cleanenv \
  --bind /data/bids:/input \
  --bind /data/out:/output \
  ./megflow_1.0.0.sif \
  -i /input -o /output \
  --steps meg_ica --resume
```

Use `singularity run` in place of `apptainer run` on SingularityCE systems.
Add structural MRI, FreeSurfer license, and custom-config binds when those paths
are needed, for example:

```bash
apptainer run --cleanenv \
  --bind /data/bids:/input \
  --bind /data/out:/output \
  --bind /data/smri:/smri \
  --bind /data/license.txt:/fs_license.txt:ro \
  --bind /data/megflow/nextflow.config:/program/nextflow/nextflow.config:ro \
  ./megflow_1.0.0.sif \
  -i /input -o /output \
  --fs_license_file /fs_license.txt \
  --fs_subjects_dir /smri \
  --steps all --resume
```

SIF root filesystems remain read-only. MEGFlow writes its generated runtime
configuration and Nextflow state beneath the bound `/output` directory.

### Main Options

| Option | Description |
| :--- | :--- |
| `-c`, `--config` | Specify the Nextflow config file (default: `nextflow.config`) |
| `-i`, `--input` | Specify the input directory |
| `-o`, `--output` | Specify the output directory (including report results) |
| `-s`, `--steps` | Sets the runtime `params.megflow` steps value (e.g. `all`, `meg_all`, `anatomy`, `report`). With **Docker**, pass this **after the image name**; see [Using pipeline steps with Docker](#using-pipeline-steps-with-docker). Same semantics as [Pipeline steps](#pipeline-steps). |
| `--anat-method` | Sets the runtime anatomy method to `freesurfer`, `deepprep`, or `pseudomri`. Single-dataset mode overrides `docker_input`; corpus mode changes the shared default while preserving explicit named-dataset methods. |
| `-r`, `--view-report` | Run Streamlit to view the report (does not run Nextflow) |
| `--corpus` | Treat the input directory as a collection of datasets, preserve matching named dataset profiles, run each selected child through the native dataset tuple DAG, and generate a corpus-level static report |
| `--fs_license_file` | Specify the FreeSurfer license file path |
| `--fs_subjects_dir` | Specify the FreeSurfer `SUBJECTS_DIR` containing processed T1 results |
| `--t1_dir` | Specify the T1 image directory |
| `--resume` | Resume the previous run (Nextflow option) |

Other processing and report policy is configured in `params.megflow`, not
exposed as Docker entrypoint flags. This includes `anatomy.t1_input_type`,
`anatomy.t1_dicom_series_glob`,
`report.static_task_log_mode`, and
`report.static_artifact_overview_duration`. Put shared values under
`params.megflow.defaults` and dataset-specific values under the matching
`params.megflow.datasets.<name>` profile.

### Example: Running a Full Pipeline
Example with input/output volumes and license files:

```bash
docker run --rm -it \
    -v /data/datasets/SMN4Lang:/input \
    -v /data/datasets/SMN4Lang/preprocessed:/output \
    -v /data/datasets/SMN4Lang/smri:/smri \
    -v /data/megflow/license.txt:/fs_license.txt \
    -v /data/megflow/nextflow/nextflow.config:/program/nextflow/nextflow.config \
    cplmeg/megflow:1.0.0 \
    -i /input \
    -o /output \
    --fs_license_file /fs_license.txt \
    --fs_subjects_dir /smri \
    --resume
```

For MEGFlow, the default **`steps`** is **`meg_all`** (MEG only, using existing `fs_subjects_dir`). To run **structural MRI + full MEG** together, use **`--steps all`** (or **`-s all`**) on the **`docker run ...`** command line, or set **`steps = 'all'`** in the mounted config's nested **`params { megflow { defaults { ... } } }`** block. See [Using pipeline steps with Docker](#using-pipeline-steps-with-docker).

---

## 📐 Quality Control Reports

MEGFlow generates a portable static HTML quality-control report for each
processed dataset and a cross-dataset dashboard for corpus runs. The static
report is the primary review output and can be opened directly from
`static_html_report/index.html` or `corpus_static_html_report/index.html`.

An optional interactive Streamlit viewer supports closer inspection and manual
editing of selected bad-channel, bad-segment, ICA, coregistration, and source
review outputs.

For corpus-mode outputs, pass the output root with `-o`. The Streamlit viewer
detects `datasets/<dataset_name>/` and adds a dataset selector in the sidebar;
each page then reads the selected dataset's `preprocessed/` tree.

### How to View the Interactive Report

The command below starts the Streamlit interactive report viewer for existing
MEGFlow output. The `-r` option does not run Nextflow preprocessing and is
separate from opening the portable static HTML report. Map port `8501` to make
the interactive viewer available in a browser:

```bash
docker run --rm -it -p 8501:8501 \
  -v /data/studies/LanguageStudy/megflow:/output \
  cplmeg/megflow:1.0.0 -r
```

**Access via browser:**
`http://<server_ip>:8501` (or `http://localhost:8501` if running locally)

---

## 🛠️ Development

Contributions to MEGFlow are welcome. The public helpers below resolve the
repository root once invoked. The shown relative invocations assume the current
directory is the repository root; use an absolute script path, and absolute
input or config paths, when invoking them from elsewhere.

### Prerequisites

Use a POSIX shell with Bash 3.2+ and Java 17 (up to 23). Source-mode workflow
development additionally needs Nextflow 24.10 or newer; Docker image work
needs a running Docker daemon; and documentation work needs the pinned packages
in `requirements_doc.txt`. Windows contributors can use WSL for Bash helpers,
while the native installer is validated separately in CI.

### Local Development Setup

```bash
git clone git@github.com:jgaolab/megflow.git
cd megflow
nextflow info
```

Install Nextflow using the [official instructions](https://www.nextflow.io/docs/latest/install.html),
then ensure it is on `PATH`. Use the source installation instructions in
[`scripts/install-dev/README.md`](scripts/install-dev/README.md) when a local
MEGFlow environment is needed instead of the distributed image.

### Validation and Regression-Test Modes

Run the fast routing gate used for push and pull-request checks from an
activated MEGFlow environment:

```bash
export MEGFLOW_NEXTFLOW="$(command -v nextflow)"
bash scripts/validation/run_validation.sh routing-ci
```

`routing-ci` runs static routing contracts, parses tracked Nextflow configs,
and executes a representative Nextflow 24.10.3 smoke matrix. `routing` adds
the exhaustive local routing, resume-deletion, failure, report, and
documentation-example matrices. `scientific` runs synthetic MNE/OSL filtering,
epochs, covariance, source-call, NormMEG-QC, DeepReject-input, MEGNet/ICA-label,
and report tests. `all` runs the complete local gates and builds documentation
when its dependencies are installed. Requested gates fail if dependencies are
missing, no tests are discovered, or any test is skipped.

GitHub Actions runs `routing-ci`, `scientific`, native Linux installer and
native macOS installer jobs, Windows parser/contracts on the Windows runner,
and the strict documentation build for every push and pull request. The
exhaustive `routing` matrix remains a local pre-release gate. Pinned lightweight
scientific dependencies are in `requirements_validation.txt`.

### Public Developer-Script Reference

| Helper | Purpose and command | Prerequisites, output, and safety |
| :--- | :--- | :--- |
| [build_megflow.sh](scripts/development/build_megflow.sh) | Build the local `cplmeg/megflow:local` image: `bash scripts/development/build_megflow.sh --dry-run` | Docker is required outside dry-run; builds from `megflow.Dockerfile` and does not overwrite a release tag by default. |
| [build_docs.sh](scripts/development/build_docs.sh) | Build documentation: `bash scripts/development/build_docs.sh --strict` | Python/Sphinx dependencies are required; writes HTML under `docs/build/html` by default. |
| [docker2sif.sh](scripts/development/docker2sif.sh) | Convert an existing local image: `bash scripts/development/docker2sif.sh --image cplmeg/megflow:local` | Apptainer or Singularity is required even for dry-run; Docker and the local-image check are required only for conversion. It neither pulls nor builds an image and refuses an existing output unless `--force` is explicit. |

All three helpers provide `--help`. Read their option descriptions before using
them on a shared workstation or cluster.

### Building the Docker Image

After changing the Dockerfile or packaged dependencies, inspect the assembled
build command first and then run it when the local Docker daemon is available:

```bash
bash scripts/development/build_megflow.sh --dry-run
bash scripts/development/build_megflow.sh --tag local
```

The default output is the local development image `cplmeg/megflow:local`. Use
`--image`, `--tag`, `--dockerfile`, `--platform`, or `--no-cache` only when the
change requires them.

### Building and Strictly Validating Documentation

Build the HTML documentation with CI-equivalent warning handling:

```bash
bash scripts/development/build_docs.sh --strict
```

The default output is `docs/build/html`. `--clean` removes only the selected
documentation output directory before rebuilding; choose a custom `--output`
when retaining a separate preview is useful.

### Advanced Local Docker-to-SIF Conversion

Preview or convert a development image that already exists on the local Docker
daemon:

```bash
bash scripts/development/docker2sif.sh --image cplmeg/megflow:local --dry-run
bash scripts/development/docker2sif.sh --image cplmeg/megflow:local
```

The helper discovers Apptainer or Singularity before assembling either command,
so one of those runtimes is required for dry-run too. Docker availability and
the local-image check apply only to an actual conversion. The helper writes a
sanitized `.sif` filename unless `--output` is specified and does not build or
pull an image automatically.

### Pull-Request Workflow

Create a focused branch, run the relevant validation mode and strict
documentation build, then commit and open a pull request. Include the command
and output needed to reproduce any user-visible pipeline or documentation
change. Keep unrelated local or site-specific launchers out of the change.

---

## 🐞 Bug Reports and Feedback

Please report bugs, unexpected behavior, or improvement suggestions through the **GitHub Issues** page.

When reporting a bug, please include:
1.  **System Information**: OS version, Docker version.
2.  **Command Used**: The exact command line you executed.
3.  **Logs**: The relevant part of the error log or traceback (please use code blocks).
4.  **Description**: A clear description of what you expected to happen versus what actually happened.

[Report an Issue](https://github.com/jgaolab/megflow/issues)
