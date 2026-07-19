#!/bin/bash  
# Usage:
# bash run_for_docker.sh -i /data/study/raw -o /data/study/megflow \
#   --fs_license_file /data/license.txt --fs_subjects_dir /data/study/smri
# Exit on error
set -e

# MEGFlow is DSL2 but still uses Groovy constructs supported by Nextflow's v1
# syntax parser. Nextflow 26 defaults to v2, so select the compatible parser
# explicitly until the pipeline itself is migrated to the static v2 syntax.
export NXF_SYNTAX_PARSER=v1
export MEGFLOW_DOCKER_BASE_CONFIG="${MEGFLOW_DOCKER_BASE_CONFIG:-/program/nextflow/nextflow.config}"

# Default configuration file and parameters
CONFIG_FILE="/program/nextflow/nextflow.config"
RUN_CONFIG_FILE="/program/nextflow/run_nextflow.config"
INPUT_DIR=""
OUTPUT_DIR=""
STEPS=""
FS_LICENSE_FILE=""
FS_SUBJECTS_DIR=""
T1_DIR=""
VIEW_REPORT=false
CORPUS_MODE=false
NEXTFLOW_FILE="/program/nextflow/megflow.nf"
STREAMLIT_APP_PATH="/program/megflow/reports/reports.py"
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

        # online reports
        -r|--view_report|--view-report) VIEW_REPORT=true ;;

        # corpus mode
        --corpus) CORPUS_MODE=true ;;

        # nextflow options
        --resume) nextflow_args+=("-resume") ;;

        -h|--help)
            echo "Usage: $0 [options]"
            echo "Options:"
            echo "  -c, --config          Project configuration file (default: /program/nextflow/nextflow.config)"
            echo "  -i, --input           MEG dataset or corpus input directory"
            echo "  -o, --output          MEGFlow output directory"
            echo "  -s, --steps           Pipeline stage override (e.g. all, meg_all, anatomy, report)"
            echo "  -r, --view-report     Run Streamlit to view the report (does not run Nextflow)"
            echo "  --corpus              Process immediate input children as separate datasets"
            echo "  --fs_license_file     FreeSurfer license path inside the container"
            echo "  --fs_subjects_dir     FreeSurfer SUBJECTS_DIR inside the container"
            echo "  --t1_dir              Single-dataset structural MRI input root"
            echo "  --resume              Resume the previous Nextflow execution"
            echo "  -h, --help             Show this help message"
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

if [ "$CORPUS_MODE" = true ] && [ -n "$T1_DIR" ]; then
    echo "Error: --t1_dir is only valid for a single-dataset run. In corpus mode, set t1_dir in each named dataset profile."
    exit 1
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

echo "Using configuration file: $CONFIG_FILE"

groovy_escape() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

