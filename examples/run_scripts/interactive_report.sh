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
Usage: interactive_report.sh --output DIR [options]

Open MEGFlow's Streamlit report viewer for existing output.

Options:
  --smri DIR                    Optional anatomy directory to mount read-only
  --image IMAGE                 Docker image (default: cplmeg/megflow:latest)
  --port PORT                   Viewer port (default: 8501)
  --dry-run                     Print the Docker command without running it
  --help                        Show this help
EOF
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUTPUT="${MEGFLOW_OUTPUT:-}"
SMRI="${MEGFLOW_SMRI:-}"
IMAGE="${MEGFLOW_IMAGE:-cplmeg/megflow:latest}"
PORT="${MEGFLOW_PORT:-8501}"
DRY_RUN=false

while [ "$#" -gt 0 ]; do
    case "$1" in
        --output) require_value "$@"; OUTPUT="$2"; shift 2 ;;
        --smri) require_value "$@"; SMRI="$2"; shift 2 ;;
        --image) require_value "$@"; IMAGE="$2"; shift 2 ;;
        --port) require_value "$@"; PORT="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help) usage; exit 0 ;;
        *) die "unknown option: $1 (use --help)" ;;
    esac
done

[ -n "$OUTPUT" ] || die "--output is required"
[ -d "$OUTPUT" ] && [ -r "$OUTPUT" ] && [ -w "$OUTPUT" ] || die "output directory must exist and be writable: $OUTPUT"
if [ -n "$SMRI" ]; then [ -d "$SMRI" ] && [ -r "$SMRI" ] || die "smri directory is not readable: $SMRI"; fi
case "$PORT" in ""|*[!0-9]*) die "--port must be an integer from 1 through 65535" ;; esac
PORT_NUMBER="$PORT"
while [ "${PORT_NUMBER#0}" != "$PORT_NUMBER" ]; do PORT_NUMBER="${PORT_NUMBER#0}"; done
[ -n "$PORT_NUMBER" ] || PORT_NUMBER=0
[ "$PORT_NUMBER" -ge 1 ] && [ "$PORT_NUMBER" -le 65535 ] || die "--port must be an integer from 1 through 65535"

if [ "$DRY_RUN" != true ]; then command -v docker >/dev/null 2>&1 || die "Docker is not available on PATH"; fi
docker_args=(run --rm)
if [ -t 0 ] && [ -t 1 ]; then docker_args+=(-it); else docker_args+=(-i); fi
docker_args+=(-p "${PORT}:${PORT}" -v "${OUTPUT}:/output")
if [ -n "$SMRI" ]; then docker_args+=(-v "${SMRI}:/smri:ro"); fi

printf 'MEGFlow interactive report\nOutput: %s\nViewer: http://localhost:%s\n' "$OUTPUT" "$PORT"
print_command docker "${docker_args[@]}" "$IMAGE" -r
if [ "$DRY_RUN" = true ]; then exit 0; fi
docker "${docker_args[@]}" "$IMAGE" -r
