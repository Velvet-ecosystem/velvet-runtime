#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Safe, read-only first-run helper for Velvet Runtime on the Founder UP2.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${VELVET_DEV_PYTHON:-python3}"
ENV_FILE="${VELVET_DEV_ENV_FILE:-${REPO_ROOT}/.velvet-dev/env.sh}"

fail() {
  echo "[VELVET FIRST RUN] BLOCKED: $*" >&2
  exit 2
}

command -v git >/dev/null 2>&1 || fail "git is not installed"
command -v "${PYTHON_BIN}" >/dev/null 2>&1 || fail "${PYTHON_BIN} is not available"

cd "${REPO_ROOT}"

[[ -f main.py ]] || fail "main.py was not found in ${REPO_ROOT}"
[[ -f velvet_cli.py ]] || fail "velvet_cli.py was not found in ${REPO_ROOT}"
[[ -f scripts/bootstrap_dev_state.py ]] || fail "development bootstrap is missing"

echo "[VELVET FIRST RUN] Repository: ${REPO_ROOT}"
echo "[VELVET FIRST RUN] Git: $(git --version)"
echo "[VELVET FIRST RUN] Python: $(${PYTHON_BIN} --version 2>&1)"

if ! "${PYTHON_BIN}" - <<'PY'
import importlib.util
import sys
required = ("velvet_event_protocol", "velvet_continuity")
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    print("missing local packages: " + ", ".join(missing), file=sys.stderr)
    raise SystemExit(1)
PY
then
  fail "required local packages are missing; install the sibling Velvet packages before continuing"
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[VELVET FIRST RUN] Creating development-only local state."
  "${PYTHON_BIN}" scripts/bootstrap_dev_state.py
fi

[[ -f "${ENV_FILE}" ]] || fail "bootstrap did not create ${ENV_FILE}"

# shellcheck disable=SC1090
source "${ENV_FILE}"
export VELVET_RUNTIME_MODE="development-read-only"

echo "[VELVET FIRST RUN] Running startup doctor."
"${PYTHON_BIN}" velvet_cli.py doctor

echo "[VELVET FIRST RUN] Capturing first-boot snapshot."
"${PYTHON_BIN}" velvet_cli.py boot-snapshot > .velvet-dev/first-boot-snapshot.json
cat .velvet-dev/first-boot-snapshot.json

cat <<'EOF'

[VELVET FIRST RUN] SAFE CHECK COMPLETE

No system service was installed, enabled, started, restarted, or modified.
No production identity or key material was generated.
No physical presence or hardware authority was granted.

Next manual command, when ready to start the read-only development Runtime:

  bash scripts/run_dev.sh
EOF
