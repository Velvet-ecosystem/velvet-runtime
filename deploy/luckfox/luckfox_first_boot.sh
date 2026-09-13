#!/usr/bin/env sh
# SPDX-License-Identifier: GPL-3.0-only
# Conservative first-boot bootstrap for Luckfox Lyra class subordinate nodes.
#
# Default mode is audit and is read-only apart from normal process side effects.
# Apply mode makes only the explicit local changes described in --help.

set -eu

MODE="audit"
NODE_NAME=""
OPERATOR_USER=""
AUTHORIZED_KEY_FILE=""
STATE_ROOT="/opt/velvet/state"

usage() {
    cat <<'USAGE'
Usage:
  sh luckfox_first_boot.sh audit
  sudo sh luckfox_first_boot.sh apply --hostname NAME [options]

Modes:
  audit                 Print a factory-state inventory to stdout. No package
                        installs, upgrades, reflashes, account changes, or
                        network changes are performed.
  apply                 Establish the minimum role-neutral Velvet node baseline.

Apply options:
  --hostname NAME       Required. Set the persistent node hostname.
  --operator-user USER  Existing account that should receive an SSH public key.
  --authorized-key-file PATH
                        Public-key file already present on the node. Requires
                        --operator-user. Existing authorized_keys content is kept.
  --state-root PATH     Velvet state root. Default: /opt/velvet/state
  -h, --help            Show this help.

Apply creates the Velvet directory skeleton, records a bootstrap receipt, and
sets the hostname. It deliberately does NOT update packages, reflash firmware,
disable password login, alter firewall rules, install Runtime, assign a role,
or grant physical authority.
USAGE
}

fatal() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

need_root() {
    [ "$(id -u)" -eq 0 ] || fatal "apply mode must run as root"
}

safe_name() {
    case "$1" in
        ''|*[!a-zA-Z0-9.-]*) return 1 ;;
        *) return 0 ;;
    esac
}

print_file_if_readable() {
    label="$1"
    path="$2"
    printf '\n[%s]\n' "$label"
    if [ -r "$path" ]; then
        cat "$path"
    else
        printf 'unavailable: %s\n' "$path"
    fi
}

run_if_present() {
    label="$1"
    command_name="$2"
    shift 2
    printf '\n[%s]\n' "$label"
    if command -v "$command_name" >/dev/null 2>&1; then
        "$command_name" "$@" 2>&1 || true
    else
        printf 'command unavailable: %s\n' "$command_name"
    fi
}

audit() {
    printf '%s\n' 'VELVET_LUCKFOX_FACTORY_AUDIT_V1'
    printf 'captured_utc=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || printf unknown)"
    printf 'hostname=%s\n' "$(hostname 2>/dev/null || printf unknown)"
    printf 'uid=%s\n' "$(id -u 2>/dev/null || printf unknown)"
    printf 'uname=%s\n' "$(uname -a 2>/dev/null || printf unknown)"

    print_file_if_readable "os-release" /etc/os-release
    print_file_if_readable "machine-id" /etc/machine-id
    print_file_if_readable "cpuinfo" /proc/cpuinfo
    print_file_if_readable "cmdline" /proc/cmdline
    print_file_if_readable "meminfo" /proc/meminfo

    run_if_present "block-devices" lsblk -a
    run_if_present "disk-usage" df -h
    run_if_present "interfaces" ip addr
    run_if_present "routes" ip route
    run_if_present "links" ip link
    run_if_present "processes" ps

    printf '\n[tool-presence]\n'
    for tool in sh bash ssh sshd dropbear git curl wget python3 pip3 systemctl hostnamectl apt apt-get apk opkg busybox; do
        if command -v "$tool" >/dev/null 2>&1; then
            printf '%s=%s\n' "$tool" "$(command -v "$tool")"
        else
            printf '%s=missing\n' "$tool"
        fi
    done

    printf '\n[passwd-accounts]\n'
    if [ -r /etc/passwd ]; then
        awk -F: '{print $1 ":" $3 ":" $4 ":" $6 ":" $7}' /etc/passwd
    else
        printf 'unavailable: /etc/passwd\n'
    fi

    printf '\n[velvet-boundary]\n'
    printf '%s\n' 'role=unassigned'
    printf '%s\n' 'runtime_installed=false'
    printf '%s\n' 'physical_authority=none'
    printf '%s\n' 'factory_state_preserved=true'
}

