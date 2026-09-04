#!/bin/sh
set -eu

usage() {
    echo "Usage: $0 --config /absolute/path/node.json [--enable]" >&2
    exit 2
}

CONFIG=""
ENABLE=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --config)
            [ "$#" -ge 2 ] || usage
            CONFIG=$2
            shift 2
            ;;
        --enable)
            ENABLE=1
            shift
            ;;
        *)
            usage
            ;;
    esac
done

[ -n "$CONFIG" ] || usage
case "$CONFIG" in
    /*) ;;
    *) echo "--config must be an absolute path" >&2; exit 2 ;;
esac

if [ "$(id -u)" -ne 0 ]; then
    echo "install_headless_node.sh must run as root" >&2
    exit 1
fi
if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl is required; use the Buildroot deployment path on non-systemd hosts" >&2
    exit 1
fi
if [ ! -r "$CONFIG" ]; then
    echo "configuration is not readable: $CONFIG" >&2
    exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
EXPECTED_REPO=/opt/velvet/velvet-runtime
if [ "$REPO_ROOT" != "$EXPECTED_REPO" ]; then
    echo "headless systemd deployment expects the Runtime repository at $EXPECTED_REPO" >&2
    echo "current repository is: $REPO_ROOT" >&2
    exit 1
fi

UNIT="$REPO_ROOT/deploy/headless/systemd/velvet-headless-node.service"
[ -r "$UNIT" ] || { echo "missing headless systemd unit" >&2; exit 1; }
[ -r "$REPO_ROOT/services/headless_node_supervisor.py" ] || {
    echo "missing headless node supervisor" >&2
    exit 1
}

if ! id velvet >/dev/null 2>&1; then
    useradd --system --home /nonexistent --shell /usr/sbin/nologin velvet
fi
install -d -o root -g velvet -m 0750 /etc/velvet
install -d -o velvet -g velvet -m 0750 /var/lib/velvet-node
install -o root -g velvet -m 0640 "$CONFIG" /etc/velvet/node.json
install -o root -g root -m 0644 "$UNIT" /etc/systemd/system/velvet-headless-node.service
systemctl daemon-reload

if [ "$ENABLE" -eq 1 ]; then
    systemctl enable --now velvet-headless-node.service
    echo "Velvet headless node installed and started."
else
    echo "Velvet headless node installed. Enable with:"
    echo "  systemctl enable --now velvet-headless-node.service"
fi
