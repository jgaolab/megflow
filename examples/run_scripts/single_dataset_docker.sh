#!/usr/bin/env bash
set -euo pipefail

die() {
    printf 'Error: %s\n' "$*" >&2
    exit 2
}

require_value() {
    [ "$#" -ge 2 ] && [ -n "$2" ] || die "$1 requires a value"
    case "$2" in --*) die "$1 requires a value (got option: $2)" ;; esac
}

print_command() {
    printf 'Command:'
    printf ' %q' "$@"
    printf '\n'
}

usage() {
    cat <<'EOF'
Usage: single_dataset_docker.sh --input DIR --output DIR [options]

Run one dataset through the official MEGFlow Docker entrypoint.

Options:
  --config FILE                 Config file (default: nextflow/quickstart.config)
  --smri DIR                    Writable FreeSurfer subjects directory
  --license FILE                FreeSurfer license file
  --image IMAGE                 Docker image (default: cplmeg/megflow:1.0.0)
  --steps VALUE                 Pipeline stage (default: meg_ica)
  --anat-method METHOD          freesurfer, deepprep, or pseudomri
  --resume                      Resume a previous run
  --dry-run                     Print the Docker command without running it
  --help                        Show this help
EOF
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INPUT=""
OUTPUT=""
CONFIG="${REPO_ROOT}/nextflow/quickstart.config"
SMRI=""
LICENSE_FILE=""
IMAGE="cplmeg/megflow:1.0.0"
STEPS="meg_ica"
ANAT_METHOD=""
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
        --anat-method) require_value "$@"; ANAT_METHOD="$2"; shift 2 ;;
        --resume) RESUME=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help) usage; exit 0 ;;
        *) die "unknown option: $1 (use --help)" ;;
    esac
done

[ -n "$INPUT" ] || die "--input is required"
[ -n "$OUTPUT" ] || die "--output is required"
[ -d "$INPUT" ] && [ -r "$INPUT" ] && [ -x "$INPUT" ] || die "input directory is not readable and traversable: $INPUT"
[ -f "$CONFIG" ] && [ -r "$CONFIG" ] || die "config file is not readable: $CONFIG"
if [ -n "$LICENSE_FILE" ]; then
    [ -f "$LICENSE_FILE" ] && [ -r "$LICENSE_FILE" ] || die "license file is not readable: $LICENSE_FILE"
fi
if [ -n "$SMRI" ] && [ -e "$SMRI" ] && { [ ! -d "$SMRI" ] || [ ! -w "$SMRI" ] || [ ! -x "$SMRI" ]; }; then
    die "smri path is not a writable and traversable directory: $SMRI"
fi
case "$ANAT_METHOD" in
    ""|freesurfer|deepprep|pseudomri) ;;
    *) die "--anat-method must be freesurfer, deepprep, or pseudomri" ;;
esac

if [ ! -e "$OUTPUT" ]; then
    mkdir -p "$OUTPUT" || die "could not create output directory: $OUTPUT"
fi
[ -d "$OUTPUT" ] && [ -w "$OUTPUT" ] && [ -x "$OUTPUT" ] || die "output directory is not writable and traversable: $OUTPUT"
if [ -n "$SMRI" ] && [ ! -e "$SMRI" ]; then
    mkdir -p "$SMRI" || die "could not create smri directory: $SMRI"
fi
if [ -n "$SMRI" ]; then [ -d "$SMRI" ] && [ -w "$SMRI" ] && [ -x "$SMRI" ] || die "smri path is not a writable and traversable directory: $SMRI"; fi

INPUT="$(cd "$INPUT" && pwd -P)"
OUTPUT="$(cd "$OUTPUT" && pwd -P)"
if [ -n "$SMRI" ]; then SMRI="$(cd "$SMRI" && pwd -P)"; fi
if [ "$DRY_RUN" != true ]; then command -v docker >/dev/null 2>&1 || die "Docker is not available on PATH"; fi

CONFIG_PATH="$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")"
docker_args=(run --rm)
if [ -t 0 ] && [ -t 1 ]; then docker_args+=(-it); else docker_args+=(-i); fi
docker_args+=(
    -v "${INPUT}:/input:ro"
    -v "${OUTPUT}:/output"
    -v "${CONFIG_PATH}:/config/nextflow.config:ro"
)
if [ -n "$SMRI" ]; then docker_args+=(-v "${SMRI}:/smri"); fi
if [ -n "$LICENSE_FILE" ]; then
    LICENSE_PATH="$(cd "$(dirname "$LICENSE_FILE")" && pwd)/$(basename "$LICENSE_FILE")"
    docker_args+=(-v "${LICENSE_PATH}:/fs_license.txt:ro")
fi
megflow_args=(--config /config/nextflow.config --input /input --output /output --steps "$STEPS")
if [ -n "$SMRI" ]; then megflow_args+=(--fs_subjects_dir /smri); fi
if [ -n "$LICENSE_FILE" ]; then megflow_args+=(--fs_license_file /fs_license.txt); fi
if [ -n "$ANAT_METHOD" ]; then megflow_args+=(--anat-method "$ANAT_METHOD"); fi
if [ "$RESUME" = true ]; then megflow_args+=(--resume); fi

printf 'MEGFlow single-dataset Docker run\nInput: %s\nOutput: %s\n' "$INPUT" "$OUTPUT"
print_command docker "${docker_args[@]}" "$IMAGE" "${megflow_args[@]}"
if [ "$DRY_RUN" = true ]; then exit 0; fi
if ! docker "${docker_args[@]}" "$IMAGE" "${megflow_args[@]}"; then
    printf 'Error: Docker launch failed\n' >&2
    exit 1
fi
printf 'Report: %s/static_html_report/index.html\n' "$OUTPUT"
