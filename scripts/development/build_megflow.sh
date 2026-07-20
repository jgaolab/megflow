#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: build_megflow.sh [options]

Build the MEGFlow development Docker image from the repository root.

Options:
  --image NAME       Image repository (default: cplmeg/megflow)
  --tag TAG          Image tag (default: local)
  --dockerfile FILE  Dockerfile relative to the repository root (default: megflow.Dockerfile)
  --platform VALUE   Docker target platform
  --no-cache         Disable Docker build cache
  --dry-run          Print the Docker build command without running Docker
  --help             Show this help message
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
IMAGE="cplmeg/megflow"
TAG="local"
DOCKERFILE="megflow.Dockerfile"
PLATFORM=""
NO_CACHE=false
DRY_RUN=false

while [ "$#" -gt 0 ]; do
    case "$1" in
        --image)
            require_value "$@"
            IMAGE="$2"
            shift 2
            ;;
        --tag)
            require_value "$@"
            TAG="$2"
            shift 2
            ;;
        --dockerfile)
            require_value "$@"
            DOCKERFILE="$2"
            shift 2
            ;;
        --platform)
            require_value "$@"
            PLATFORM="$2"
            shift 2
            ;;
        --no-cache)
            NO_CACHE=true
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

case "$DOCKERFILE" in
    /*) DOCKERFILE_PATH="$DOCKERFILE" ;;
    *) DOCKERFILE_PATH="$REPO_ROOT/$DOCKERFILE" ;;
esac

if [ ! -f "$DOCKERFILE_PATH" ]; then
    error "Dockerfile not found: $DOCKERFILE_PATH"
    exit 2
fi
if [ ! -d "$REPO_ROOT" ]; then
    error "Build context not found: $REPO_ROOT"
    exit 2
fi

BUILD_ARGS=(build -f "$DOCKERFILE_PATH" -t "$IMAGE:$TAG")
if [ -n "$PLATFORM" ]; then
    BUILD_ARGS+=(--platform "$PLATFORM")
fi
if [ "$NO_CACHE" = true ]; then
    BUILD_ARGS+=(--no-cache)
fi
BUILD_ARGS+=("$REPO_ROOT")

printf 'Docker build command: docker'
printf ' %q' "${BUILD_ARGS[@]}"
printf '\nImage: %s:%s\n' "$IMAGE" "$TAG"

if [ "$DRY_RUN" = true ]; then
    printf 'Dry run: Docker was not invoked.\n'
    exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
    error 'Docker client is required.'
    exit 2
fi
DOCKER_BIN="$(command -v docker)"
if ! "$DOCKER_BIN" info >/dev/null 2>&1; then
    error 'Docker daemon is unavailable.'
    exit 1
fi
if ! "$DOCKER_BIN" "${BUILD_ARGS[@]}"; then
    error 'Docker build failed.'
    exit 1
fi

printf 'Built image: %s:%s\n' "$IMAGE" "$TAG"
