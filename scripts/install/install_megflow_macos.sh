#!/usr/bin/env bash

set -euo pipefail

IMAGE_TAG="${1:-latest}"
IMAGE="cplmeg/megflow:${IMAGE_TAG}"

log() {
  echo "[megflow-install][macos] $*"
}

validate_inputs() {
  if [[ -z "${IMAGE_TAG}" ]]; then
    log "Image tag cannot be empty."
    exit 1
  fi
}

ensure_macos() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    log "This script is for macOS only."
    exit 1
  fi
}

ensure_docker_desktop() {
  if command -v docker >/dev/null 2>&1; then
    log "Docker CLI is already installed."
  else
    log "Docker not found. Installing Docker Desktop via Homebrew."
    if ! command -v brew >/dev/null 2>&1; then
      log "Homebrew not found. Please install Homebrew first: https://brew.sh/"
      exit 1
    fi
    brew install --cask docker
  fi

  if ! docker info >/dev/null 2>&1; then
    log "Docker daemon is not ready. Trying to launch Docker Desktop."
    open -a Docker || true
    for _ in $(seq 1 30); do
      if docker info >/dev/null 2>&1; then
        break
      fi
      sleep 2
    done
  fi

  if ! docker info >/dev/null 2>&1; then
    log "Docker is still not ready. Please start Docker Desktop manually and retry."
    exit 1
  fi
}

main() {
  ensure_macos
  validate_inputs
  log "Target image: ${IMAGE}"
  ensure_docker_desktop

  log "Pulling MEGFlow Docker image..."
  docker pull "${IMAGE}"

  log "Running '-h' to validate installation (help output should print below)..."
  docker run --rm "${IMAGE}" -h

  log "Validation completed."
}

main "$@"
