# Runnable MEGFlow examples

These launchers are portable starting points for a local checkout. The commands
below assume the current directory is the repository root. Each script resolves
the repository root once invoked; from another directory, use its absolute path.
Use `--help` to see every option before replacing the placeholder paths below.

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
`freesurfer`, `deepprep`, or `pseudomri`.

### `corpus_docker.sh`

`--input` must contain at least one immediate dataset directory. Its default
configuration is
[`nextflow/nextflow_for_docker.config`](../../nextflow/nextflow_for_docker.config),
but a corpus project normally supplies an overlay with dataset profiles. It
passes `--corpus` to the image entrypoint and writes the corpus report to
`<output>/corpus_static_html_report/index.html`.

### `corpus_source.sh`

`--config` is required and remains authoritative for corpus paths, output,
dataset profiles, and scientific settings. The launcher defaults to
[`nextflow/megflow.nf`](../../nextflow/megflow.nf), `nextflow`, `local,strict`,
and resume mode. It derives work and driver-log paths from `output_dir` in the
configuration when that value is available. Use `--no-resume` for a clean run.

### `interactive_report.sh`

`--output` must name an existing writable MEGFlow output directory. The viewer
uses port `8501` by default; choose another valid port with `--port`. Add
`--smri` only when the report needs anatomy files mounted read-only.

For configuration details and the staged-analysis workflow, see the
[quickstart guide](../../docs/source/quickstart/quick_guide.rst), the
[configuration reference](../../docs/source/reference/configuration.rst), and
the [report guide](../../docs/source/tutorial/reports.rst).
