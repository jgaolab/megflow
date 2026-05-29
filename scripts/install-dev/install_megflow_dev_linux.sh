#!/usr/bin/env bash

set -euo pipefail

INSTALL_ROOT="${HOME}/.megflow-dev"
INSTALL_FREESURFER=1
SKIP_REQUIREMENTS=0
CONDA_ENV_PREFIX=""
MINICONDA_ROOT=""
REPO_URL="git@github.com:jgaolab/megflow.git"
REPO_DIR=""
PY_ENV_NAME="megflow"
PY_ENV_PREFIX=""
NEXTFLOW_BIN=""
CONDA_BIN=""
FREESURFER_STATUS="not_requested"

log() {
  echo "[megflow-dev-install][linux] $*"
}

usage() {
  cat <<'EOF'
Usage:
  bash scripts/install-dev/install_megflow_dev_linux.sh [options]

Options:
  --install-dir <dir>      Installation root directory (default: ~/.megflow-dev)
  --no-freesurfer          Skip FreeSurfer installation
  --with-freesurfer        Force FreeSurfer installation (default behavior)
  --skip-requirements      Skip installing requirements.txt
  --conda-prefix <dir>     Conda env prefix for FreeSurfer
                           (default: <install-dir>/freesurfer/conda-env)
  --repo-dir <dir>         Local source directory (default: <install-dir>/src/megflow)
  --repo-url <url>         Source git URL (default: git@github.com:jgaolab/megflow.git)
  --miniconda-root <dir>   Miniconda install path when conda is absent
                           (default: <install-dir>/miniconda3)
  -h, --help               Show this help message

Examples:
  bash scripts/install-dev/install_megflow_dev_linux.sh
  bash scripts/install-dev/install_megflow_dev_linux.sh --install-dir /data/megflow-dev
  bash scripts/install-dev/install_megflow_dev_linux.sh --no-freesurfer
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --install-dir) INSTALL_ROOT="${2:-}"; shift 2 ;;
      --no-freesurfer) INSTALL_FREESURFER=0; shift ;;
      --with-freesurfer) INSTALL_FREESURFER=1; shift ;;
      --skip-requirements) SKIP_REQUIREMENTS=1; shift ;;
      --conda-prefix) CONDA_ENV_PREFIX="${2:-}"; shift 2 ;;
      --repo-dir) REPO_DIR="${2:-}"; shift 2 ;;
      --repo-url) REPO_URL="${2:-}"; shift 2 ;;
      --miniconda-root) MINICONDA_ROOT="${2:-}"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) log "Unknown argument: $1"; usage; exit 1 ;;
    esac
  done
}

ensure_dir() {
  mkdir -p "$1"
}

ensure_download_tool() {
  if command -v curl >/dev/null 2>&1; then
    echo "curl"
    return
  fi
  if command -v wget >/dev/null 2>&1; then
    echo "wget"
    return
  fi

  log "Neither curl nor wget was found. Please install one of them and retry."
  exit 1
}

ensure_git() {
  command -v git >/dev/null 2>&1 || {
    log "git is required but not found. Please install git first."
    exit 1
  }
}

get_conda_root() {
  local conda_root
  conda_root="$(dirname "$(dirname "${CONDA_BIN}")")"
  [[ -f "${conda_root}/etc/profile.d/conda.sh" ]] || {
    log "Cannot locate conda.sh from conda root: ${conda_root}"
    exit 1
  }
  echo "${conda_root}"
}

activate_conda_base() {
  local conda_root
  conda_root="$(get_conda_root)"
  # shellcheck disable=SC1091
  source "${conda_root}/etc/profile.d/conda.sh"
  conda activate base >/dev/null 2>&1 || true
}

resolve_python_env_prefix() {
  local env_path
  PY_ENV_PREFIX="${INSTALL_ROOT}/conda-envs/${PY_ENV_NAME}"
  env_path="$(conda env list 2>/dev/null | awk -v n="${PY_ENV_NAME}" '$1 == n { print $NF; exit }')"

  if [[ -n "${env_path}" && -d "${env_path}" ]]; then
    PY_ENV_PREFIX="${env_path}"
    log "Found existing named Python env '${PY_ENV_NAME}': ${PY_ENV_PREFIX}"
  fi
}

install_nextflow() {
  local downloader nextflow_bin_dir tmp_dir
  downloader="$(ensure_download_tool)"
  nextflow_bin_dir="${INSTALL_ROOT}/nextflow/bin"

  ensure_dir "${nextflow_bin_dir}"
  tmp_dir="$(mktemp -d)"
  log "Installing Nextflow to ${nextflow_bin_dir}"
  pushd "${tmp_dir}" >/dev/null

  if [[ "${downloader}" == "curl" ]]; then
    curl -s https://get.nextflow.io | bash
  else
    wget -qO- https://get.nextflow.io | bash
  fi

  chmod +x nextflow
  mv -f nextflow "${nextflow_bin_dir}/nextflow"
  popd >/dev/null
  rm -rf "${tmp_dir}"

  NEXTFLOW_BIN="${nextflow_bin_dir}/nextflow"
  log "Nextflow installed: ${NEXTFLOW_BIN}"
}

