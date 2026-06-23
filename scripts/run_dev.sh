#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Start Velvet Runtime using repo-local development-only state.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${VELVET_DEV_PYTHON:-python3}"
ENV_FILE="${VELVET_DEV_ENV_FILE:-${REPO_ROOT}/.velvet-dev/env.sh}"
CHECK_ONLY=false

usage() {
  cat <<'EOF'
Usage: ./scripts/run_dev.sh [--check]

  --check   Bootstrap if needed, run Velvet doctor, then exit.
EOF
}

case "${1:-}" in
  "") ;;
  --check) CHECK_ONLY=true ;;
  -h|--help) usage; exit 0 ;;
  *) echo "Unknown argument: $1" >&2; usage >&2; exit 64 ;;
esac

cd "${REPO_ROOT}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[VELVET DEV] Development state is missing; creating it now."
  "${PYTHON_BIN}" "${REPO_ROOT}/scripts/bootstrap_dev_state.py"
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[VELVET DEV] Bootstrap did not create environment file: ${ENV_FILE}" >&2
  exit 2
fi

# Generated locally by bootstrap_dev_state.py and ignored by Git.
# shellcheck disable=SC1090
source "${ENV_FILE}"

export VELVET_RUNTIME_MODE="development-read-only"

echo "[VELVET DEV] Running startup doctor."
"${PYTHON_BIN}" "${REPO_ROOT}/velvet_cli.py" doctor

if [[ "${CHECK_ONLY}" == true ]]; then
  echo "[VELVET DEV] Read-only development state is ready."
  exit 0
fi

echo "[VELVET DEV] Starting Velvet Runtime in development-read-only mode."
echo "[VELVET DEV] Press Ctrl+C for a clean shutdown."
exec "${PYTHON_BIN}" "${REPO_ROOT}/main.py"
