#!/usr/bin/env bash
set -euo pipefail

# Run the WAND + SMN4Lang + MEG-MASC demo directly with host Nextflow.
# Scientific stages, dataset paths, subject filters, and per-dataset overrides
# are read from nextflow/nextflow_multi_dataset_demo.config.
#
# Examples:
#   bash run_MultiDatasets_sourcecode.sh
#   CONDA_ENV=megflow bash run_MultiDatasets_sourcecode.sh
#   PROFILE=slurm,strict bash run_MultiDatasets_sourcecode.sh
#   RESUME=false DRY_RUN=true bash run_MultiDatasets_sourcecode.sh

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE="${PIPELINE:-${PROJECT_ROOT}/nextflow/megflow.nf}"
CONFIG="${CONFIG:-${PROJECT_ROOT}/nextflow/nextflow_multi_dataset_demo.config}"
NEXTFLOW_BIN="${NEXTFLOW_BIN:-nextflow}"
PROFILE="${PROFILE:-local,strict}"
RESUME="${RESUME:-true}"
DRY_RUN="${DRY_RUN:-false}"
CONDA_ENV="${CONDA_ENV:-}"

if [ ! -f "$PIPELINE" ]; then
    echo "Pipeline does not exist: $PIPELINE" >&2
    exit 1
fi

if [ ! -f "$CONFIG" ]; then
    echo "Config does not exist: $CONFIG" >&2
    exit 1
fi

for arg in "$@"; do
    case "$arg" in
        --steps|--steps=*)
            echo "Do not pass --steps to source Nextflow runs." >&2
            echo "Set params.megflow.defaults.steps or a dataset profile's steps in $CONFIG." >&2
            exit 1
            ;;
    esac
done

if [ -n "$CONDA_ENV" ]; then
    if ! command -v conda >/dev/null 2>&1; then
        echo "CONDA_ENV is set but conda is not available on PATH." >&2
        exit 1
    fi
    eval "$(conda shell.bash hook)"
    conda activate "$CONDA_ENV"
fi

if [[ "$NEXTFLOW_BIN" == */* ]]; then
    if [ ! -x "$NEXTFLOW_BIN" ]; then
        echo "Nextflow executable is not available: $NEXTFLOW_BIN" >&2
        exit 1
    fi
elif ! command -v "$NEXTFLOW_BIN" >/dev/null 2>&1; then
    echo "Nextflow is not available on PATH." >&2
    echo "Install Nextflow or set NEXTFLOW_BIN=/path/to/nextflow." >&2
    exit 1
fi

OUTPUT_ROOT="$(
    sed -n 's/^[[:space:]]*output_dir[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$CONFIG" \
        | head -n 1
)"
if [ -z "$OUTPUT_ROOT" ]; then
    echo "Could not read params.megflow.output_dir from: $CONFIG" >&2
    exit 1
fi

WORK_DIR="${WORK_DIR:-${OUTPUT_ROOT}/work}"
LOG_FILE="${LOG_FILE:-${OUTPUT_ROOT}/corpus_static_html_report/nextflow/nextflow.log}"

case "$RESUME" in
    true|TRUE|True|1|yes|YES|-resume) resume_enabled=true ;;
    false|FALSE|False|0|no|NO|"") resume_enabled=false ;;
    *)
        echo "Invalid RESUME value: $RESUME (expected true or false)" >&2
        exit 1
        ;;
esac

case "$DRY_RUN" in
    true|TRUE|True|1|yes|YES) dry_run_enabled=true ;;
    false|FALSE|False|0|no|NO|"") dry_run_enabled=false ;;
    *)
        echo "Invalid DRY_RUN value: $DRY_RUN (expected true or false)" >&2
        exit 1
        ;;
esac

if [ -z "${NXF_ANSI_LOG:-}" ]; then
    if [ -t 1 ]; then
        export NXF_ANSI_LOG=true
    else
        export NXF_ANSI_LOG=false
    fi
fi

nextflow_cmd=(
    "$NEXTFLOW_BIN"
    -log "$LOG_FILE"
    -C "$CONFIG"
    run "$PIPELINE"
    -profile "$PROFILE"
    -w "$WORK_DIR"
)
if [ "$resume_enabled" = true ]; then
    nextflow_cmd+=(-resume)
fi
if [ "$#" -gt 0 ]; then
    nextflow_cmd+=("$@")
fi

echo "============================================================"
echo "MEGFlow multi-dataset source run"
echo "Project root:  $PROJECT_ROOT"
echo "Pipeline:      $PIPELINE"
echo "Config:        $CONFIG"
echo "Output root:   $OUTPUT_ROOT"
echo "Work dir:      $WORK_DIR"
echo "Nextflow log:  $LOG_FILE"
echo "Profile:       $PROFILE"
echo "Resume:        $resume_enabled"
echo "Conda env:     ${CONDA_ENV:-current environment}"
echo "============================================================"

if [ "$dry_run_enabled" = true ]; then
    printf 'Command:'
    printf ' %q' "${nextflow_cmd[@]}"
    printf '\n'
    exit 0
fi

mkdir -p "$WORK_DIR" "$(dirname "$LOG_FILE")"
cd "$PROJECT_ROOT"
exec "${nextflow_cmd[@]}"