write_run_config() {
    local run_input_dir="$1"
    local run_output_dir="$2"
    local run_config_file="$3"
    local run_fs_subjects_dir="${4:-$FS_SUBJECTS_DIR}"
    local run_t1_dir="${5:-$T1_DIR}"
    local escaped_input
    local escaped_output
    local escaped_t1
    local fs_subjects_assignment=""
    local t1_dir_assignment=""
    local steps_assignment=""
    local anatomy_assignments=""

    cp "$CONFIG_FILE" "$run_config_file"

    escaped_input="$(groovy_escape "$run_input_dir")"
    escaped_output="$(groovy_escape "$run_output_dir")"

    if [ -n "$run_t1_dir" ]; then
        escaped_t1="$(groovy_escape "$run_t1_dir")"
        t1_dir_assignment="params.megflow.datasets.docker_input.t1_dir = \"${escaped_t1}\""
    fi

    if [ -n "$STEPS" ]; then
        steps_assignment="params.megflow.datasets.docker_input.steps = \"$(groovy_escape "$STEPS")\""
    fi

    if [ -n "$FS_LICENSE_FILE" ]; then
        anatomy_assignments="params.megflow.datasets.docker_input.anatomy = params.megflow.datasets.docker_input.anatomy ?: [:]"
        anatomy_assignments="${anatomy_assignments}
params.megflow.datasets.docker_input.anatomy.fs_license_file = \"$(groovy_escape "$FS_LICENSE_FILE")\""
    fi

    if [ -n "$run_fs_subjects_dir" ]; then
        echo "Using FreeSurfer subjects directory: $run_fs_subjects_dir"
        mkdir -p "$run_fs_subjects_dir"
        fs_subjects_assignment="params.megflow.datasets.docker_input.fs_subjects_dir = \"$(groovy_escape "$run_fs_subjects_dir")\""
    fi

    cat >> "$run_config_file" <<EOF

// Runtime overrides generated by run_for_docker.sh.
params.megflow.output_dir = "${escaped_output}"
params.megflow.report_scope = "dataset"
params.megflow.corpus_root = ""
params.megflow.dataset_include = ["docker_input"]
params.megflow.dataset_exclude = []

params.megflow.datasets.docker_input.name = "docker_input"
params.megflow.datasets.docker_input.dataset_dir = "${escaped_input}"
params.megflow.datasets.docker_input.output_dir = "${escaped_output}"
params.megflow.datasets.docker_input.preproc_dir = "${escaped_output}/preprocessed"
${t1_dir_assignment}
${fs_subjects_assignment}
${steps_assignment}
${anatomy_assignments}

workDir = "${escaped_output}/work"
log.file = "${escaped_output}/static_html_report/nextflow/nextflow.log"
report.file = "${escaped_output}/static_html_report/nextflow/report.html"
timeline.file = "${escaped_output}/static_html_report/nextflow/timeline.html"
trace.file = "${escaped_output}/static_html_report/nextflow/trace.txt"
EOF
}

write_corpus_run_config() {
    local run_input_dir="$1"
    local run_output_dir="$2"
    local run_config_file="$3"
    local run_fs_subjects_root="$4"
    local escaped_input
    local escaped_output
    local escaped_fs_subjects_root
    local steps_assignment=""
    local anatomy_assignments=""

    cp "$CONFIG_FILE" "$run_config_file"

    escaped_input="$(groovy_escape "$run_input_dir")"
    escaped_output="$(groovy_escape "$run_output_dir")"
    escaped_fs_subjects_root="$(groovy_escape "$run_fs_subjects_root")"

    if [ -n "$STEPS" ]; then
        steps_assignment="params.megflow.defaults.steps = \"$(groovy_escape "$STEPS")\""
    fi

    if [ -n "$FS_LICENSE_FILE" ]; then
        anatomy_assignments="params.megflow.defaults.anatomy = params.megflow.defaults.anatomy ?: [:]"
        anatomy_assignments="${anatomy_assignments}
params.megflow.defaults.anatomy.fs_license_file = \"$(groovy_escape "$FS_LICENSE_FILE")\""
    fi

    cat >> "$run_config_file" <<EOF

// Corpus runtime overrides generated by run_for_docker.sh.
params.megflow.output_dir = "${escaped_output}"
params.megflow.report_scope = "corpus"
params.megflow.corpus_root = "${escaped_input}"
params.megflow.fs_subjects_root = "${escaped_fs_subjects_root}"

${steps_assignment}
${anatomy_assignments}

// docker_input is the single-dataset placeholder bundled with the image.
// An empty dataset_dir keeps it out of corpus discovery while preserving all
// named profiles from the mounted configuration.
params.megflow.datasets.docker_input.dataset_dir = ""

workDir = "${escaped_output}/work/corpus_driver"
log.file = "${escaped_output}/corpus_static_html_report/nextflow/nextflow.log"
report.file = "${escaped_output}/corpus_static_html_report/nextflow/report.html"
timeline.file = "${escaped_output}/corpus_static_html_report/nextflow/timeline.html"
trace.file = "${escaped_output}/corpus_static_html_report/nextflow/trace.txt"
EOF
}


