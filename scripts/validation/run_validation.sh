#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNITTEST_GATE="${ROOT_DIR}/scripts/validation/run_unittest_gate.py"
EXPECTED_NEXTFLOW_VERSION="${MEGFLOW_EXPECTED_NEXTFLOW_VERSION:-24.10.3}"

export MPLBACKEND="${MPLBACKEND:-Agg}"
export NUMEXPR_MAX_THREADS="${NUMEXPR_MAX_THREADS:-8}"
export NXF_ANSI_LOG="${NXF_ANSI_LOG:-false}"
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-${TMPDIR:-/tmp}/megflow-validation-pycache}"
export PYTHONPATH="${ROOT_DIR}:${ROOT_DIR}/megflow:${ROOT_DIR}/tests${PYTHONPATH:+:${PYTHONPATH}}"

die() {
    printf 'Validation error: %s\n' "$*" >&2
    exit 2
}

if [[ -n "${PYTHON:-}" ]]; then
    PYTHON_BIN="${PYTHON}"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    die "Python is required for validation"
fi

run_unittest_gate() {
    "${PYTHON_BIN}" "${UNITTEST_GATE}" "$@"
}

report_duration() {
    local label="$1"
    local started_at="$2"
    local elapsed=$((SECONDS - started_at))
    printf '%s completed in %dm %02ds\n' \
        "${label}" "$((elapsed / 60))" "$((elapsed % 60))"
}

run_timed_unittest_gate() {
    local label="$1"
    shift
    local started_at=${SECONDS}
    run_unittest_gate "$@"
    report_duration "${label}" "${started_at}"
}

resolve_nextflow() {
    if [[ -n "${MEGFLOW_NEXTFLOW:-}" ]]; then
        [[ -x "${MEGFLOW_NEXTFLOW}" ]] || die "MEGFLOW_NEXTFLOW is not executable: ${MEGFLOW_NEXTFLOW}"
    else
        MEGFLOW_NEXTFLOW="$(command -v nextflow || true)"
        [[ -n "${MEGFLOW_NEXTFLOW}" ]] || die "Nextflow is required for the routing gate"
    fi
    export MEGFLOW_NEXTFLOW

    local version_output
    version_output="$("${MEGFLOW_NEXTFLOW}" -version 2>&1)"
    if [[ "${version_output}" != *"version ${EXPECTED_NEXTFLOW_VERSION}"* ]]; then
        printf '%s\n' "${version_output}" >&2
        die "expected Nextflow ${EXPECTED_NEXTFLOW_VERSION}"
    fi
}

