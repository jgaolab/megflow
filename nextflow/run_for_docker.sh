#!/bin/bash  
# Usage:
#$ bash run_for_docker.sh -i /data/liaopan/datasets/Holmes_cn_single/raw --fs_license_file /data/liaopan/megflow/license.txt --fs_subjects_dir /data/liaopan/datasets/Holmes_cn/smri
#  bash run_for_docker.sh -i /data/liaopan/datasets/Holmes_cn_single/raw --fs_license_file /data/liaopan/megflow/license.txt --fs_subjects_dir /data/liaopan/datasets/Holmes_cn/smri -o /data/liaopan/datasets/Holmes_cn_single
# Exit on error
set -e

# Default configuration file and parameters
CONFIG_FILE="/program/nextflow/nextflow.config"
RUN_CONFIG_FILE="/program/nextflow/run_nextflow.config"
INPUT_DIR=""
OUTPUT_DIR=""
STEPS=""
FS_LICENSE_FILE=""
FS_SUBJECTS_DIR=""
T1_DIR=""
T1_INPUT_TYPE=""
T1_DICOM_SERIES_GLOB=""
ANAT_ONLY=false
MEG_ONLY=false
VIEW_REPORT=false
COHORT_MODE=false
NEXTFLOW_FILE="/program/nextflow/megflow.nf"
STREAMLIT_APP_PATH="/program/megflow/reports/reports.py"
COHORT_REPORT_PATH="/program/megflow/reports/cohort_static_html_report.py"
STATIC_TASK_LOG_MODE=""
STATIC_ARTIFACT_OVERVIEW_DURATION=""
nextflow_args=()

prepare_docker_user() {
    if [ "$(id -u)" != "0" ] || [ "${MEGFLOW_DOCKER_DROPPED:-}" = "1" ]; then
        return
    fi

    local scan_input_dir=""
    local scan_output_dir=""
    local previous_arg=""
    for arg in "$@"; do
        case "$previous_arg" in
            -i|--input)
                scan_input_dir="$arg"
                previous_arg=""
                continue
                ;;
            -o|--output)
                scan_output_dir="$arg"
                previous_arg=""
                continue
                ;;
        esac
        case "$arg" in
            -i|--input|-o|--output)
                previous_arg="$arg"
                ;;
        esac
    done

    if [ -z "$scan_output_dir" ] && [ -e /output ]; then
        scan_output_dir=/output
    fi

    local target_uid="${LOCAL_UID:-${HOST_UID:-}}"
    local target_gid="${LOCAL_GID:-${HOST_GID:-}}"

    if [ -z "$target_uid" ] && [ -n "$scan_input_dir" ] && [ -e "$scan_input_dir" ]; then
        target_uid="$(stat -c '%u' "$scan_input_dir" 2>/dev/null || true)"
        target_gid="$(stat -c '%g' "$scan_input_dir" 2>/dev/null || true)"
    fi
    if { [ -z "$target_uid" ] || [ "$target_uid" = "0" ]; } && [ -n "$scan_output_dir" ] && [ -e "$scan_output_dir" ]; then
        local output_uid
        local output_gid
        output_uid="$(stat -c '%u' "$scan_output_dir" 2>/dev/null || true)"
        output_gid="$(stat -c '%g' "$scan_output_dir" 2>/dev/null || true)"
        if [ -n "$output_uid" ] && [ "$output_uid" != "0" ]; then
            target_uid="$output_uid"
            target_gid="$output_gid"
        fi
    fi

    if [ -z "$target_uid" ] || [ "$target_uid" = "0" ]; then
        target_uid=1000
    fi
    if [ -z "$target_gid" ]; then
        target_gid="$target_uid"
    fi

    if ! getent group "$target_gid" >/dev/null 2>&1; then
        groupadd -g "$target_gid" megflow_host_group 2>/dev/null || true
    fi
    if ! getent passwd "$target_uid" >/dev/null 2>&1; then
        useradd -u "$target_uid" -g "$target_gid" -M -d /tmp/megflow_home -s /bin/bash megflow_host_user 2>/dev/null || true
    fi

    mkdir -p /tmp/megflow_home /tmp/megflow_cache /tmp/megflow_nextflow /tmp/NUMBA_CACHE_DIR /tmp/MPLCONFIGDIR
    chmod -R 777 /tmp/megflow_home /tmp/megflow_cache /tmp/megflow_nextflow /tmp/NUMBA_CACHE_DIR /tmp/MPLCONFIGDIR

    if [ -n "$scan_output_dir" ]; then
        mkdir -p "$scan_output_dir"
        if ! gosu "$target_uid:$target_gid" test -w "$scan_output_dir" 2>/dev/null; then
            echo "Preparing output directory ownership for ${target_uid}:${target_gid}: $scan_output_dir"
            chown -R "$target_uid:$target_gid" "$scan_output_dir"
        fi
        chmod ug+rwX "$scan_output_dir" 2>/dev/null || true
    fi

    export MEGFLOW_DOCKER_DROPPED=1
    export HOME=/tmp/megflow_home
    export XDG_CACHE_HOME=/tmp/megflow_cache
    export NXF_HOME=/tmp/megflow_nextflow
    export NXF_TEMP=/tmp
    export TMPDIR=/tmp
    export NUMBA_CACHE_DIR=/tmp/NUMBA_CACHE_DIR
    export MPLCONFIGDIR=/tmp/MPLCONFIGDIR
    exec gosu "$target_uid:$target_gid" "$0" "$@"
}