# Call Nextflow to run the pipeline with specified configurations
echo "Running Nextflow pipeline..."

if [ -n "$STEPS" ]; then
    echo "Setting MEGFlow steps: $STEPS"
fi

run_nextflow_pipeline() {
    local run_config_file="$1"
    local run_output_dir="$2"
    local run_work_dir="$3"
    local work_args=()
    local nextflow_report_dir="${run_output_dir}/static_html_report/nextflow"
    local nextflow_launch_dir="${run_output_dir}/.nextflow-launch"

    mkdir -p "$nextflow_report_dir" "${nextflow_launch_dir}/.nextflow"
    if [ -n "$run_work_dir" ]; then
        mkdir -p "$run_work_dir"
        work_args=(-w "$run_work_dir")
    fi

    # Nextflow keeps run history under launchDir/.nextflow, independently of NXF_HOME.
    (
        cd "$nextflow_launch_dir"
        nextflow -log "${nextflow_report_dir}/nextflow.log" run "${NEXTFLOW_FILE}" \
            -c "${run_config_file}" \
            "${work_args[@]}" \
            -with-report "${nextflow_report_dir}/report.html" \
            -with-timeline "${nextflow_report_dir}/timeline.html" \
            -with-trace "${nextflow_report_dir}/trace.txt" \
            "${nextflow_args[@]}"
    )

    cp "$run_config_file" "${run_output_dir}/nextflow.config"
}

# activate Anaconda virtualenv and virtual display
#/usr/bin/supervisord  -c /etc/supervisor/conf.d/supervisord.conf
#Xvfb :99 -screen 0 1920x1080x24 &
#export DISPLAY=:99
#xhost +
#export QT_QPA_PLATFORM=xcb #offscreen

mkdir -p "$OUTPUT_DIR"

if [ "$CORPUS_MODE" = true ]; then
    if [ ! -d "$INPUT_DIR" ]; then
        echo "Error: --corpus requires --input to be a directory containing dataset subdirectories."
        exit 1
    fi

    echo "Running corpus mode. Dataset collection root: $INPUT_DIR"
    corpus_work_dir="${OUTPUT_DIR}/work"
    corpus_fs_subjects_root="${FS_SUBJECTS_DIR:-/smri}"
    corpus_nextflow_dir="${OUTPUT_DIR}/corpus_static_html_report/nextflow"
    corpus_launch_dir="${OUTPUT_DIR}/.nextflow-launch"
    mkdir -p "${OUTPUT_DIR}/datasets" "$corpus_nextflow_dir" "$corpus_work_dir" \
        "$corpus_fs_subjects_root" "${corpus_launch_dir}/.nextflow"

    write_corpus_run_config "$INPUT_DIR" "$OUTPUT_DIR" "$RUN_CONFIG_FILE" "$corpus_fs_subjects_root"

    (
        cd "$corpus_launch_dir"
        nextflow -log "${corpus_nextflow_dir}/nextflow.log" run "${NEXTFLOW_FILE}" \
            -c "${RUN_CONFIG_FILE}" \
            -w "${corpus_work_dir}/corpus_driver" \
            -with-report "${corpus_nextflow_dir}/report.html" \
            -with-timeline "${corpus_nextflow_dir}/timeline.html" \
            -with-trace "${corpus_nextflow_dir}/trace.txt" \
            "${nextflow_args[@]}"
    )

    cp "$RUN_CONFIG_FILE" "${OUTPUT_DIR}/nextflow.config"
    chmod -R ug+rwX "$OUTPUT_DIR" 2>/dev/null || true
    exit 0
fi

write_run_config "$INPUT_DIR" "$OUTPUT_DIR" "$RUN_CONFIG_FILE"
run_nextflow_pipeline "$RUN_CONFIG_FILE" "$OUTPUT_DIR" ""
chmod -R ug+rwX "$OUTPUT_DIR" 2>/dev/null || true
