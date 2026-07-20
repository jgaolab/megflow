#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: docker2sif.sh [options]

Convert a local Docker image to a SIF file without pulling or building images.

Options:
  --image IMAGE                       Docker image (default: cplmeg/megflow:local)
  --output FILE                       SIF output file (default: sanitized image name with .sif)
  --runtime auto|apptainer|singularity Runtime selection (default: auto)
  --force                             Allow overwriting an existing output file
  --dry-run                           Print the runtime command without running it
  --help                              Show this help message
EOF
}

error() {
    printf 'Error: %s\n' "$*" >&2
}

require_value() {
    if [ "$#" -lt 2 ] || [ -z "$2" ]; then
        error "Option $1 requires a value."
        exit 2
    fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
IMAGE="cplmeg/megflow:local"
OUTPUT=""
RUNTIME="auto"
FORCE=false
DRY_RUN=false

while [ "$#" -gt 0 ]; do
    case "$1" in
        --image)
            require_value "$@"
            IMAGE="$2"
            shift 2
            ;;
        --output)
            require_value "$@"
            OUTPUT="$2"
            shift 2
            ;;
        --runtime)
            require_value "$@"
            RUNTIME="$2"
            shift 2
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            usage >&2
            exit 2
            ;;
    esac
done

case "$RUNTIME" in
    auto|apptainer|singularity) ;;
    *)
        error "Unsupported runtime: $RUNTIME"
        exit 2
        ;;
esac

if [ -z "$OUTPUT" ]; then
    SANITIZED_IMAGE="${IMAGE//\//_}"
    SANITIZED_IMAGE="${SANITIZED_IMAGE//:/_}"
    OUTPUT="$SANITIZED_IMAGE.sif"
fi
case "$OUTPUT" in
    /*) OUTPUT_PATH="$OUTPUT" ;;
    *) OUTPUT_PATH="$REPO_ROOT/$OUTPUT" ;;
esac
OUTPUT_DIR="$(dirname "$OUTPUT_PATH")"
if [ ! -d "$OUTPUT_DIR" ] || [ ! -w "$OUTPUT_DIR" ]; then
    error "Output directory is not writable: $OUTPUT_DIR"
    exit 2
fi
if [ -e "$OUTPUT_PATH" ] && [ "$FORCE" != true ]; then
    error "Output already exists; use --force to replace it: $OUTPUT_PATH"
    exit 2
fi

RUNTIME_BIN=""
if [ "$RUNTIME" = auto ] || [ "$RUNTIME" = apptainer ]; then
    if command -v apptainer >/dev/null 2>&1; then
        RUNTIME_BIN="$(command -v apptainer)"
    elif [ "$RUNTIME" = apptainer ]; then
        error 'Apptainer is required but was not found on PATH.'
        exit 2
    fi
fi
if [ -z "$RUNTIME_BIN" ] && { [ "$RUNTIME" = auto ] || [ "$RUNTIME" = singularity ]; }; then
    if command -v singularity >/dev/null 2>&1; then
        RUNTIME_BIN="$(command -v singularity)"
    else
        error 'Neither Apptainer nor Singularity is available on PATH.'
        exit 2
    fi
fi

BUILD_ARGS=(build)
if [ "$FORCE" = true ]; then
    BUILD_ARGS+=(--force)
fi
BUILD_ARGS+=("$OUTPUT_PATH" "docker-daemon://$IMAGE")

printf 'SIF conversion command:'
printf ' %q' "$RUNTIME_BIN" "${BUILD_ARGS[@]}"
printf '\nOutput: %s\n' "$OUTPUT_PATH"
if [ "$DRY_RUN" = true ]; then
    printf 'Dry run: no Docker or SIF runtime command was invoked.\n'
    exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
    error 'Docker client is required to inspect the local image.'
    exit 2
fi
DOCKER_BIN="$(command -v docker)"
if ! "$DOCKER_BIN" image inspect "$IMAGE" >/dev/null 2>&1; then
    error "Local Docker image was not found: $IMAGE"
    exit 2
fi
if ! "$RUNTIME_BIN" "${BUILD_ARGS[@]}"; then
    error 'SIF conversion failed.'
    exit 1
fi

printf 'SIF output: %s\n' "$OUTPUT_PATH"