resolve_or_install_nextflow() {
  local nextflow_bin_dir
  if command -v nextflow >/dev/null 2>&1; then
    NEXTFLOW_BIN="$(command -v nextflow)"
    log "Found system Nextflow: ${NEXTFLOW_BIN}. Skip installation."
    return
  fi

  nextflow_bin_dir="${INSTALL_ROOT}/nextflow/bin"
  if [[ -x "${nextflow_bin_dir}/nextflow" ]]; then
    NEXTFLOW_BIN="${nextflow_bin_dir}/nextflow"
    log "Found installed Nextflow: ${NEXTFLOW_BIN}. Skip installation."
    return
  fi

  install_nextflow
}

install_miniconda() {
  local downloader installer tmp_dir
  downloader="$(ensure_download_tool)"
  installer="Miniconda3-latest-Linux-x86_64.sh"

  ensure_dir "${MINICONDA_ROOT}"
  tmp_dir="$(mktemp -d)"
  pushd "${tmp_dir}" >/dev/null
  log "Conda not found. Installing Miniconda to ${MINICONDA_ROOT}"

  if [[ "${downloader}" == "curl" ]]; then
    curl -fsSLO "https://repo.anaconda.com/miniconda/${installer}"
  else
    wget -q "https://repo.anaconda.com/miniconda/${installer}"
  fi

  bash "${installer}" -b -u -p "${MINICONDA_ROOT}"
  popd >/dev/null
  rm -rf "${tmp_dir}"

  CONDA_BIN="${MINICONDA_ROOT}/bin/conda"
  [[ -x "${CONDA_BIN}" ]] || {
    log "Miniconda installation failed: conda executable not found."
    exit 1
  }
}

ensure_conda() {
  if command -v conda >/dev/null 2>&1; then
    CONDA_BIN="$(command -v conda)"
    log "Found Conda: ${CONDA_BIN}. Skip installation."
    return
  fi

  if [[ -x "${MINICONDA_ROOT}/bin/conda" ]]; then
    CONDA_BIN="${MINICONDA_ROOT}/bin/conda"
    log "Found existing Miniconda: ${CONDA_BIN}. Skip installation."
    return
  fi

  install_miniconda
}

prepare_source_code() {
  ensure_git
  ensure_dir "$(dirname "${REPO_DIR}")"

  if [[ -d "${REPO_DIR}/.git" ]]; then
    log "Updating existing source repository at ${REPO_DIR}"
    (
      cd "${REPO_DIR}"
      git pull --ff-only
    )
    return
  fi

  if [[ -d "${REPO_DIR}" ]]; then
    log "Directory exists but is not a git repo: ${REPO_DIR}"
    log "Please clean it or pass --repo-dir to another path."
    exit 1
  fi

  log "Cloning source from ${REPO_URL} to ${REPO_DIR}"
  git clone "${REPO_URL}" "${REPO_DIR}"
}

create_python_env() {
  local req_file
  req_file="${REPO_DIR}/requirements.txt"

  [[ -f "${req_file}" ]] || {
    log "requirements.txt not found in ${REPO_DIR}"
    exit 1
  }

  activate_conda_base
  resolve_python_env_prefix
  ensure_dir "$(dirname "${PY_ENV_PREFIX}")"

  if [[ -d "${PY_ENV_PREFIX}" ]]; then
    log "Python env already exists: ${PY_ENV_PREFIX}."
  else
    log "Creating Python env '${PY_ENV_NAME}' at ${PY_ENV_PREFIX}"
    conda create -y -p "${PY_ENV_PREFIX}" python=3.10 pip
  fi

  if [[ "${SKIP_REQUIREMENTS}" -eq 1 ]]; then
    log "Skipping requirements installation by option."
    return
  fi

  conda run -p "${PY_ENV_PREFIX}" python -m pip install --upgrade pip
  log "Installing requirements from ${req_file} (this may take some time)"
  conda run -p "${PY_ENV_PREFIX}" python -m pip install -r "${req_file}"
}

resolve_or_install_freesurfer() {
  if [[ "${INSTALL_FREESURFER}" -eq 0 ]]; then
    FREESURFER_STATUS="skipped_by_option"
    log "Skipping FreeSurfer installation by user option."
    return
  fi

  if command -v recon-all >/dev/null 2>&1; then
    FREESURFER_STATUS="use_system"
    log "Found system FreeSurfer: $(command -v recon-all). Skip installation."
    return
  fi

  if [[ -x "${CONDA_ENV_PREFIX}/bin/recon-all" ]]; then
    FREESURFER_STATUS="use_existing_prefix"
    log "Found FreeSurfer in target prefix: ${CONDA_ENV_PREFIX}. Skip installation."
    return
  fi

  activate_conda_base
  ensure_dir "$(dirname "${CONDA_ENV_PREFIX}")"
  log "FreeSurfer not found. Installing to ${CONDA_ENV_PREFIX}"
  conda create -y -p "${CONDA_ENV_PREFIX}" -c conda-forge freesurfer
  FREESURFER_STATUS="installed_in_prefix"
}

