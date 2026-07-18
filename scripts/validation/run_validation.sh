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

run_routing() {
    resolve_nextflow
    printf '\n== Routing and resume validation ==\n'
    run_unittest_gate \
        test_nextflow_execution_config \
        test_docker_entrypoint_options \
        test_docker_image_namespace \
        test_install_scripts \
        test_megnet_retrained_nextflow_contract \
        test_validation_runner \
        test_nextflow_profile_integration \
        test_nextflow_report_layout_integration

    printf '\n== Shipped Nextflow config parsing ==\n'
    local configs=("${ROOT_DIR}"/nextflow/*.config)
    [[ -e "${configs[0]}" ]] || die "no shipped Nextflow configs found"
    local config
    for config in "${configs[@]}"; do
        "${MEGFLOW_NEXTFLOW}" -C "${config}" config "${ROOT_DIR}/nextflow/megflow.nf" -o flat >/dev/null
        printf 'parsed %s\n' "${config#${ROOT_DIR}/}"
    done
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
    run_unittest_gate \
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
    die "usage: $0 [routing|scientific|all]"
fi

case "${1:-all}" in
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
        die "unknown validation mode '$1'; expected routing, scientific, or all"
        ;;
esac
