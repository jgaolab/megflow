#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE="${IMAGE:-cplmeg/megflow:1.0.0}"
PROJECT_ROOT="${PROJECT_ROOT:-$SCRIPT_DIR}"
DATASETS_ROOT="/data/liaopan/datasets"
CONFIG="${CONFIG:-$PROJECT_ROOT/nextflow/nextflow_multi_dataset_demo.config}"
PIPELINE="${PIPELINE:-$PROJECT_ROOT/nextflow/megflow.nf}"
OUTPUT_ROOT="$DATASETS_ROOT/megflow_multi_dataset_demo_3datasets"
CONTAINER_NAME="${CONTAINER_NAME:-megflow-multidataset-demo}"
PROFILE="${PROFILE:-strict}"
RESUME="${RESUME--resume}"

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is not available on PATH." >&2
    exit 1
fi

for required_path in "$PROJECT_ROOT" "$DATASETS_ROOT" "$CONFIG" "$PIPELINE"; do
    if [ ! -e "$required_path" ]; then
        echo "Required path does not exist: $required_path" >&2
        exit 1
    fi
done

if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    echo "Container name is already in use: $CONTAINER_NAME" >&2
    echo "Stop or remove that container, or set CONTAINER_NAME to another value." >&2
    exit 1
fi

docker_flags=(--rm --init --name "$CONTAINER_NAME")
if [ -t 0 ] && [ -t 1 ]; then
    docker_flags+=(-it)
    nextflow_ansi_log=true
else
    docker_flags+=(-i)
    nextflow_ansi_log=false
fi

nextflow_cmd=(nextflow -C "$CONFIG" run "$PIPELINE")
if [ -n "$RESUME" ]; then
    nextflow_cmd+=("$RESUME")
fi
nextflow_cmd+=(-profile "$PROFILE")

echo "============================================================"
echo "MEGFlow multi-dataset Docker run"
echo "Image:          $IMAGE"
echo "Config:         $CONFIG"
echo "Pipeline:       $PIPELINE"
echo "Datasets root:  $DATASETS_ROOT"
echo "Output root:    $OUTPUT_ROOT"
echo "Profile:        $PROFILE"
echo "Resume:         ${RESUME:-disabled}"
echo "============================================================"

docker run "${docker_flags[@]}" \
    --user "$(id -u):$(id -g)" \
    --shm-size=16g \
    --entrypoint /bin/bash \
    -e HOME=/tmp/megflow_home \
    -e XDG_CACHE_HOME=/tmp/megflow_cache \
    -e NXF_HOME=/tmp/megflow_nextflow \
    -e NXF_TEMP=/tmp \
    -e TMPDIR=/tmp \
    -e NUMBA_CACHE_DIR=/tmp/NUMBA_CACHE_DIR \
    -e MPLCONFIGDIR=/tmp/MPLCONFIGDIR \
    -e NXF_ANSI_LOG="$nextflow_ansi_log" \
    -v "$PROJECT_ROOT:$PROJECT_ROOT" \
    -v "$DATASETS_ROOT:$DATASETS_ROOT" \
    -w "$PROJECT_ROOT" \
    "$IMAGE" \
    -lc 'exec "$@"' bash "${nextflow_cmd[@]}"

echo "Dataset reports: $OUTPUT_ROOT/datasets/*/static_html_report/index.html"
echo "Corpus report:   $OUTPUT_ROOT/corpus_static_html_report/index.html"
