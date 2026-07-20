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
Usage: corpus_docker.sh --input DIR --output DIR [options]

Run every immediate dataset directory through MEGFlow's Docker corpus mode.

Options:
  --config FILE                 Config file (default: nextflow/nextflow_for_docker.config)
  --smri DIR                    Writable subjects directory (default: OUTPUT/smri)
  --license FILE                FreeSurfer license file
  --image IMAGE                 Docker image (default: cplmeg/megflow:latest)
  --steps VALUE                 Pipeline stage (default: meg_ica)
  --resume                      Resume a previous run
  --dry-run                     Print the Docker command without running it
  --help                        Show this help
EOF
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INPUT="${MEGFLOW_INPUT:-}"
OUTPUT="${MEGFLOW_OUTPUT:-}"
CONFIG="${MEGFLOW_CONFIG:-${REPO_ROOT}/nextflow/nextflow_for_docker.config}"
SMRI="${MEGFLOW_SMRI:-}"
LICENSE_FILE="${MEGFLOW_LICENSE:-}"
IMAGE="${MEGFLOW_IMAGE:-cplmeg/megflow:latest}"
STEPS="${MEGFLOW_STEPS:-meg_ica}"
RESUME=false
DRY_RUN=false

while [ "$#" -gt 0 ]; do
    case "$1" in
        --input) require_value "$@"; INPUT="$2"; shift 2 ;;
        --output) require_value "$@"; OUTPUT="$2"; shift 2 ;;
        --config) require_value "$@"; CONFIG="$2"; shift 2 ;;
        --smri) require_value "$@"; SMRI="$2"; shift 2 ;;
        --license) require_value "$@"; LICENSE_FILE="$2"; shift 2 ;;
        --image) require_value "$@"; IMAGE="$2"; shift 2 ;;
        --steps) require_value "$@"; STEPS="$2"; shift 2 ;;
        --resume) RESUME=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help) usage; exit 0 ;;
        *) die "unknown option: $1 (use --help)" ;;
    esac
done

[ -n "$INPUT" ] || die "--input is required"
[ -n "$OUTPUT" ] || die "--output is required"
[ -d "$INPUT" ] && [ -r "$INPUT" ] || die "input directory is not readable: $INPUT"
[ -f "$CONFIG" ] && [ -r "$CONFIG" ] || die "config file is not readable: $CONFIG"
if ! find "$INPUT" -mindepth 1 -maxdepth 1 -type d -print -quit | grep -q .; then
    die "corpus input has no immediate dataset directories: $INPUT"
fi
if [ -z "$SMRI" ]; then SMRI="${OUTPUT}/smri"; fi
if [ -n "$LICENSE_FILE" ]; then
    [ -f "$LICENSE_FILE" ] && [ -r "$LICENSE_FILE" ] || die "license file is not readable: $LICENSE_FILE"
fi
if [ -e "$SMRI" ] && { [ ! -d "$SMRI" ] || [ ! -w "$SMRI" ]; }; then
    die "smri path is not a writable directory: $SMRI"
fi

if [ ! -e "$OUTPUT" ]; then mkdir -p "$OUTPUT" || die "could not create output directory: $OUTPUT"; fi
[ -d "$OUTPUT" ] && [ -w "$OUTPUT" ] || die "output directory is not writable: $OUTPUT"
if [ ! -e "$SMRI" ]; then mkdir -p "$SMRI" || die "could not create smri directory: $SMRI"; fi
[ -d "$SMRI" ] && [ -w "$SMRI" ] || die "smri path is not a writable directory: $SMRI"
INPUT="$(cd "$INPUT" && pwd -P)"
OUTPUT="$(cd "$OUTPUT" && pwd -P)"
SMRI="$(cd "$SMRI" && pwd -P)"
if [ "$DRY_RUN" != true ]; then command -v docker >/dev/null 2>&1 || die "Docker is not available on PATH"; fi

CONFIG_PATH="$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")"
docker_args=(run --rm)
if [ -t 0 ] && [ -t 1 ]; then docker_args+=(-it); else docker_args+=(-i); fi
docker_args+=(
    -v "${INPUT}:/input:ro"
    -v "${OUTPUT}:/output"
    -v "${SMRI}:/smri"
    -v "${CONFIG_PATH}:/config/nextflow.config:ro"
)
if [ -n "$LICENSE_FILE" ]; then
    LICENSE_PATH="$(cd "$(dirname "$LICENSE_FILE")" && pwd)/$(basename "$LICENSE_FILE")"
    docker_args+=(-v "${LICENSE_PATH}:/fs_license.txt:ro")
fi
megflow_args=(--config /config/nextflow.config --input /input --output /output --fs_subjects_dir /smri --corpus --steps "$STEPS")
if [ -n "$LICENSE_FILE" ]; then megflow_args+=(--fs_license_file /fs_license.txt); fi
if [ "$RESUME" = true ]; then megflow_args+=(--resume); fi

printf 'MEGFlow corpus Docker run\nInput: %s\nOutput: %s\n' "$INPUT" "$OUTPUT"
print_command docker "${docker_args[@]}" "$IMAGE" "${megflow_args[@]}"
if [ "$DRY_RUN" = true ]; then exit 0; fi
if ! docker "${docker_args[@]}" "$IMAGE" "${megflow_args[@]}"; then
    printf 'Error: Docker launch failed\n' >&2
    exit 1
fi
printf 'Corpus report: %s/corpus_static_html_report/index.html\n' "$OUTPUT"
