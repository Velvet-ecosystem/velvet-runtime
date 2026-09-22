#!/usr/bin/env sh
# SPDX-License-Identifier: GPL-3.0-only
# Read-only host preflight for provisioning a box-fresh Luckfox Lyra.

set -eu

required="ssh scp git curl python3"
optional="rsync nmap ip arp adb"
missing_required=0

printf '%s\n' 'Velvet Luckfox host-tool preflight'
printf 'host: %s\n' "$(hostname 2>/dev/null || printf unknown)"
printf 'kernel: %s\n' "$(uname -sr 2>/dev/null || printf unknown)"
printf '\nRequired tools:\n'
for tool in $required; do
    if command -v "$tool" >/dev/null 2>&1; then
        printf '  [ok]      %s -> %s\n' "$tool" "$(command -v "$tool")"
    else
        printf '  [missing] %s\n' "$tool"
        missing_required=1
    fi
done

printf '\nOptional discovery/recovery tools:\n'
for tool in $optional; do
    if command -v "$tool" >/dev/null 2>&1; then
        printf '  [ok]      %s -> %s\n' "$tool" "$(command -v "$tool")"
    else
        printf '  [optional] %s\n' "$tool"
    fi
done

printf '\nNotes:\n'
printf '%s\n' '  - nmap is convenient for DHCP discovery but is not required.'
printf '%s\n' '  - adb is a fallback access path, not part of the normal Ethernet/SSH flow.'
printf '%s\n' '  - Rockchip upgrade_tool is intentionally not required for first boot.'
printf '%s\n' '  - This preflight installs or changes nothing.'

if [ "$missing_required" -ne 0 ]; then
    printf '\nResult: required host tools are missing.\n' >&2
    exit 1
fi

printf '\nResult: host is ready for normal Luckfox Ethernet/SSH bring-up.\n'