verify_installation() {
  log "Verifying Nextflow"
  "${NEXTFLOW_BIN}" -version >/dev/null

  log "Verifying Conda"
  "${CONDA_BIN}" --version >/dev/null

  log "Verifying Python env (${PY_ENV_NAME})"
  conda run -p "${PY_ENV_PREFIX}" python -c "import sys; print(sys.version)" >/dev/null

  if [[ "${INSTALL_FREESURFER}" -eq 0 ]]; then
    return
  fi

  log "Verifying FreeSurfer"
  if [[ "${FREESURFER_STATUS}" == "use_system" ]]; then
    recon-all -version >/dev/null
  else
    conda run -p "${CONDA_ENV_PREFIX}" recon-all -version >/dev/null
  fi
}

write_env_file() {
  local env_file conda_root
  env_file="${INSTALL_ROOT}/env.sh"
  conda_root="$(get_conda_root)"

  ensure_dir "${INSTALL_ROOT}"

  {
    echo "#!/usr/bin/env bash"
    echo "# Source this file to enable local MEGFlow dev tools"
    echo "export MEGFLOW_DEV_ROOT=\"${INSTALL_ROOT}\""
    echo "export MEGFLOW_SRC_DIR=\"${REPO_DIR}\""
    echo "export PATH=\"$(dirname "${NEXTFLOW_BIN}"):\${PATH}\""
    echo "# shellcheck disable=SC1091"
    echo "source \"${conda_root}/etc/profile.d/conda.sh\""
    echo "conda activate \"${PY_ENV_PREFIX}\""
    if [[ "${INSTALL_FREESURFER}" -eq 1 && "${FREESURFER_STATUS}" != "use_system" ]]; then
      echo "export FREESURFER_HOME=\"${CONDA_ENV_PREFIX}\""
      echo "export PATH=\"${CONDA_ENV_PREFIX}/bin:\${PATH}\""
    fi
  } > "${env_file}"

  chmod +x "${env_file}"
  log "Environment helper generated: ${env_file}"
}

print_summary() {
  log "================ Installation Summary ================"
  log "Install root      : ${INSTALL_ROOT}"
  log "Source repo       : ${REPO_DIR}"
  log "Repo URL          : ${REPO_URL}"
  log "Nextflow bin      : ${NEXTFLOW_BIN}"
  log "Conda binary      : ${CONDA_BIN}"
  log "Python env prefix : ${PY_ENV_PREFIX}"
  if [[ "${INSTALL_FREESURFER}" -eq 1 ]]; then
    log "FreeSurfer prefix : ${CONDA_ENV_PREFIX}"
    log "FreeSurfer status : ${FREESURFER_STATUS}"
  else
    log "FreeSurfer        : skipped by option"
  fi
  log "Skip requirements : ${SKIP_REQUIREMENTS}"
  log "Env helper        : ${INSTALL_ROOT}/env.sh"
  log "====================================================="

  log "Next steps:"
  log "  source ${INSTALL_ROOT}/env.sh"
  log "  cd ${REPO_DIR}"
  log "  nextflow info"
  log "  python -c 'import mne; print(mne.__version__)'"
  if [[ "${INSTALL_FREESURFER}" -eq 1 ]]; then
    log "  FreeSurfer still requires a valid license file at runtime."
  fi
}

main() {
  parse_args "$@"

  [[ -n "${MINICONDA_ROOT}" ]] || MINICONDA_ROOT="${INSTALL_ROOT}/miniconda3"
  [[ -n "${REPO_DIR}" ]] || REPO_DIR="${INSTALL_ROOT}/src/megflow"
  [[ -n "${CONDA_ENV_PREFIX}" ]] || CONDA_ENV_PREFIX="${INSTALL_ROOT}/freesurfer/conda-env"

  log "Install root: ${INSTALL_ROOT}"
  log "Install FreeSurfer: ${INSTALL_FREESURFER}"
  log "Repo URL: ${REPO_URL}"
  log "Repo dir: ${REPO_DIR}"
  log "Miniconda root: ${MINICONDA_ROOT}"
  log "FreeSurfer Conda prefix: ${CONDA_ENV_PREFIX}"

  ensure_dir "${INSTALL_ROOT}"
  prepare_source_code
  resolve_or_install_nextflow
  ensure_conda
  create_python_env
  resolve_or_install_freesurfer
  verify_installation
  write_env_file
  print_summary

  log "Done."
}

main "$@"
