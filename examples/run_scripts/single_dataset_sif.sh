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
Usage: single_dataset_sif.sh --input DIR --output DIR --sif FILE [options]

Run one dataset from the same MEGFlow SIF with Apptainer or SingularityCE.

Options:
  --config FILE                 Config file (default: nextflow/quickstart.config)
  --smri DIR                    Writable FreeSurfer subjects directory
  --license FILE                FreeSurfer license file
  --sif FILE                    MEGFlow SIF image (required)
  --runtime VALUE               auto, apptainer, or singularity (default: auto)
  --runtime-bin PATH_OR_COMMAND Explicit runtime executable; overrides --runtime
  --steps VALUE                 Pipeline stage (default: meg_ica)
  --anat-method METHOD          freesurfer, deepprep, or pseudomri
  --resume                      Resume a previous run
  --dry-run                     Print the SIF command without running it
  --help                        Show this help
EOF
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INPUT=""
OUTPUT=""
SIF=""
CONFIG="${REPO_ROOT}/nextflow/quickstart.config"
SMRI=""
LICENSE_FILE=""
RUNTIME="auto"
RUNTIME_OVERRIDE=""
STEPS="meg_ica"
ANAT_METHOD=""
RESUME=false
DRY_RUN=false

while [ "$#" -gt 0 ]; do
    case "$1" in
        --input) require_value "$@"; INPUT="$2"; shift 2 ;;
        --output) require_value "$@"; OUTPUT="$2"; shift 2 ;;
        --sif) require_value "$@"; SIF="$2"; shift 2 ;;
        --config) require_value "$@"; CONFIG="$2"; shift 2 ;;
        --smri) require_value "$@"; SMRI="$2"; shift 2 ;;
        --license) require_value "$@"; LICENSE_FILE="$2"; shift 2 ;;
        --runtime) require_value "$@"; RUNTIME="$2"; shift 2 ;;
        --runtime-bin) require_value "$@"; RUNTIME_OVERRIDE="$2"; shift 2 ;;
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
[ -n "$SIF" ] || die "--sif is required"
[ -d "$INPUT" ] && [ -r "$INPUT" ] && [ -x "$INPUT" ] || die "input directory is not readable and traversable: $INPUT"
[ -f "$SIF" ] && [ -r "$SIF" ] || die "SIF image is not readable: $SIF"
[ -f "$CONFIG" ] && [ -r "$CONFIG" ] || die "config file is not readable: $CONFIG"
if [ -n "$LICENSE_FILE" ]; then
    [ -f "$LICENSE_FILE" ] && [ -r "$LICENSE_FILE" ] || die "license file is not readable: $LICENSE_FILE"
fi
if [ -n "$SMRI" ] && [ -e "$SMRI" ] && { [ ! -d "$SMRI" ] || [ ! -w "$SMRI" ] || [ ! -x "$SMRI" ]; }; then
    die "smri path is not a writable and traversable directory: $SMRI"
fi
case "$RUNTIME" in
    auto|apptainer|singularity) ;;
    *) die "--runtime must be auto, apptainer, or singularity" ;;
esac
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
if [ -n "$SMRI" ]; then
    [ -d "$SMRI" ] && [ -w "$SMRI" ] && [ -x "$SMRI" ] || die "smri path is not a writable and traversable directory: $SMRI"
fi

INPUT="$(cd "$INPUT" && pwd -P)"
OUTPUT="$(cd "$OUTPUT" && pwd -P)"
SIF="$(cd "$(dirname "$SIF")" && pwd -P)/$(basename "$SIF")"
CONFIG="$(cd "$(dirname "$CONFIG")" && pwd -P)/$(basename "$CONFIG")"
if [ -n "$SMRI" ]; then SMRI="$(cd "$SMRI" && pwd -P)"; fi
if [ -n "$LICENSE_FILE" ]; then
    LICENSE_FILE="$(cd "$(dirname "$LICENSE_FILE")" && pwd -P)/$(basename "$LICENSE_FILE")"
fi

if [ -n "$RUNTIME_OVERRIDE" ]; then
    RUNTIME_BIN="$RUNTIME_OVERRIDE"
elif [ "$RUNTIME" = "apptainer" ] || [ "$RUNTIME" = "singularity" ]; then
    RUNTIME_BIN="$RUNTIME"
elif command -v apptainer >/dev/null 2>&1; then
    RUNTIME_BIN="apptainer"
elif command -v singularity >/dev/null 2>&1; then
    RUNTIME_BIN="singularity"
elif [ "$DRY_RUN" = true ]; then
    RUNTIME_BIN="apptainer"
else
    die "neither Apptainer nor SingularityCE is available on PATH; use --runtime-bin for a custom installation path"
fi

if [ "$DRY_RUN" != true ]; then
    if [[ "$RUNTIME_BIN" == */* ]]; then
        [ -x "$RUNTIME_BIN" ] || die "runtime executable is not available: $RUNTIME_BIN"
    else
        command -v "$RUNTIME_BIN" >/dev/null 2>&1 || die "runtime executable is not available on PATH: $RUNTIME_BIN"
    fi
fi
if [[ "$RUNTIME_BIN" == */* ]] && [ -e "$RUNTIME_BIN" ]; then
    RUNTIME_BIN="$(cd "$(dirname "$RUNTIME_BIN")" && pwd -P)/$(basename "$RUNTIME_BIN")"
fi

runtime_args=(
    run
    --cleanenv
    --bind "${INPUT}:/input:ro"
    --bind "${OUTPUT}:/output"
    --bind "${CONFIG}:/config/nextflow.config:ro"
)
if [ -n "$SMRI" ]; then runtime_args+=(--bind "${SMRI}:/smri"); fi
if [ -n "$LICENSE_FILE" ]; then runtime_args+=(--bind "${LICENSE_FILE}:/fs_license.txt:ro"); fi

megflow_args=(--config /config/nextflow.config --input /input --output /output --steps "$STEPS")
if [ -n "$SMRI" ]; then megflow_args+=(--fs_subjects_dir /smri); fi
if [ -n "$LICENSE_FILE" ]; then megflow_args+=(--fs_license_file /fs_license.txt); fi
if [ -n "$ANAT_METHOD" ]; then megflow_args+=(--anat-method "$ANAT_METHOD"); fi
if [ "$RESUME" = true ]; then megflow_args+=(--resume); fi

printf 'MEGFlow single-dataset SIF run\nRuntime: %s\nSIF: %s\nInput: %s\nOutput: %s\n' \
    "$RUNTIME_BIN" "$SIF" "$INPUT" "$OUTPUT"
print_command "$RUNTIME_BIN" "${runtime_args[@]}" "$SIF" "${megflow_args[@]}"
if [ "$DRY_RUN" = true ]; then exit 0; fi
if ! "$RUNTIME_BIN" "${runtime_args[@]}" "$SIF" "${megflow_args[@]}"; then
    printf 'Error: SIF runtime launch failed\n' >&2
    exit 1
fi
printf 'Report: %s/static_html_report/index.html\n' "$OUTPUT"