prepare_docker_user "$@"

echo "Executor:"
executor_name="$(id -un 2>/dev/null || true)"
if [ -n "$executor_name" ]; then
    echo "$executor_name"
else
    id -u
fi

export HOME="${HOME:-/tmp/megflow_home}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-/tmp/megflow_cache}"
export NXF_HOME="${NXF_HOME:-/tmp/megflow_nextflow}"
export NXF_TEMP="${NXF_TEMP:-/tmp}"
export TMPDIR="${TMPDIR:-/tmp}"
export NUMBA_CACHE_DIR="${NUMBA_CACHE_DIR:-/tmp/NUMBA_CACHE_DIR}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/MPLCONFIGDIR}"
mkdir -p "$HOME" "$XDG_CACHE_HOME" "$NXF_HOME" "$NXF_TEMP" "$TMPDIR" "$NUMBA_CACHE_DIR" "$MPLCONFIGDIR"

# Process input arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -c|--config) CONFIG_FILE="$2"; shift ;;
        -i|--input) INPUT_DIR="$2"; shift ;;
        -o|--output) OUTPUT_DIR="$2"; shift ;;
        -s|--steps) STEPS="$2"; shift ;;
        --fs_license_file) FS_LICENSE_FILE="$2"; shift ;;
        --fs_subjects_dir) FS_SUBJECTS_DIR="$2"; shift ;;

        # Other parameters
        --t1_dir) T1_DIR="$2"; shift ;;
        --t1_input_type) T1_INPUT_TYPE="$2"; shift ;;
        --t1_dicom_series_glob|--t1-dicom-series-glob) T1_DICOM_SERIES_GLOB="$2"; shift ;;

        # options for specifying only one part
        --anat_only) ANAT_ONLY=true ;;
        --meg_only) MEG_ONLY=true ;;

        # online reports
        -r|--view_report|--view-report) VIEW_REPORT=true ;;

        # cohort mode
        --cohort) COHORT_MODE=true ;;

        # static report options
        --static_task_log_mode|--task-log-mode) STATIC_TASK_LOG_MODE="$2"; shift ;;
        --static_artifact_overview_duration|--artifact-overview-duration) STATIC_ARTIFACT_OVERVIEW_DURATION="$2"; shift ;;

        # nextflow options
        --resume) nextflow_args+=("-resume") ;;

        -h|--help)
            echo "Usage: $0 [options]"
            echo "Options:"
            echo "  -c, --config          Specify the Nextflow config file (default: nextflow.config)"
            echo "  -i, --input           Specify the input directory"
            echo "  -o, --output          Specify the output directory(including report results.)"
            echo "  -s, --steps           Same as Nextflow --steps / params.steps (e.g. all, meg_all, anatomy, report, meg_epochs,skip_ica)"
            echo "  -r, --view-report     Run Streamlit to view the report (does not run Nextflow)"
            echo "  --cohort              Treat --input as a directory of datasets; isolate each child's output and FreeSurfer SUBJECTS_DIR"
            echo "  --static_task_log_mode failed|all-command-log|none"
            echo "  --static_artifact_overview_duration seconds"
            echo "  --fs_license_file     Specify the FreeSurfer license file"
            echo "  --fs_subjects_dir     Specify the FreeSurfer SUBJECTS_DIR directory containing processed T1 results"
            echo "  --t1_dir              Specify the T1 image directory"
            echo "  --t1_input_type       Specify the T1 input type"
            echo "  --t1_dicom_series_glob Optional relative glob for selecting DICOM series under each T1 DICOM root"
            echo "  --anat_only           Deprecated shortcut for --steps anatomy"
            echo "  --meg_only            Deprecated shortcut for --steps meg_all"
            echo "  --resume              Resume the previous run(nextflow options)"
            exit 0
            ;;
        *)
            echo "Unknown parameter: $1"
            exit 1
            ;;
    esac
    shift
