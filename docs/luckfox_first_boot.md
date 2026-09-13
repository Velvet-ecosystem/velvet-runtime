# Luckfox Lyra First-Boot Bootstrap

This procedure is for a box-fresh Luckfox Lyra-class subordinate node before it is assigned a Velvet role.

The goal is deliberately narrow:

1. discover and log into the factory image,
2. capture a factory-state audit before meaningful changes,
3. establish the minimum Velvet filesystem and hostname baseline,
4. verify SSH access survives a reboot,
5. only then assign a role and deploy Runtime or other services.

The bootstrap does **not** grant physical authority, install Runtime, update packages, reflash firmware, or assign the node as Velour/OEM/etc.

## Vendor access facts

Luckfox currently documents two common factory login profiles for Lyra:

- Buildroot: user `root`
- Ubuntu 22.04: user `lyra`

The vendor documentation should be treated as the source of truth for the shipped password and USB-network fallback address. Do not put long-lived production secrets in this repository.

Official references:

- https://wiki.luckfox.com/Luckfox-Lyra/Login/
- https://wiki.luckfox.com/Luckfox-Lyra/Getting-Started/Image-flashing/

Ethernet + SSH is the preferred normal first-access path. ADB is a fallback. Rockchip `upgrade_tool` is a recovery/reimage tool and is intentionally outside the normal first-boot path.

## 1. Prepare the Founder/host

From the repository root:

```bash
sh deploy/luckfox/check_host_tools.sh
```

Required for the normal workflow:

- `ssh`
- `scp`
- `git`
- `curl`
- `python3`

Useful but optional:

- `rsync`
- `nmap`
- `ip` / `arp`
- `adb`

On an Ubuntu host, missing normal tools can typically be installed with the distribution package manager. Do not install Rockchip flashing tools merely for a normal first boot.

## 2. Power only one Lyra first

Bring up the first board by itself. Connect it to the same Ethernet LAN as the Founder/UP Squared and confirm link activity.

Find its DHCP lease using the router/switch information, `ip neigh`, or `nmap` if available. Do not assume an Ethernet IP address from the vendor USB-network address.

Example discovery commands:

```bash
ip neigh
nmap -sn 192.168.1.0/24
```

Adjust the subnet to the actual bench LAN.

## 3. First login

Use the account appropriate to the factory image.

```bash
ssh lyra@<NODE-IP>
```

or, for a Buildroot image:

```bash
ssh root@<NODE-IP>
```

At this point, do not run a full package upgrade and do not reflash the board.

## 4. Capture the untouched factory audit

The audit mode is designed to be read-only. It prints the board identity, kernel, OS information, CPU/memory data, storage, interfaces, route state, available tools, local accounts, and the explicit Velvet authority boundary.

Run it remotely without permanently copying the script to the board:

```bash
ssh <FACTORY-USER>@<NODE-IP> 'sh -s audit' \
  < deploy/luckfox/luckfox_first_boot.sh \
  | tee luckfox_factory_audit_01.txt
```

Keep that audit as first-wake evidence. When the second Lyra is eventually powered for the first time, capture a separate audit for it rather than assuming both units shipped identically.

## 5. Prepare SSH-key access

If the Founder does not already have an operator SSH key, create one interactively on the Founder:

```bash
ssh-keygen -t ed25519
```

Copy only the public key to the Lyra. One simple path is:

```bash
scp ~/.ssh/id_ed25519.pub <FACTORY-USER>@<NODE-IP>:/tmp/velvet_operator.pub
scp deploy/luckfox/luckfox_first_boot.sh <FACTORY-USER>@<NODE-IP>:/tmp/
```

The bootstrap appends the public key and preserves existing `authorized_keys` content. It deliberately does not disable password login. First prove that key authentication and reboot recovery work; hardening can happen afterward without gambling on a lockout.

## 6. Apply the role-neutral Velvet baseline

Choose a temporary or final node hostname. Role assignment remains separate.

Ubuntu-style example:

```bash
ssh lyra@<NODE-IP>
sudo sh /tmp/luckfox_first_boot.sh apply \
  --hostname velvet-node-01 \
  --operator-user lyra \
  --authorized-key-file /tmp/velvet_operator.pub
```

Buildroot-style example when already logged in as root:

```bash
sh /tmp/luckfox_first_boot.sh apply \
  --hostname velvet-node-01 \
  --operator-user root \
  --authorized-key-file /tmp/velvet_operator.pub
```

Apply mode creates only the minimum neutral skeleton:

```text
/opt/velvet/
/opt/velvet/runtime/
/opt/velvet/state/
/opt/velvet/state/bootstrap/
/opt/velvet/state/receipts/
/opt/velvet/state/recovery/
```

It writes:

```text
/opt/velvet/state/bootstrap/first_boot_baseline.txt
```

That receipt explicitly records:

```text
role=unassigned
runtime_installed=false
physical_authority=none
package_upgrade_performed=false
firmware_reflash_performed=false
```

## 7. Reboot verification

Before installing any Velvet role services:

```bash
sudo reboot
```

Then verify:

```bash
ssh <FACTORY-USER>@<NODE-IP>
hostname
cat /opt/velvet/state/bootstrap/first_boot_baseline.txt
```

Confirm the operator SSH key works after reboot. Preserve password access until key access is proven.

## 8. Stop point before role assignment

A correctly bootstrapped Lyra should now be:

- reachable over the Velvet LAN,
- carrying a recorded factory audit,
- using its intended hostname,
- reachable through a tested SSH key,
- holding the neutral Velvet filesystem skeleton,
- explicitly role-unassigned,
- carrying no Runtime physical authority.

Only after this checkpoint should the node become, for example, the Librarian/Security surface or the Runtime/OEM surface.

## Safety and continuity rules

- Never generate or commit production private keys in this repository.
- Never treat a hostname or role name as authority.
- Never copy the Founder continuity identity/proof material onto a subordinate node.
- Never reflash a box-fresh node before its shipped state has been captured unless recovery makes that unavoidable.
- Never enable physical control merely because Runtime is installed.
- Preserve each node's first-wake audit and bootstrap receipt as evidence.
