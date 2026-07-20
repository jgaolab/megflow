#!/usr/bin/env bash
set -euo pipefail

die() {
    printf 'Error: %s\n' "$*" >&2
    exit 2
}

require_value() {
    [ "$#" -ge 2 ] && [ -n "$2" ] || die "$1 requires a value"
}

print_command() {
    printf 'Command:'
    printf ' %q' "$@"
    printf '\n'
}

usage() {
    cat <<'EOF'
Usage: corpus_source.sh --config FILE [options]

Run a corpus configuration with host Nextflow. The config supplies all
corpus paths, dataset profiles, and scientific parameters.

Options:
  --pipeline FILE               Pipeline (default: nextflow/megflow.nf)
  --nextflow PATH_OR_COMMAND    Nextflow command (default: nextflow)
  --profile VALUE               Profile (default: local,strict)
  --conda-env NAME              Activate this Conda environment before launch
  --work-dir DIR                Nextflow work directory
  --log-file FILE               Nextflow driver log file
  --resume                      Resume a previous run (default)
  --no-resume                   Do not resume a previous run
  --dry-run                     Print the Nextflow command without running it
  --help                        Show this help
EOF
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG="${MEGFLOW_CONFIG:-}"
PIPELINE="${MEGFLOW_PIPELINE:-${REPO_ROOT}/nextflow/megflow.nf}"
NEXTFLOW_BIN="${MEGFLOW_NEXTFLOW:-nextflow}"
PROFILE="${MEGFLOW_PROFILE:-local,strict}"
CONDA_ENV="${MEGFLOW_CONDA_ENV:-}"
WORK_DIR="${MEGFLOW_WORK_DIR:-}"
LOG_FILE="${MEGFLOW_LOG_FILE:-}"
RESUME=true
DRY_RUN=false

while [ "$#" -gt 0 ]; do
    case "$1" in
        --config) require_value "$@"; CONFIG="$2"; shift 2 ;;
        --pipeline) require_value "$@"; PIPELINE="$2"; shift 2 ;;
        --nextflow) require_value "$@"; NEXTFLOW_BIN="$2"; shift 2 ;;
        --profile) require_value "$@"; PROFILE="$2"; shift 2 ;;
        --conda-env) require_value "$@"; CONDA_ENV="$2"; shift 2 ;;
        --work-dir) require_value "$@"; WORK_DIR="$2"; shift 2 ;;
        --log-file) require_value "$@"; LOG_FILE="$2"; shift 2 ;;
        --resume) RESUME=true; shift ;;
        --no-resume) RESUME=false; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help) usage; exit 0 ;;
        *) die "unknown option: $1 (use --help)" ;;
    esac
done

[ -n "$CONFIG" ] || die "--config is required"
[ -f "$CONFIG" ] && [ -r "$CONFIG" ] || die "config file is not readable: $CONFIG"
[ -f "$PIPELINE" ] && [ -r "$PIPELINE" ] || die "pipeline file is not readable: $PIPELINE"
OUTPUT_ROOT="$(sed -n 's/^[[:space:]]*output_dir[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$CONFIG" | head -n 1)"
if [ -z "$OUTPUT_ROOT" ]; then
    OUTPUT_ROOT="$(sed -n "s/^[[:space:]]*output_dir[[:space:]]*=[[:space:]]*'\([^']*\)'.*/\1/p" "$CONFIG" | head -n 1)"
fi
if [ -n "$OUTPUT_ROOT" ]; then
    if [ -z "$WORK_DIR" ]; then WORK_DIR="${OUTPUT_ROOT}/work"; fi
    if [ -z "$LOG_FILE" ]; then LOG_FILE="${OUTPUT_ROOT}/corpus_static_html_report/nextflow/nextflow.log"; fi
fi

nextflow_cmd=("$NEXTFLOW_BIN")
if [ -n "$LOG_FILE" ]; then nextflow_cmd+=(-log "$LOG_FILE"); fi
nextflow_cmd+=(-C "$CONFIG" run "$PIPELINE" -profile "$PROFILE")
if [ -n "$WORK_DIR" ]; then nextflow_cmd+=(-w "$WORK_DIR"); fi
if [ "$RESUME" = true ]; then nextflow_cmd+=(-resume); fi

printf 'MEGFlow corpus source run\nConfig: %s\nPipeline: %s\n' "$CONFIG" "$PIPELINE"
print_command "${nextflow_cmd[@]}"
if [ "$DRY_RUN" = true ]; then exit 0; fi
if [ -n "$CONDA_ENV" ]; then
    command -v conda >/dev/null 2>&1 || die "Conda is not available on PATH"
    eval "$(conda shell.bash hook)"
    conda activate "$CONDA_ENV"
fi
if [[ "$NEXTFLOW_BIN" == */* ]]; then
    [ -x "$NEXTFLOW_BIN" ] || die "Nextflow executable is not available: $NEXTFLOW_BIN"
else
    command -v "$NEXTFLOW_BIN" >/dev/null 2>&1 || die "Nextflow is not available on PATH"
fi
if [ -n "$WORK_DIR" ]; then
    if [ -e "$WORK_DIR" ] && { [ ! -d "$WORK_DIR" ] || [ ! -w "$WORK_DIR" ]; }; then
        die "work directory is not writable: $WORK_DIR"
    fi
    if [ ! -e "$WORK_DIR" ]; then mkdir -p "$WORK_DIR" || die "could not create work directory: $WORK_DIR"; fi
    [ -d "$WORK_DIR" ] && [ -w "$WORK_DIR" ] || die "work directory is not writable: $WORK_DIR"
fi
if [ -n "$LOG_FILE" ]; then
    LOG_PARENT="$(dirname "$LOG_FILE")"
    if [ -e "$LOG_FILE" ] && { [ ! -f "$LOG_FILE" ] || [ ! -w "$LOG_FILE" ]; }; then
        die "log file is not writable: $LOG_FILE"
    fi
    if [ -e "$LOG_PARENT" ] && { [ ! -d "$LOG_PARENT" ] || [ ! -w "$LOG_PARENT" ]; }; then
        die "log directory is not writable: $LOG_PARENT"
    fi
    if [ ! -e "$LOG_PARENT" ]; then mkdir -p "$LOG_PARENT" || die "could not create log directory: $LOG_PARENT"; fi
    [ -d "$LOG_PARENT" ] && [ -w "$LOG_PARENT" ] || die "log directory is not writable: $LOG_PARENT"
fi
if ! "${nextflow_cmd[@]}"; then
    printf 'Error: Nextflow launch failed\n' >&2
    exit 1
fi
printf 'Corpus report: %s/corpus_static_html_report/index.html\n' "${OUTPUT_ROOT:-configured output directory}"