done


# If --view-report is set, run the Streamlit app instead of Nextflow
if [ "$VIEW_REPORT" = true ]; then
    echo "Starting Streamlit to view the report..."
    if [ -z "$OUTPUT_DIR" ]; then
      OUTPUT_DIR="/output"
    fi
    export DATASET_REPORT_PATH="$OUTPUT_DIR"
    if [ -n "$FS_SUBJECTS_DIR" ]; then
      export SUBJECTS_DIR="$FS_SUBJECTS_DIR"
    elif [ -d "${OUTPUT_DIR}/smri" ]; then
      export SUBJECTS_DIR="${OUTPUT_DIR}/smri"
    fi
    streamlit run "$STREAMLIT_APP_PATH" --server.port=8501 --server.headless=true
    exit 0
fi

# Check if input and output directories are specified
if [ -z "$INPUT_DIR" ]; then
    echo "Input directory must be specified."
    exit 1
fi

if [ -z "$OUTPUT_DIR" ]; then
    echo "Output directory must be specified."
    exit 1
fi

if ! mkdir -p "$OUTPUT_DIR" 2>/dev/null || ! touch "$OUTPUT_DIR/.megflow_write_test" 2>/dev/null; then
    echo "Error: output directory is not writable by the container user: $OUTPUT_DIR"
    echo "If you run Docker with a custom --user, remove it or make the mounted output directory writable by that user."
    echo "You can also pass LOCAL_UID/LOCAL_GID when automatic ownership inference from /input is not suitable."
    exit 1
fi
rm -f "$OUTPUT_DIR/.megflow_write_test"

# Check if the config file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file not found: $CONFIG_FILE"
    exit 1
fi

read_static_task_log_mode() {
    sed -n 's/^[[:space:]]*static_task_log_mode[[:space:]]*=[[:space:]]*["'\'']\([^"'\'']*\)["'\''].*/\1/p' "$CONFIG_FILE" | head -n 1
}

read_static_artifact_overview_duration() {
    sed -n 's/^[[:space:]]*static_artifact_overview_duration[[:space:]]*=[[:space:]]*\([^[:space:]]*\).*/\1/p' "$CONFIG_FILE" | head -n 1
}

STATIC_TASK_LOG_MODE="${STATIC_TASK_LOG_MODE:-$(read_static_task_log_mode)}"
STATIC_TASK_LOG_MODE="${STATIC_TASK_LOG_MODE:-failed}"
STATIC_ARTIFACT_OVERVIEW_DURATION="${STATIC_ARTIFACT_OVERVIEW_DURATION:-$(read_static_artifact_overview_duration)}"
STATIC_ARTIFACT_OVERVIEW_DURATION="${STATIC_ARTIFACT_OVERVIEW_DURATION:-200.0}"
case "$STATIC_TASK_LOG_MODE" in
    failed|all-command-log|none) ;;
    *)
        echo "Error: invalid --static_task_log_mode '$STATIC_TASK_LOG_MODE' (expected failed, all-command-log, or none)"
        exit 1
        ;;
esac

