#!/usr/bin/env bash
set -euo pipefail

# Cohort runner: each immediate child directory under DATASET_ROOT is treated as
# one MEGPrep dataset. Nextflow expands those datasets into a cohort channel,
# runs one shared process DAG, and then builds a cohort-level static HTML report
# from the isolated dataset outputs.
#
# Paths below are placeholders. Override before running, for example:
#   DATASET_ROOT=/path/to/megqc_cohort INPUT \
#   OUTPUT_ROOT=/path/to/megqc_cohort_OUTPUT \
#   bash run_MultiDatasets.sh

PIPELINE="${PIPELINE:-nextflow/meg_anat_pipeline_for_docker.nf}"
CONFIG="${CONFIG:-nextflow/nextflow_for_cohort.config}"
DATASET_ROOT="${DATASET_ROOT:-/path/to/megqc_cohort_INPUT}"
OUTPUT_ROOT="${OUTPUT_ROOT:-/path/to/megqc_cohort_OUTPUT}"
FS_SUBJECTS_ROOT="${FS_SUBJECTS_ROOT:-${OUTPUT_ROOT}/smri}"
T1_ROOT="${T1_ROOT:-}"
STEPS="${STEPS:-meg_ica}"
RESUME="${RESUME:--resume}"
STATIC_TASK_LOG_MODE="${STATIC_TASK_LOG_MODE:-}"
STATIC_ARTIFACT_OVERVIEW_DURATION="${STATIC_ARTIFACT_OVERVIEW_DURATION:-}"

read_static_task_log_mode() {
    [ -f "$CONFIG" ] || return 0
    sed -n 's/^[[:space:]]*static_task_log_mode[[:space:]]*=[[:space:]]*["'\'']\([^"'\'']*\)["'\''].*/\1/p' "$CONFIG" | head -n 1
}

read_static_artifact_overview_duration() {
    [ -f "$CONFIG" ] || return 0
    sed -n 's/^[[:space:]]*static_artifact_overview_duration[[:space:]]*=[[:space:]]*\([^[:space:]]*\).*/\1/p' "$CONFIG" | head -n 1
}

STATIC_TASK_LOG_MODE="${STATIC_TASK_LOG_MODE:-$(read_static_task_log_mode)}"
STATIC_TASK_LOG_MODE="${STATIC_TASK_LOG_MODE:-failed}"
STATIC_ARTIFACT_OVERVIEW_DURATION="${STATIC_ARTIFACT_OVERVIEW_DURATION:-$(read_static_artifact_overview_duration)}"
STATIC_ARTIFACT_OVERVIEW_DURATION="${STATIC_ARTIFACT_OVERVIEW_DURATION:-200.0}"
case "$STATIC_TASK_LOG_MODE" in
    failed|all-command-log|none) ;;
    *)
        echo "Invalid STATIC_TASK_LOG_MODE: $STATIC_TASK_LOG_MODE (expected failed, all-command-log, or none)" >&2
        exit 1
        ;;
esac

if [ ! -d "$DATASET_ROOT" ]; then
    echo "DATASET_ROOT does not exist: $DATASET_ROOT" >&2
    exit 1
fi

mkdir -p "$OUTPUT_ROOT/datasets" "$OUTPUT_ROOT/work" "$FS_SUBJECTS_ROOT"

if ! find "$DATASET_ROOT" -mindepth 1 -maxdepth 1 -type d -print -quit | grep -q .; then
    echo "No dataset subdirectories were found under: $DATASET_ROOT" >&2
    exit 1
fi

PIPELINE_ABS="$(cd "$(dirname "$PIPELINE")" && pwd)/$(basename "$PIPELINE")"
CONFIG_ABS="$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")"

echo "============================================================"
echo "Cohort root:          $DATASET_ROOT"
echo "Output root:          $OUTPUT_ROOT"
echo "MRI root:             $FS_SUBJECTS_ROOT"
echo "Pipeline:             $PIPELINE_ABS"
echo "Config:               $CONFIG_ABS"
echo "Steps:                $STEPS"
echo "Task log mode:        $STATIC_TASK_LOG_MODE"
echo "Artifact overview:    ${STATIC_ARTIFACT_OVERVIEW_DURATION}s"
if [ -n "$T1_ROOT" ]; then
    echo "T1 root:              $T1_ROOT"
else
    echo "T1 root:              <per dataset input>"
fi
echo "============================================================"

nextflow run "$PIPELINE_ABS" \
    -c "$CONFIG_ABS" \
    -w "${OUTPUT_ROOT}/work/cohort_driver" \
    --cohort true \
    --cohort_t1_root "$T1_ROOT" \
    --steps "$STEPS" \
    --dataset_dir "$DATASET_ROOT" \
    --output_dir "$OUTPUT_ROOT" \
    --preproc_dir "${OUTPUT_ROOT}/preprocessed" \
    --fs_subjects_dir "$FS_SUBJECTS_ROOT" \
    --static_task_log_mode "$STATIC_TASK_LOG_MODE" \
    --static_artifact_overview_duration "$STATIC_ARTIFACT_OVERVIEW_DURATION" \
    -with-report "${OUTPUT_ROOT}/cohort_report.html" \
    -with-timeline "${OUTPUT_ROOT}/cohort_timeline.html" \
    -with-trace "${OUTPUT_ROOT}/cohort_trace.txt" \
    $RESUME

echo "Cohort report: ${OUTPUT_ROOT}/cohort_static_html_report/index.html"
