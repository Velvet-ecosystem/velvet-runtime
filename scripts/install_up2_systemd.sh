#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail

RUNTIME_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="velvet"
SERVICE_GROUP="velvet"
ENABLE_NOW=0

usage() {
  cat <<'EOF'
Install Velvet Runtime as a hardened, read-only systemd service.

Usage:
  sudo bash scripts/install_up2_systemd.sh [options]

Options:
  --runtime-root PATH   Runtime checkout path (default: current checkout)
  --user NAME           Service user (default: velvet)
  --group NAME          Service group (default: velvet)
  --enable-now          Enable and start the service immediately
  -h, --help            Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime-root)
      RUNTIME_ROOT="$(readlink -f "$2")"
      shift 2
      ;;
    --user)
      SERVICE_USER="$2"
      shift 2
      ;;
    --group)
      SERVICE_GROUP="$2"
      shift 2
      ;;
    --enable-now)
      ENABLE_NOW=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi

for required in \
  "$RUNTIME_ROOT/velvet_cli.py" \
  "$RUNTIME_ROOT/.venv/bin/python" \
  "$RUNTIME_ROOT/.velvet-dev/env.sh" \
  "$RUNTIME_ROOT/deploy/systemd/velvet-runtime.service.in"; do
  if [[ ! -e "$required" ]]; then
    echo "Required path is missing: $required" >&2
    exit 1
  fi
done

if ! getent group "$SERVICE_GROUP" >/dev/null; then
  groupadd --system "$SERVICE_GROUP"
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd \
    --system \
    --gid "$SERVICE_GROUP" \
    --home-dir /nonexistent \
    --shell /usr/sbin/nologin \
    "$SERVICE_USER"
fi

install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_GROUP" /opt/velvet/state
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$RUNTIME_ROOT/.velvet-dev"

SERVICE_PATH=/etc/systemd/system/velvet-runtime.service
sed \
  -e "s|@RUNTIME_ROOT@|$RUNTIME_ROOT|g" \
  -e "s|@SERVICE_USER@|$SERVICE_USER|g" \
  -e "s|@SERVICE_GROUP@|$SERVICE_GROUP|g" \
  "$RUNTIME_ROOT/deploy/systemd/velvet-runtime.service.in" \
  > "$SERVICE_PATH"
chmod 0644 "$SERVICE_PATH"

systemd-analyze verify "$SERVICE_PATH"
systemctl daemon-reload

printf '[Velvet] Installed %s\n' "$SERVICE_PATH"
printf '[Velvet] Runtime root: %s\n' "$RUNTIME_ROOT"
printf '[Velvet] Service identity: %s:%s\n' "$SERVICE_USER" "$SERVICE_GROUP"
printf '[Velvet] Physical authority remains disabled.\n'

if [[ "$ENABLE_NOW" -eq 1 ]]; then
  systemctl enable --now velvet-runtime.service
  systemctl --no-pager --full status velvet-runtime.service
else
  cat <<EOF
[Velvet] Service was not started automatically.
[Velvet] Review the generated unit, then run:
  sudo systemctl enable --now velvet-runtime.service
  sudo "$RUNTIME_ROOT/.venv/bin/python" "$RUNTIME_ROOT/scripts/up2_service_validate.py"
EOF
fi
