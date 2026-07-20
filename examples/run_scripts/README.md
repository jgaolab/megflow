# Runnable MEGFlow examples

These launchers are portable starting points for a local checkout. The commands
below assume the current directory is the repository root. Scripts that use
bundled configuration or pipeline files resolve the repository root once
invoked; from another directory, use an absolute script path. Use `--help` to
see every option before replacing the placeholder paths below.

| Goal | Script | First command |
| --- | --- | --- |
| First Docker run for one dataset | `single_dataset_docker.sh` | `bash examples/run_scripts/single_dataset_docker.sh --input /data/bids --output /data/megflow-output --smri /data/smri --license /data/license.txt --steps meg_ica` |
| Process immediate children of a corpus root in Docker | `corpus_docker.sh` | `bash examples/run_scripts/corpus_docker.sh --input /data/corpus --output /data/corpus-output --smri /data/corpus-smri --config /data/corpus.config --steps meg_ica --resume` |
| Run a corpus configuration with host Nextflow | `corpus_source.sh` | `bash examples/run_scripts/corpus_source.sh --config /data/corpus.config --profile local,strict --resume` |
| Open a completed report in Streamlit | `interactive_report.sh` | `bash examples/run_scripts/interactive_report.sh --output /data/megflow-output --port 8501` |

## Common safety behavior

All four scripts use strict Bash mode, quote supplied paths, reject unknown or
incomplete options, and print the final command. `--help` works without Docker
or Nextflow. Use `--dry-run` to inspect a launch command without starting an
external runtime. The Docker processing launchers create only the output and
anatomy directories selected for that invocation; the source launcher may also
create its selected work and log directories. None changes ownership or
permissions recursively. Configuration and license mounts are read-only.

The Docker launchers use `-it` when attached to a terminal and fall back to
`-i` for non-interactive environments. The report launcher does not run
Nextflow: it mounts an existing output directory and exposes the viewer at
`http://localhost:<port>`.

## Script notes

### `single_dataset_docker.sh`

`--input` and `--output` are required. Its default configuration is
[`nextflow/quickstart.config`](../../nextflow/quickstart.config), and the
default `--steps` value is `meg_ica`. Supply `--smri` and `--license` when the
chosen stage needs FreeSurfer outputs or a license. `--anat-method` accepts
`freesurfer`, `deepprep`, or `pseudomri`. A successful processing run reports
`<output>/static_html_report/index.html`.

| Option | Requirement/default | Purpose |
| --- | --- | --- |
| `--input DIR` | Required | Read-only host dataset mounted at `/input`. |
| `--output DIR` | Required | Writable host result directory mounted at `/output`. |
| `--config FILE` | `nextflow/quickstart.config` | Nextflow configuration mounted read-only. |
| `--smri DIR` | None | Writable anatomy/FreeSurfer subjects directory. |
| `--license FILE` | None | FreeSurfer license mounted read-only. |
| `--image IMAGE` | `cplmeg/megflow:latest` | Docker image to run. |
| `--steps VALUE` | `meg_ica` | Requested MEGFlow stage. |
| `--anat-method METHOD` | Config default | Override with `freesurfer`, `deepprep`, or `pseudomri`. |
| `--resume` | Off | Resume a previous Nextflow run. |
| `--dry-run` | Off | Print the Docker command without launching it. |
| `--help` | — | Print CLI help and exit. |

### `corpus_docker.sh`

`--input` must contain at least one immediate dataset directory. Its default
configuration is
[`nextflow/nextflow_for_docker.config`](../../nextflow/nextflow_for_docker.config),
but a corpus project normally supplies an overlay with dataset profiles. It
passes `--corpus` to the image entrypoint and writes the corpus report to
`<output>/corpus_static_html_report/index.html`.

| Option | Requirement/default | Purpose |
| --- | --- | --- |
| `--input DIR` | Required | Corpus root containing immediate dataset directories. |
| `--output DIR` | Required | Writable corpus result root. |
| `--config FILE` | `nextflow/nextflow_for_docker.config` | Corpus configuration mounted read-only. |
| `--smri DIR` | `<output>/smri` | Writable shared anatomy directory. |
| `--license FILE` | None | FreeSurfer license mounted read-only. |
| `--image IMAGE` | `cplmeg/megflow:latest` | Docker image to run. |
| `--steps VALUE` | `meg_ica` | Requested MEGFlow stage for the corpus. |
| `--resume` | Off | Resume previous corpus work. |
| `--dry-run` | Off | Print the Docker command without launching it. |
| `--help` | — | Print CLI help and exit. |

### `corpus_source.sh`

`--config` is required and remains authoritative for corpus paths, output,
dataset profiles, and scientific settings. The launcher defaults to
[`nextflow/megflow.nf`](../../nextflow/megflow.nf), `nextflow`, `local,strict`,
and resume mode. It derives work and driver-log paths from `output_dir` in the
configuration when that value is available. Use `--no-resume` for a clean run.
On success it prints the corpus report location under the configured output.

| Option | Requirement/default | Purpose |
| --- | --- | --- |
| `--config FILE` | Required | Authoritative corpus and scientific configuration. |
| `--pipeline FILE` | `nextflow/megflow.nf` | Nextflow pipeline file. |
| `--nextflow PATH_OR_COMMAND` | `nextflow` | Nextflow executable or command name. |
| `--profile VALUE` | `local,strict` | Comma-separated Nextflow profiles. |
| `--conda-env NAME` | None | Conda environment activated before launch. |
| `--work-dir DIR` | Derived when possible | Override Nextflow `-w`. |
| `--log-file FILE` | Derived when possible | Override the Nextflow driver log. |
| `--resume` | On | Explicitly retain resume mode. |
| `--no-resume` | Off | Disable resume mode. |
| `--dry-run` | Off | Print the Nextflow command without launching it. |
| `--help` | — | Print CLI help and exit. |

### `interactive_report.sh`

`--output` must name an existing writable MEGFlow output directory. The viewer
uses port `8501` by default; choose another valid port with `--port`. Add
`--smri` only when the report needs anatomy files mounted read-only. A custom
host port is mapped to the viewer's fixed container port `8501`.

| Option | Requirement/default | Purpose |
| --- | --- | --- |
| `--output DIR` | Required | Existing writable result directory mounted at `/output`. |
| `--smri DIR` | None | Optional anatomy directory mounted read-only. |
| `--image IMAGE` | `cplmeg/megflow:latest` | Docker image containing the viewer. |
| `--port PORT` | `8501` | Host port for `http://localhost:<port>`. |
| `--dry-run` | Off | Print the Docker command without launching it. |
| `--help` | — | Print CLI help and exit. |

## Troubleshooting

- Run with `--dry-run` first and verify every host path and mounted container
  path in the printed command.
- Create output and anatomy bind-source directories as your normal host user
  before launching Docker. If Docker creates a missing source as `root`, the
  non-root process in the container may be unable to write it.
- If Docker is unavailable, confirm both the client and daemon are running and
  that your account can access the daemon. A FreeSurfer stage also needs a
  readable license and writable `--smri` directory.
- For source mode, confirm Nextflow is on `PATH` (or set `--nextflow`), the
  selected Conda environment exists, and the configured output/work/log parents
  are writable and traversable.
- If the report viewer port is already occupied, choose another host port, for
  example `--port 8502`; the script still maps it to container port `8501`.

For configuration details and the staged-analysis workflow, see the
[quickstart guide](../../docs/source/quickstart/quick_guide.rst), the
[configuration reference](../../docs/source/reference/configuration.rst), and
the [report guide](../../docs/source/tutorial/reports.rst).