ensure_operator_key() {
    user_name="$1"
    key_file="$2"

    id "$user_name" >/dev/null 2>&1 || fatal "operator user does not exist: $user_name"
    [ -r "$key_file" ] || fatal "authorized key file is not readable: $key_file"

    home_dir="$(awk -F: -v u="$user_name" '$1 == u {print $6}' /etc/passwd)"
    [ -n "$home_dir" ] || fatal "could not determine home directory for $user_name"

    group_name="$(id -gn "$user_name" 2>/dev/null || printf '%s' "$user_name")"
    mkdir -p "$home_dir/.ssh"
    chown "$user_name:$group_name" "$home_dir/.ssh"
    chmod 0700 "$home_dir/.ssh"
    touch "$home_dir/.ssh/authorized_keys"
    chown "$user_name:$group_name" "$home_dir/.ssh/authorized_keys"
    chmod 0600 "$home_dir/.ssh/authorized_keys"

    while IFS= read -r key_line; do
        [ -n "$key_line" ] || continue
        case "$key_line" in \#*) continue ;; esac
        if ! grep -Fqx "$key_line" "$home_dir/.ssh/authorized_keys" 2>/dev/null; then
            printf '%s\n' "$key_line" >> "$home_dir/.ssh/authorized_keys"
        fi
    done < "$key_file"

    chown "$user_name:$group_name" "$home_dir/.ssh/authorized_keys"
}

set_node_hostname() {
    new_name="$1"
    if command -v hostnamectl >/dev/null 2>&1; then
        hostnamectl set-hostname "$new_name"
    else
        printf '%s\n' "$new_name" > /etc/hostname
        hostname "$new_name"
    fi
}

apply_baseline() {
    need_root
    [ -n "$NODE_NAME" ] || fatal "--hostname is required in apply mode"
    safe_name "$NODE_NAME" || fatal "hostname contains unsupported characters"

    if [ -n "$AUTHORIZED_KEY_FILE" ] && [ -z "$OPERATOR_USER" ]; then
        fatal "--authorized-key-file requires --operator-user"
    fi

    set_node_hostname "$NODE_NAME"

    mkdir -p /opt/velvet /opt/velvet/runtime
    mkdir -p "$STATE_ROOT" "$STATE_ROOT/bootstrap" "$STATE_ROOT/receipts" "$STATE_ROOT/recovery"
    chmod 0755 /opt/velvet /opt/velvet/runtime
    chmod 0750 "$STATE_ROOT" "$STATE_ROOT/bootstrap" "$STATE_ROOT/receipts" "$STATE_ROOT/recovery"

    if [ -n "$AUTHORIZED_KEY_FILE" ]; then
        ensure_operator_key "$OPERATOR_USER" "$AUTHORIZED_KEY_FILE"
    fi

    receipt="$STATE_ROOT/bootstrap/first_boot_baseline.txt"
    umask 027
    {
        printf '%s\n' 'VELVET_LUCKFOX_FIRST_BOOT_BASELINE_V1'
        printf 'applied_utc=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || printf unknown)"
        printf 'hostname=%s\n' "$NODE_NAME"
        printf 'kernel=%s\n' "$(uname -sr 2>/dev/null || printf unknown)"
        printf 'architecture=%s\n' "$(uname -m 2>/dev/null || printf unknown)"
        printf 'operator_user=%s\n' "${OPERATOR_USER:-unchanged}"
        printf 'ssh_key_installed=%s\n' "$( [ -n "$AUTHORIZED_KEY_FILE" ] && printf true || printf false )"
        printf '%s\n' 'role=unassigned'
        printf '%s\n' 'runtime_installed=false'
        printf '%s\n' 'physical_authority=none'
        printf '%s\n' 'package_upgrade_performed=false'
        printf '%s\n' 'firmware_reflash_performed=false'
    } > "$receipt"
    chmod 0640 "$receipt"

    printf 'Velvet node baseline applied.\n'
    printf 'hostname: %s\n' "$NODE_NAME"
    printf 'receipt: %s\n' "$receipt"
    printf '%s\n' 'role remains unassigned; Runtime and physical authority remain absent.'
}

if [ "$#" -gt 0 ]; then
    MODE="$1"
    shift
fi

case "$MODE" in
    -h|--help|help)
        usage
        exit 0
        ;;
    audit|apply)
        ;;
    *)
        usage >&2
        fatal "unknown mode: $MODE"
        ;;
esac

while [ "$#" -gt 0 ]; do
    case "$1" in
        --hostname)
            [ "$#" -ge 2 ] || fatal "--hostname requires a value"
            NODE_NAME="$2"
            shift 2
            ;;
        --operator-user)
            [ "$#" -ge 2 ] || fatal "--operator-user requires a value"
            OPERATOR_USER="$2"
            shift 2
            ;;
        --authorized-key-file)
            [ "$#" -ge 2 ] || fatal "--authorized-key-file requires a value"
            AUTHORIZED_KEY_FILE="$2"
            shift 2
            ;;
        --state-root)
            [ "$#" -ge 2 ] || fatal "--state-root requires a value"
            STATE_ROOT="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fatal "unknown option: $1"
            ;;
    esac
done

case "$MODE" in
    audit) audit ;;
    apply) apply_baseline ;;
esac
