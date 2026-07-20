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
    case "$2" in
        --*)
            error "Option $1 requires a value (got option: $2)."
            exit 2
            ;;
    esac
}

resolve_path_allow_missing() {
    local target="$1"
    local suffix=""
    local component
    local parent
    local resolved

    while [ ! -e "$target" ] && [ ! -L "$target" ]; do
        component="$(basename "$target")"
        parent="$(dirname "$target")"
        [ "$parent" != "$target" ] || return 1
        suffix="/${component}${suffix}"
        target="$parent"
    done
    [ -d "$target" ] || return 1
    resolved="$(cd -P "$target" && pwd)" || return 1
    printf '%s%s\n' "$resolved" "$suffix"
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

RESOLVED_DOCS_DIR="$(cd -P "$REPO_ROOT/docs" && pwd)"
EXPECTED_DOCS_BUILD_ROOT="$RESOLVED_DOCS_DIR/build"
if ! RESOLVED_DOCS_BUILD_ROOT="$(resolve_path_allow_missing "$DOCS_BUILD_ROOT")"; then
    error "Could not resolve documentation build root: $DOCS_BUILD_ROOT"
    exit 2
fi
if [ "$RESOLVED_DOCS_BUILD_ROOT" != "$EXPECTED_DOCS_BUILD_ROOT" ]; then
    error "Documentation build root must not resolve outside $RESOLVED_DOCS_DIR."
    exit 2
fi
if ! RESOLVED_OUTPUT="$(resolve_path_allow_missing "$OUTPUT_PATH")"; then
    error "Could not safely resolve documentation output: $OUTPUT_PATH"
    exit 2
fi
case "$RESOLVED_OUTPUT" in
    "$RESOLVED_DOCS_BUILD_ROOT"/*) OUTPUT_PATH="$RESOLVED_OUTPUT" ;;
    *)
        error "Documentation output must resolve under $RESOLVED_DOCS_BUILD_ROOT."
        exit 2
        ;;
esac

if [ ! -d "$DOCS_SOURCE" ] || [ ! -r "$DOCS_SOURCE" ] || [ ! -x "$DOCS_SOURCE" ]; then
    error "Documentation source is not readable and traversable: $DOCS_SOURCE"
    exit 2
fi
if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    error 'Python is required.'
    exit 2
fi
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

printf 'Documentation command:'
printf ' %q' "$PYTHON_BIN" "${SPHINX_ARGS[@]}"
printf '\nOutput: %s\n' "$OUTPUT_PATH"
if ! "$PYTHON_BIN" "${SPHINX_ARGS[@]}"; then
    error 'Documentation build failed.'
    exit 1
fi

printf 'Documentation output: %s\n' "$OUTPUT_PATH"