parse_shipped_configs() {
    local started_at=${SECONDS}
    local configs=()
    local tracked_config
    while IFS= read -r tracked_config; do
        configs+=("${ROOT_DIR}/${tracked_config}")
    done < <(
        cd "${ROOT_DIR}"
        git ls-files 'nextflow/*.config'
    )

    [[ ${#configs[@]} -gt 0 ]] || die "no tracked Nextflow configs found"
    local config
    for config in "${configs[@]}"; do
        "${MEGFLOW_NEXTFLOW}" -C "${config}" config "${ROOT_DIR}/nextflow/megflow.nf" -o flat >/dev/null
        printf 'parsed %s\n' "${config#${ROOT_DIR}/}"
    done
    report_duration "Shipped config parsing" "${started_at}"
}

run_routing_ci() {
    local started_at=${SECONDS}
    resolve_nextflow

    printf '\n== CI static routing contracts ==\n'
    run_timed_unittest_gate "CI static routing contracts" \
        test_documentation_config_examples.DocumentationConfigExamplesTests \
        test_documentation_config_examples.DocumentationConfigExamplesIntegrationTests.test_all_documented_groovy_blocks_parse_together \
        test_nextflow_execution_config \
        test_docker_entrypoint_options \
        test_docker_image_namespace \
        test_megnet_retrained_nextflow_contract \
        test_quality_score_nextflow_contract \
        test_validation_runner

    printf '\n== CI Nextflow routing smoke matrix ==\n'
    run_timed_unittest_gate "CI Nextflow routing smoke matrix" \
        test_nextflow_profile_integration.NextflowProfileIntegrationTests.test_anatomy_step_matrix_schedules_only_selected_method \
        test_nextflow_profile_integration.NextflowProfileIntegrationTests.test_with_anatomy_modifier_stops_at_requested_meg_stage \
        test_nextflow_profile_integration.NextflowProfileIntegrationTests.test_recording_level_steps_reduce_the_dataset_stage \
        test_nextflow_profile_integration.NextflowProfileIntegrationTests.test_dataset_and_recording_overrides_do_not_cross_route \
        test_nextflow_profile_integration.NextflowProfileIntegrationTests.test_mne_and_osl_kwargs_survive_default_dataset_recording_merges \
        test_nextflow_profile_integration.NextflowProfileIntegrationTests.test_raw_covariance_pairs_with_the_correct_dataset_noise_recording \
        test_nextflow_profile_integration.NextflowProfileIntegrationTests.test_lcmv_data_covariance_is_conditional_and_uses_exact_source_input \
        test_nextflow_profile_integration.NextflowProfileIntegrationTests.test_missing_raw_covariance_pair_fails_instead_of_silently_skipping_source \
        test_nextflow_profile_integration.NextflowProfileIntegrationTests.test_resume_invalidates_event_dependent_lineage_and_new_inputs \
        test_nextflow_profile_integration.NextflowProfileIntegrationTests.test_strict_processing_failure_terminates_before_report_submission \
        test_nextflow_report_layout_integration.NextflowReportLayoutIntegrationTests.test_live_trace_survives_dataset_and_corpus_report_rebuild

    printf '\n== Shipped Nextflow config parsing ==\n'
    parse_shipped_configs
    report_duration "CI routing validation" "${started_at}"
}

run_routing() {
    local started_at=${SECONDS}
    resolve_nextflow
    printf '\n== Full local routing and resume validation ==\n'
    run_timed_unittest_gate "Full local routing and resume validation" \
        test_documentation_config_examples \
        test_nextflow_execution_config \
        test_docker_entrypoint_options \
        test_docker_image_namespace \
        test_install_scripts \
        test_megnet_retrained_nextflow_contract \
        test_quality_score_nextflow_contract \
        test_validation_runner \
        test_nextflow_profile_integration \
        test_nextflow_report_layout_integration

    printf '\n== Shipped Nextflow config parsing ==\n'
    parse_shipped_configs
    report_duration "Full local routing validation" "${started_at}"
}

run_scientific() {
    printf '\n== Scientific MNE/OSL validation ==\n'
    MEGFLOW_REPO_ROOT="${ROOT_DIR}" "${PYTHON_BIN}" -c '
import os
from pathlib import Path
import mne, numpy, pandas, scipy, yaml
from PIL import Image
import osl_ephys

root = Path(os.environ["MEGFLOW_REPO_ROOT"]).resolve()
expected = (root / "megflow" / "tools" / "osl-ephys" / "osl_ephys").resolve()
actual = Path(osl_ephys.__file__).resolve().parent
if actual != expected:
    raise SystemExit(f"Validation must use vendored OSL-ephys: expected {expected}, got {actual}")
print(f"MNE {mne.__version__}; NumPy {numpy.__version__}; SciPy {scipy.__version__}")
print(f"OSL-ephys source: {actual}")
'
    run_timed_unittest_gate "Scientific MNE/OSL validation" \
        test_deepreject_input \
        test_epochs_preproc \
        test_ica_category_switches \
        test_megnet_retrained \
        test_megnet_retrained_comparison \
        test_megqc_scores \
        test_mne_config_contract \
        test_normmegqc_preprocessing \
        test_rank_covariance \
        test_run_ica_label_megnet \
        test_source_routing \
        test_source_visualization \
        test_static_reports
}

documentation_dependencies_available() {
    "${PYTHON_BIN}" -c '
import sphinx
import sphinx_autodoc_typehints
import sphinx_book_theme
import sphinx_click
import sphinx_copybutton
import sphinx_design
' >/dev/null 2>&1
}

run_all() {
    run_routing
    run_scientific
    if documentation_dependencies_available; then
        printf '\n== Documentation validation ==\n'
        "${PYTHON_BIN}" -m sphinx -W --keep-going -b html "${ROOT_DIR}/docs/source" "${ROOT_DIR}/docs/build/html"
    else
        printf '\nDocumentation validation not run: install requirements_doc.txt.\n'
    fi
}

if [[ $# -gt 1 ]]; then
    die "usage: $0 [routing-ci|routing|scientific|all]"
fi

case "${1:-all}" in
    routing-ci)
        run_routing_ci
        ;;
    routing)
        run_routing
        ;;
    scientific)
        run_scientific
        ;;
    all)
        run_all
        ;;
    *)
        die "unknown validation mode '$1'; expected routing-ci, routing, scientific, or all"
        ;;
esac