echo "Using configuration file: $CONFIG_FILE"
echo "Static report task log mode: $STATIC_TASK_LOG_MODE"
echo "Static artifact overview duration: ${STATIC_ARTIFACT_OVERVIEW_DURATION}s"

write_run_config() {
    local run_input_dir="$1"
    local run_output_dir="$2"
    local run_config_file="$3"
    local run_fs_subjects_dir="${4:-$FS_SUBJECTS_DIR}"
    local run_t1_dir="${5:-$T1_DIR}"

    cp "$CONFIG_FILE" "$run_config_file"

    if [ -n "$run_input_dir" ]; then
        echo "Setting dataset_dir in config to: $run_input_dir"
        sed -i "s|^\s*dataset_dir\s*=.*|    dataset_dir = \"$run_input_dir\"|" "$run_config_file"
    fi

    if [ -n "$run_output_dir" ]; then
        echo "Setting output_dir in config to: $run_output_dir"
        sed -i "s|^\s*output_dir\s*=.*|    output_dir = \"$run_output_dir\"|" "$run_config_file"
    fi

    if [ -n "$run_fs_subjects_dir" ]; then
        echo "Using FreeSurfer subjects directory: $run_fs_subjects_dir"
        mkdir -p "$run_fs_subjects_dir"
        sed -i "s|^\s*fs_subjects_dir\s*=.*|    fs_subjects_dir = \"$run_fs_subjects_dir\"|" "$run_config_file"
    fi

    if [ -n "$FS_LICENSE_FILE" ]; then
        echo "Using FreeSurfer license file: $FS_LICENSE_FILE"
        sed -i "s|^\s*fs_license\s*=.*|    fs_license = \"$FS_LICENSE_FILE\"|" "$run_config_file"
    fi

    if [ -n "$run_t1_dir" ]; then
        echo "Setting t1_dir in config to: $run_t1_dir"
        sed -i "s|^\s*t1_dir\s*=.*|    t1_dir = \"$run_t1_dir\"|" "$run_config_file"
        sed -i "s|^\s*t1_bids_dir\s*=.*|    t1_bids_dir = \"$run_t1_dir\"|" "$run_config_file"
    fi

    if [ -n "$T1_INPUT_TYPE" ]; then
        echo "Setting t1_input_type in config to: $T1_INPUT_TYPE"
        sed -i "s|^\s*t1_input_type\s*=.*|    t1_input_type = \"$T1_INPUT_TYPE\"|" "$run_config_file"
    fi

    if [ -n "$T1_DICOM_SERIES_GLOB" ]; then
        echo "Setting t1_dicom_series_glob in config to: $T1_DICOM_SERIES_GLOB"
        if grep -q "^[[:space:]]*t1_dicom_series_glob[[:space:]]*=" "$run_config_file"; then
            sed -i "s|^[[:space:]]*t1_dicom_series_glob[[:space:]]*=.*|    t1_dicom_series_glob = \"$T1_DICOM_SERIES_GLOB\"|" "$run_config_file"
        else
            sed -i "/^[[:space:]]*t1_input_type[[:space:]]*=/a\\    t1_dicom_series_glob = \"$T1_DICOM_SERIES_GLOB\"" "$run_config_file"
        fi
    fi

    echo "Setting static_task_log_mode in config to: $STATIC_TASK_LOG_MODE"
    sed -i "s|^\s*static_task_log_mode\s*=.*|    static_task_log_mode = \"$STATIC_TASK_LOG_MODE\"|" "$run_config_file"
    echo "Setting static_artifact_overview_duration in config to: $STATIC_ARTIFACT_OVERVIEW_DURATION"
    sed -i "s|^\s*static_artifact_overview_duration\s*=.*|    static_artifact_overview_duration = $STATIC_ARTIFACT_OVERVIEW_DURATION|" "$run_config_file"
}


# Call Nextflow to run the pipeline with specified configurations
echo "Running Nextflow pipeline..."

steps_args=()
if [ "$ANAT_ONLY" = true ] && [ "$MEG_ONLY" = true ]; then
    echo "Error: --anat_only and --meg_only cannot be used together. Prefer --steps anatomy or --steps meg_all."
    exit 1
fi

