#!/usr/bin/env bash
set -euo pipefail

# Compatibility wrapper retained at its historical path. It now launches the
# Docker corpus entrypoint and uses the v2 params.megflow profile system.
#
# Example:
#   DATASET_ROOT=/data/corpus \
#   OUTPUT_ROOT=/data/corpus_megflow \
#   FS_SUBJECTS_ROOT=/data/corpus_smri \
#   CONFIG=/data/corpus.config \
#   bash scripts/cohort-dev/run_MultiDatasets.sh

IMAGE="${IMAGE:-cplmeg/megflow:1.0.0}"
CONFIG="${CONFIG:-nextflow/nextflow_for_docker.config}"
DATASET_ROOT="${DATASET_ROOT:-/path/to/corpus_INPUT}"
OUTPUT_ROOT="${OUTPUT_ROOT:-/path/to/corpus_OUTPUT}"
FS_SUBJECTS_ROOT="${FS_SUBJECTS_ROOT:-${OUTPUT_ROOT}/smri}"
FS_LICENSE_FILE="${FS_LICENSE_FILE:-}"
STEPS="${STEPS:-meg_ica}"
RESUME="${RESUME:-true}"

if [ ! -d "$DATASET_ROOT" ]; then
    echo "DATASET_ROOT does not exist: $DATASET_ROOT" >&2
    exit 1
fi

if [ ! -f "$CONFIG" ]; then
    echo "CONFIG does not exist: $CONFIG" >&2
    exit 1
fi

if ! find "$DATASET_ROOT" -mindepth 1 -maxdepth 1 -type d -print -quit | grep -q .; then
    echo "No dataset subdirectories were found under: $DATASET_ROOT" >&2
    exit 1
fi

mkdir -p "$OUTPUT_ROOT" "$FS_SUBJECTS_ROOT"

docker_args=(
    run --rm -it
    -v "${DATASET_ROOT}:/input:ro"
    -v "${OUTPUT_ROOT}:/output"
    -v "${FS_SUBJECTS_ROOT}:/smri"
    -v "$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG"):/program/nextflow/nextflow.config:ro"
)

megflow_args=(
    -i /input
    -o /output
    --fs_subjects_dir /smri
    --corpus
    --steps "$STEPS"
)

if [ -n "$FS_LICENSE_FILE" ]; then
    if [ ! -f "$FS_LICENSE_FILE" ]; then
        echo "FS_LICENSE_FILE does not exist: $FS_LICENSE_FILE" >&2
        exit 1
    fi
    docker_args+=(
        -v "$(cd "$(dirname "$FS_LICENSE_FILE")" && pwd)/$(basename "$FS_LICENSE_FILE"):/fs_license.txt:ro"
    )
    megflow_args+=(--fs_license_file /fs_license.txt)
fi

if [ "$RESUME" = "true" ]; then
    megflow_args+=(--resume)
fi

echo "============================================================"
echo "Corpus root:          $DATASET_ROOT"
echo "Output root:          $OUTPUT_ROOT"
echo "MRI root:             $FS_SUBJECTS_ROOT"
echo "Config:               $CONFIG"
echo "Image:                $IMAGE"
echo "Steps:                $STEPS"
echo "============================================================"

docker "${docker_args[@]}" "$IMAGE" "${megflow_args[@]}"

echo "Corpus report: ${OUTPUT_ROOT}/corpus_static_html_report/index.html"
