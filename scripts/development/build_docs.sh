#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: build_docs.sh [options]

Build the HTML documentation from the repository root.

Options:
  --clean       Remove the selected output directory before building
  --strict      Treat Sphinx warnings as errors and keep going
  --output DIR  HTML output directory under docs/build (default: docs/build/html)
  --help        Show this help message
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
DOCS_SOURCE="$REPO_ROOT/docs/source"
DOCS_BUILD_ROOT="$REPO_ROOT/docs/build"
OUTPUT="docs/build/html"
CLEAN=false
STRICT=false

while [ "$#" -gt 0 ]; do
    case "$1" in
        --clean)
            CLEAN=true
            shift
            ;;
        --strict)
            STRICT=true
            shift
            ;;
        --output)
            require_value "$@"
            OUTPUT="$2"
            shift 2
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

case "$OUTPUT" in
    /*) OUTPUT_PATH="$OUTPUT" ;;
    *) OUTPUT_PATH="$REPO_ROOT/$OUTPUT" ;;
esac

case "$OUTPUT_PATH" in
    */../*|*/..)
        error 'Documentation output must not traverse outside docs/build.'
        exit 2
        ;;
esac
case "$OUTPUT_PATH" in
    "$DOCS_BUILD_ROOT"/*) ;;
    *)
        error "Documentation output must be under $DOCS_BUILD_ROOT."
        exit 2
        ;;
esac

if [ "$CLEAN" = true ] && [ -e "$OUTPUT_PATH" ]; then
    RESOLVED_DOCS_BUILD_ROOT="$(cd -P "$DOCS_BUILD_ROOT" && pwd)"
    RESOLVED_OUTPUT_PARENT="$(cd -P "$(dirname "$OUTPUT_PATH")" && pwd)"
    RESOLVED_OUTPUT="$RESOLVED_OUTPUT_PARENT/$(basename "$OUTPUT_PATH")"
    case "$RESOLVED_OUTPUT" in
        "$RESOLVED_DOCS_BUILD_ROOT"/*) OUTPUT_PATH="$RESOLVED_OUTPUT" ;;
        *)
            error "Documentation output must resolve under $RESOLVED_DOCS_BUILD_ROOT."
            exit 2
            ;;
    esac
fi

if [ ! -d "$DOCS_SOURCE" ]; then
    error "Documentation source not found: $DOCS_SOURCE"
    exit 2
fi
if ! command -v "${PYTHON:-python}" >/dev/null 2>&1; then
    error 'Python is required.'
    exit 2
fi
PYTHON_BIN="$(command -v "${PYTHON:-python}")"
if ! "$PYTHON_BIN" -c 'import sphinx' >/dev/null 2>&1; then
    error 'The active Python environment must provide Sphinx.'
    exit 2
fi

if [ "$CLEAN" = true ] && [ -e "$OUTPUT_PATH" ]; then
    rm -rf -- "$OUTPUT_PATH"
fi

SPHINX_ARGS=(-m sphinx -b html)
if [ "$STRICT" = true ]; then
    SPHINX_ARGS+=(-W --keep-going)
fi
SPHINX_ARGS+=("$DOCS_SOURCE" "$OUTPUT_PATH")

printf 'Documentation command: python'
printf ' %q' "${SPHINX_ARGS[@]}"
printf '\nOutput: %s\n' "$OUTPUT_PATH"
if ! "$PYTHON_BIN" "${SPHINX_ARGS[@]}"; then
    error 'Documentation build failed.'
    exit 1
fi

printf 'Documentation output: %s\n' "$OUTPUT_PATH"
