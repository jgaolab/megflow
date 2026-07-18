#!/usr/bin/env bash

set -euo pipefail

IMAGE_TAG="${1:-latest}"
RUNTIME_MODE="${2:-auto}" # auto | docker | apptainer
IMAGE="cmrlab/megflow:${IMAGE_TAG}"
SIF_PATH="${MEGFLOW_SIF_PATH:-./megflow_${IMAGE_TAG}.sif}"
RUNTIME=""

log() {
  echo "[megflow-install][linux] $*"
}

validate_inputs() {
  if [[ -z "${IMAGE_TAG}" ]]; then
    log "Image tag cannot be empty."
    exit 1
  fi
}

ensure_linux() {
  if [[ "$(uname -s)" != "Linux" ]]; then
    log "This script is for Linux only."
    exit 1
  fi
}

require_root_if_needed() {
  if [[ "${EUID}" -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
      SUDO="sudo"
    else
      log "Not running as root and sudo is unavailable; cannot auto-install Docker."
      exit 1
    fi
  else
    SUDO=""
  fi
}

install_docker_linux() {
  if command -v docker >/dev/null 2>&1; then
    log "Docker is already installed. Skipping installation."
    return
  fi

  require_root_if_needed
  log "Docker not found. Installing Docker."

  if command -v apt-get >/dev/null 2>&1; then
    ${SUDO} apt-get update
    ${SUDO} apt-get install -y docker.io
  elif command -v dnf >/dev/null 2>&1; then
    ${SUDO} dnf install -y docker
  elif command -v yum >/dev/null 2>&1; then
    ${SUDO} yum install -y docker
  elif command -v zypper >/dev/null 2>&1; then
    ${SUDO} zypper --non-interactive install docker
  elif command -v pacman >/dev/null 2>&1; then
    ${SUDO} pacman -Sy --noconfirm docker
  else
    log "Unsupported Linux package manager. Please install Docker manually and retry."
    exit 1
  fi
}

start_docker_linux() {
  # Docker may already be reachable for current user; avoid requiring sudo in that case.
  if docker info >/dev/null 2>&1; then
    return
  fi

  require_root_if_needed

  if command -v systemctl >/dev/null 2>&1; then
    ${SUDO} systemctl enable --now docker || true
  elif command -v service >/dev/null 2>&1; then
    ${SUDO} service docker start || true
  fi

  if ! docker info >/dev/null 2>&1; then
    log "Docker daemon is unavailable. Ensure Docker service is running and current user can run docker."
    exit 1
  fi
}

install_apptainer_linux() {
  if command -v apptainer >/dev/null 2>&1 || command -v singularity >/dev/null 2>&1; then
    log "Apptainer/Singularity is already installed. Skipping installation."
    return
  fi

  require_root_if_needed
  log "Apptainer/Singularity not found. Attempting to install."

  if command -v apt-get >/dev/null 2>&1; then
    ${SUDO} apt-get update
    ${SUDO} apt-get install -y apptainer || ${SUDO} apt-get install -y singularity-container
  elif command -v dnf >/dev/null 2>&1; then
    ${SUDO} dnf install -y apptainer || ${SUDO} dnf install -y singularity
  elif command -v yum >/dev/null 2>&1; then
    ${SUDO} yum install -y apptainer || ${SUDO} yum install -y singularity
  elif command -v zypper >/dev/null 2>&1; then
    ${SUDO} zypper --non-interactive install apptainer || ${SUDO} zypper --non-interactive install singularity
  elif command -v pacman >/dev/null 2>&1; then
    ${SUDO} pacman -Sy --noconfirm apptainer || ${SUDO} pacman -Sy --noconfirm singularity
  else
    log "Unsupported package manager. Please install Apptainer or Singularity manually and retry."
    exit 1
  fi
}

apptainer_cmd() {
  if command -v apptainer >/dev/null 2>&1; then
    echo "apptainer"
  elif command -v singularity >/dev/null 2>&1; then
    echo "singularity"
  else
    echo ""
  fi
}

docker_usable() {
  command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
}

select_runtime() {
  case "${RUNTIME_MODE}" in
    docker)
      RUNTIME="docker"
      ;;
    apptainer)
      RUNTIME="apptainer"
      ;;
    auto)
      if docker_usable; then
        RUNTIME="docker"
      else
        RUNTIME="apptainer"
      fi
      ;;
    *)
      log "Invalid runtime mode: ${RUNTIME_MODE}. Use: auto | docker | apptainer"
      exit 1
      ;;
  esac
}

run_docker_flow() {
  install_docker_linux
  start_docker_linux

  log "Pulling MEGFlow Docker image..."
  docker pull "${IMAGE}"

  log "Running '-h' to validate installation (help output should print below)..."
  docker run --rm "${IMAGE}" -h
}

run_apptainer_flow() {
  local appt

  install_apptainer_linux
  appt="$(apptainer_cmd)"
  if [[ -z "${appt}" ]]; then
    log "Apptainer/Singularity is not available after installation attempt."
    exit 1
  fi

  log "Pulling MEGFlow image through ${appt} from docker://..."
  log "Output SIF: ${SIF_PATH}"
  "${appt}" pull --force "${SIF_PATH}" "docker://${IMAGE}"

  log "Running '-h' to validate installation (help output should print below)..."
  if ! "${appt}" run "${SIF_PATH}" -h; then
    log "Primary validation via '${appt} run ... -h' failed; trying '${appt} exec ... -h'."
    "${appt}" exec "${SIF_PATH}" /program/nextflow/run.sh -h || {
      log "Validation failed for Apptainer/Singularity image."
      exit 1
    }
  fi
}

main() {
  ensure_linux
  validate_inputs
  log "Target image: ${IMAGE}"
  select_runtime
  log "Selected runtime: ${RUNTIME}"

  if [[ "${RUNTIME}" == "docker" ]]; then
    run_docker_flow
  else
    run_apptainer_flow
  fi

  log "Validation completed."
}

main "$@"
