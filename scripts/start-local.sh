#!/usr/bin/env bash
# Run the API on the host with the project's existing Docker data volumes.
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not on PATH. Install Docker Desktop first." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Docker is not running. Start the Docker service, then rerun this command." >&2
    exit 1
  fi
  echo "Starting Docker Desktop and waiting for its daemon..."
  open -a Docker
  deadline=$((SECONDS + 90))
  until docker info >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "Docker did not become ready within 90 seconds. Check Docker Desktop and rerun this command." >&2
      exit 1
    fi
    sleep 2
  done
fi
if [[ ! -x venv/bin/python ]]; then
  echo "Create the Python venv and install requirements first (see README.md)." >&2
  exit 1
fi
services=(postgres redis)
if [[ "${START_MINIO:-0}" == "1" ]]; then
  services+=(minio)
fi
docker compose -f docker/docker-compose.yml up -d --wait --wait-timeout 90 "${services[@]}"
venv/bin/python -m scripts.check_dependencies
if [[ "${1:-}" == "--dependencies-only" ]]; then
  exit 0
fi
exec venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload --timeout-graceful-shutdown 5 "$@"