if [ -z "$STEPS" ] && [ "$ANAT_ONLY" = true ]; then
    STEPS="anatomy"
    echo "Warning: --anat_only is deprecated; using --steps anatomy."
fi

if [ -z "$STEPS" ] && [ "$MEG_ONLY" = true ]; then
    STEPS="meg_all"
    echo "Warning: --meg_only is deprecated; using --steps meg_all."
fi

if [ -n "$STEPS" ]; then
    echo "Setting steps (Nextflow params.steps): $STEPS"
    steps_args=(--steps "$STEPS")
fi

run_nextflow_pipeline() {
    local run_config_file="$1"
    local run_output_dir="$2"
    local run_work_dir="$3"
    local work_args=()

    mkdir -p "$run_output_dir"
    if [ -n "$run_work_dir" ]; then
        mkdir -p "$run_work_dir"
        work_args=(-w "$run_work_dir")
    fi

    nextflow run "${NEXTFLOW_FILE}" \
        -c "${run_config_file}" \
        "${steps_args[@]}" \
        --static_task_log_mode "$STATIC_TASK_LOG_MODE" \
        --static_artifact_overview_duration "$STATIC_ARTIFACT_OVERVIEW_DURATION" \
        "${work_args[@]}" \
        -with-report "${run_output_dir}/report.html" \
        -with-timeline "${run_output_dir}/timeline.html" \
        -with-trace "${run_output_dir}/trace.txt" \
        "${nextflow_args[@]}"

    cp "$run_config_file" "${run_output_dir}/nextflow.config"
}

# activate Anaconda virtualenv and virtual display
#/usr/bin/supervisord  -c /etc/supervisor/conf.d/supervisord.conf
#Xvfb :99 -screen 0 1920x1080x24 &
#export DISPLAY=:99
#xhost +
#export QT_QPA_PLATFORM=xcb #offscreen

mkdir -p "$OUTPUT_DIR"

if [ "$COHORT_MODE" = true ]; then
    if [ ! -d "$INPUT_DIR" ]; then
        echo "Error: --cohort requires --input to be a directory containing dataset subdirectories."
        exit 1
    fi

    echo "Running cohort mode. Dataset collection root: $INPUT_DIR"
    cohort_work_dir="${OUTPUT_DIR}/work"
    cohort_fs_subjects_base="${FS_SUBJECTS_DIR:-/smri}"
    mkdir -p "${OUTPUT_DIR}/datasets" "$cohort_work_dir" "$cohort_fs_subjects_base"

    write_run_config "$INPUT_DIR" "$OUTPUT_DIR" "$RUN_CONFIG_FILE" "$cohort_fs_subjects_base" ""

    cohort_args=(
        --cohort true
        --cohort_t1_root "$T1_DIR"
        --dataset_dir "$INPUT_DIR"
        --output_dir "$OUTPUT_DIR"
        --preproc_dir "${OUTPUT_DIR}/preprocessed"
        --fs_subjects_dir "$cohort_fs_subjects_base"
    )

    if [ -n "$STEPS" ]; then
        cohort_args+=(--steps "$STEPS")
    fi

    nextflow run "${NEXTFLOW_FILE}" \
        -c "${RUN_CONFIG_FILE}" \
        "${cohort_args[@]}" \
        --static_task_log_mode "$STATIC_TASK_LOG_MODE" \
        --static_artifact_overview_duration "$STATIC_ARTIFACT_OVERVIEW_DURATION" \
        -w "${cohort_work_dir}/cohort_driver" \
        -with-report "${OUTPUT_DIR}/cohort_report.html" \
        -with-timeline "${OUTPUT_DIR}/cohort_timeline.html" \
        -with-trace "${OUTPUT_DIR}/cohort_trace.txt" \
        "${nextflow_args[@]}"

    chmod -R ug+rwX "$OUTPUT_DIR" 2>/dev/null || true
    exit 0
fi

write_run_config "$INPUT_DIR" "$OUTPUT_DIR" "$RUN_CONFIG_FILE"
run_nextflow_pipeline "$RUN_CONFIG_FILE" "$OUTPUT_DIR" ""
chmod -R ug+rwX "$OUTPUT_DIR" 2>/dev/null || true
