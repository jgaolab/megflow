#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: rm_none_docker.sh [--yes] [--help]

Preview dangling Docker image IDs. Pass --yes to remove the listed IDs.
EOF
}

error() {
    printf 'Error: %s\n' "$*" >&2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APPLY=false

while [ "$#" -gt 0 ]; do
    case "$1" in
        --yes)
            APPLY=true
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

if ! command -v docker >/dev/null 2>&1; then
    error 'Docker client is required.'
    exit 2
fi
DOCKER_BIN="$(command -v docker)"
if ! DANGLING_IDS="$("$DOCKER_BIN" images --filter dangling=true --quiet)"; then
    error 'Could not list dangling Docker image IDs.'
    exit 1
fi

if [ -z "$DANGLING_IDS" ]; then
    printf 'No dangling Docker images found.\n'
    exit 0
fi

printf 'Dangling Docker image IDs:\n%s\n' "$DANGLING_IDS"
if [ "$APPLY" != true ]; then
    printf 'Preview only. Re-run with --yes to remove these image IDs.\n'
    exit 0
fi

DELETION_FAILED=false
while IFS= read -r image_id; do
    if [ -n "$image_id" ] && ! "$DOCKER_BIN" rmi "$image_id"; then
        DELETION_FAILED=true
    fi
done <<< "$DANGLING_IDS"
if [ "$DELETION_FAILED" = true ]; then
    error 'One or more dangling Docker images could not be removed.'
    exit 1
fi

printf 'Removed dangling Docker image IDs.\n'
