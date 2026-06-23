#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_SRC="${REPO_ROOT}/deploy/systemd/velvet-runtime.service"
ENV_SRC="${REPO_ROOT}/deploy/systemd/runtime.env.example"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/systemd/install_up2_service.sh" >&2
  exit 1
fi

if ! id velvet >/dev/null 2>&1; then
  useradd --system --home /opt/velvet --shell /usr/sbin/nologin velvet
fi

install -d -o velvet -g velvet -m 0750 /opt/velvet/runtime /opt/velvet/state
install -d -o root -g velvet -m 0750 /etc/velvet
install -m 0644 "${SERVICE_SRC}" /etc/systemd/system/velvet-runtime.service

if [[ ! -f /etc/velvet/runtime.env ]]; then
  install -m 0640 -o root -g velvet "${ENV_SRC}" /etc/velvet/runtime.env
fi

systemctl daemon-reload

echo "Installed velvet-runtime.service."
echo "Before enabling it:"
echo "  1. copy the repository to /opt/velvet/runtime"
echo "  2. provision local production identity, proof, policy, and keys"
echo "  3. run: sudo -u velvet /usr/bin/python3 /opt/velvet/runtime/velvet_cli.py doctor"
echo "  4. enable: systemctl enable --now velvet-runtime.service"
