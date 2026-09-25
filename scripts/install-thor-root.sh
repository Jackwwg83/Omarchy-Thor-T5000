#!/bin/bash
# Install the Arch Linux ARM root for the Thor port on the USB drive's RAYTONE_ROOT partition.
#
#   install-thor-root.sh --disk /dev/disk/by-id/usb-... --serial S --tools-root DIR \
#       --tarball ArchLinuxARM-aarch64-latest.tar.gz --tarball-sha256 HEX --packages DIR --user NAME \
#       [--write --confirm-serial S]
#
# Runs on JetPack as root, in a private mount namespace. Unpacks the verified Arch Linux ARM rootfs
# once with the tools root's bsdtar (keeps xattrs and file capabilities), then, in a chroot of the
# drive with sysfs read-only and no efivarfs: upgrades it, replaces linux-aarch64 with the
# raytone-thor kernel, firmware and core packages, and configures the system.
#
# Accounts: the rootfs's default "alarm" user is removed and root is locked. NAME gets uid 1000,
# its JetPack password hash (never printed) and its SSH authorized_keys; the JetPack NetworkManager
# profiles are copied so the drive joins the same network. A temporary passwordless sudo rule for
# NAME (/etc/sudoers.d/raytone-temp) exists for the bring-up and must be removed afterwards.
#
# Unattended safety, for a first boot nobody watches: emergency and rescue mode reboot instead of
# waiting at a shell, a dead-man timer reboots after 20 minutes unless /run/raytone-keep exists,
# a thermal guard (scripts/thor-rootfs/thermal-guard) reboots when fan control stops or the SoC runs
# hot, a reboot that stalls is forced after 5 minutes, and a boot marker records every boot in
# /var/lib/raytone/boots.log. NVIDIA's systemd watchdog setting (RuntimeWatchdogSec=120) comes with
# raytone-thor-core. The drive gets a machine ID and a console keymap, so its first boot is not a
# systemd "first boot" (no interactive systemd-firstboot, no preset-all). The running system mounts
# efivarfs read-only once systemd-remount-fs has run. Units that can write UEFI variables or TPM
# state are masked whatever would start them (boot, a socket, logind, a generator): every unit in the
# drive's /usr/lib/systemd/system named systemd-pcr*, systemd-tpm2-*, *factory-reset*, bless-boot,
# hibernate or boot-update / boot-random-seed / boot-clear-sysfail (MASK_RE). Units elsewhere or
# under other names are not covered by this scan. systemd-repart and the sleep targets are masked
# too. Nothing that writes UEFI variables (efibootmgr, grub, fwupd)
# is installed. A dry run unless --write.
# Tests: tests/test_install_thor_root.py (RAYTONE_* variables exist for them).
set -euo pipefail

HERE=$(dirname "$(readlink -f "$0")")
ORIG_ARGS=("$@")
die() { echo "install-thor-root: $*" >&2; exit 1; }
# shellcheck source=lib/usb.sh
source "$HERE/lib/usb.sh"
# shellcheck source=lib/thor-chroot.sh
source "$HERE/lib/thor-chroot.sh"

disk='' serial='' write=0 confirm='' tools='' tarball='' tarball_sha='' pkgdir='' user='' dev=''
while (($#)); do
  case $1 in
    --disk) disk=${2:-}; shift 2 ;;
    --serial) serial=${2:-}; shift 2 ;;
    --write) write=1; shift ;;
    --confirm-serial) confirm=${2:-}; shift 2 ;;
    --tools-root) tools=${2:-}; shift 2 ;;
    --tarball) tarball=${2:-}; shift 2 ;;
    --tarball-sha256) tarball_sha=${2:-}; shift 2 ;;
    --packages) pkgdir=${2:-}; shift 2 ;;
    --user) user=${2:-}; shift 2 ;;
    *) die "unknown argument $1" ;;
  esac
done
resolve_usb_disk
[[ $user =~ ^[a-z_][a-z0-9_-]*$ ]] || die "--user NAME is required"
[[ -e $tools/usr/bin/bsdtar ]] || die "tools root '$tools' has no bsdtar"
[[ -f $tarball ]] || die "rootfs tarball '$tarball' not found"
[[ $(sha256sum "$tarball" | cut -d' ' -f1) == "$tarball_sha" ]] || die "rootfs tarball sha256 does not match $tarball_sha"
PKG_FILES=()
# raytone-thor-leetop-nic: the vendor's Wi-Fi and 2.5GbE drivers; without it the drive has no network.
for p in raytone-thor-firmware raytone-thor-linux raytone-thor-core raytone-thor-leetop-nic; do
  f=$(compgen -G "$pkgdir/$p-[0-9]*.pkg.tar.*" | grep -v '\.sig$' | sort -V | tail -1) || true
  [[ -n $f ]] || die "package $p not found in '$pkgdir'"
  PKG_FILES+=("$f")
done

MNT=${RAYTONE_TARGET_MOUNT:-/mnt/raytone-target}
HOST_ETC=${RAYTONE_HOST_ETC:-/etc}
HOST_HOME=${RAYTONE_HOST_HOME:-/home/$user}
HOST_RUN=${RAYTONE_HOST_RUN:-/run}
MIRROR=${PKG_MIRROR:-https://mirrors.tuna.tsinghua.edu.cn/archlinuxarm}
ROOT_DEV=${dev}2
HOSTNAME_=raytone-thor
BASE_PKGS=(networkmanager openssh sudo avahi nss-mdns linux-firmware-realtek wireless-regdb iw vim less htop)
UNITS=(sshd NetworkManager avahi-daemon systemd-timesyncd raytone-deadman.timer raytone-boot-start raytone-boot-marker
       raytone-thermal-guard nv-load-display-modules nvfancontrol nvpmodel nvpower)
# Masked by name wherever the target has them: units that can write UEFI variables or TPM state.
MASK_RE='^(systemd-(pcr|tpm2-|factory-reset|bless-boot|hibernate|boot-(update|random-seed|clear-sysfail))|factory-reset)'
# Masked always: interactive first-boot setup, partition changes, sleep (JetPack known issue 5525468),
# and systemd-networkd, which the Arch Linux ARM image enables next to NetworkManager.
MASK_ALWAYS=(systemd-firstboot.service systemd-repart.service
             systemd-networkd.service systemd-networkd.socket systemd-networkd-wait-online.service
             sleep.target suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target)
KVER=6.8.12-1021-tegra

# Everything a login on the drive needs is checked before anything is written.
[[ -s $HOST_HOME/.ssh/authorized_keys ]] || die "no $HOST_HOME/.ssh/authorized_keys to copy; the drive would have no SSH login"
{ set +x; } 2>/dev/null
awk -F: -v u="$user" '$1 == u {print $2}' "$HOST_ETC/shadow" 2>/dev/null | grep -q '^\$' ||
  die "no password hash for $user in $HOST_ETC/shadow"
NM_PROFILES=()   # the host's active Wi-Fi and Ethernet profiles; on JetPack netplan keeps them in /run
while IFS= read -r line; do
  type=${line%%:*} f=${line#*:}
  [[ $type == 802-11-wireless || $type == 802-3-ethernet ]] || continue
  case $f in
    /etc/NetworkManager/system-connections/*) f=$HOST_ETC/NetworkManager/system-connections/${f##*/} ;;
    /run/NetworkManager/system-connections/*) f=$HOST_RUN/NetworkManager/system-connections/${f##*/} ;;
    *) continue ;;
  esac
  [[ -f $f ]] && NM_PROFILES+=("$f")
done < <(nmcli -t -g TYPE,FILENAME connection show --active 2>/dev/null)
((${#NM_PROFILES[@]})) || die "no active NetworkManager profile to copy; the drive would have no network"

if ((!write)); then
  identity
  not_in_use
  check_layout
  echo "target: $ROOT_DEV (RAYTONE_ROOT on $disk)"
  echo "rootfs: $(basename "$tarball") sha256 ok"
  echo "packages: ${PKG_FILES[*]##*/}"
  echo "network: ${NM_PROFILES[*]##*/}"
  echo "dry run: nothing written. Add --write --confirm-serial $serial."
  exit 0
fi
[[ $confirm == "$serial" ]] || die "--confirm-serial must repeat the disk serial before anything is written"
[[ $EUID -eq 0 || ${RAYTONE_SKIP_ROOT_CHECK:-} == 1 ]] || die "must run as root to write"
if [[ ${RAYTONE_IN_NS:-} != 1 && ${RAYTONE_NO_UNSHARE:-} != 1 ]]; then
  # PID 1 of new mount and PID namespaces: package hooks cannot see host processes, and leftovers die with it.
  exec unshare --mount --pid --fork --propagation private -- env RAYTONE_IN_NS=1 bash "$0" "${ORIG_ARGS[@]}"
fi

cleanup() { umount -R "$MNT" 2>/dev/null || true; restore_automount; }
trap cleanup EXIT
suppress_automount
identity
not_in_use
check_layout
mkdir -p "$MNT"
mount -t ext4 -o noatime "$ROOT_DEV" "$MNT"
root_partuuid=$(blkid -s PARTUUID -o value "$ROOT_DEV")
[[ -n $root_partuuid ]] || die "no PARTUUID for $ROOT_DEV"

# 1. Unpack the rootfs once, with the tools root's bsdtar; a marker records a complete unpack.
if [[ -f $MNT/etc/arch-release && ! -f $MNT/.raytone-unpacked ]]; then
  die "$ROOT_DEV holds a partial unpack (no .raytone-unpacked); reformat it with make-thor-usb.sh"
fi
if [[ ! -f $MNT/.raytone-unpacked ]]; then
  [[ -z $(find "$MNT" -mindepth 1 -maxdepth 1 ! -name lost+found -print -quit) ]] ||
    die "$ROOT_DEV is neither empty nor an Arch root; refusing to unpack over it"
  mkdir -p "$tools/mnt/raytone-target" "$tools/mnt/raytone-cache"
  mount --bind "$MNT" "$tools/mnt/raytone-target"
  mount --bind "$(dirname "$(readlink -f "$tarball")")" "$tools/mnt/raytone-cache"
  echo "+ unpacking $(basename "$tarball")"
  chroot "$tools" /usr/bin/env -i PATH=/usr/bin bsdtar -xpf "/mnt/raytone-cache/$(basename "$tarball")" -C /mnt/raytone-target
  umount "$tools/mnt/raytone-cache" "$tools/mnt/raytone-target"
  [[ -f $MNT/etc/arch-release ]] && echo "$(basename "$tarball") $tarball_sha" > "$MNT/.raytone-unpacked"
fi
[[ -f $MNT/etc/arch-release ]] || die "unpacking the rootfs failed"

# 2. A chroot of the drive (lib/thor-chroot.sh).
thor_chroot_mount

# 3. Packages. The mkinitcpio drop-in goes first so the kernel's install hook uses it.
mkdir -p "$MNT/etc/mkinitcpio.conf.d" "$MNT/etc/pacman.d"
cat > "$MNT/etc/mkinitcpio.conf.d/raytone-thor.conf" <<'EOF'
# RaytoneOS Thor: USB storage, xHCI and ext4 are built into the L4T kernel; the initramfs is a
# fallback (the GRUB entry boots without one). No autodetect (built in a chroot), no early KMS.
MODULES=(uas)
HOOKS=(base udev modconf block filesystems fsck)
EOF
printf 'Server = %s/$arch/$repo\n' "$MIRROR" > "$MNT/etc/pacman.d/mirrorlist"
in_target pacman-key --init
in_target pacman-key --populate archlinuxarm
in_target pacman -Sy --noconfirm archlinuxarm-keyring
if in_target pacman -Q linux-aarch64 > /dev/null 2>&1; then in_target pacman -Rdd --noconfirm linux-aarch64; fi
in_target pacman -Su --noconfirm
in_target pacman -S --noconfirm --needed "${BASE_PKGS[@]}"
mkdir -p "$MNT/var/cache/raytone"
cp -f "${PKG_FILES[@]}" "$MNT/var/cache/raytone/"
in_target pacman -U --noconfirm --needed "${PKG_FILES[@]/#*\///var/cache/raytone/}"
in_target gpgconf --homedir /etc/pacman.d/gnupg --kill all || true

# 4. System files.
echo "$HOSTNAME_" > "$MNT/etc/hostname"
printf '127.0.0.1 localhost\n::1 localhost\n127.0.1.1 %s.localdomain %s\n' "$HOSTNAME_" "$HOSTNAME_" > "$MNT/etc/hosts"
{
  echo "# RaytoneOS Thor USB drive"
  echo "PARTUUID=$root_partuuid / ext4 defaults,noatime 0 1"
  echo "# No UEFI variable writes from this system (systemd-remount-fs applies the options)."
  echo "efivarfs /sys/firmware/efi/efivars efivarfs ro,nosuid,nodev,noexec 0 0"
} > "$MNT/etc/fstab"
if [[ -L $HOST_ETC/localtime ]]; then ln -sfn "$(readlink "$HOST_ETC/localtime")" "$MNT/etc/localtime"
else cp -f "$HOST_ETC/localtime" "$MNT/etc/localtime"; fi
[[ -f $MNT/etc/locale.gen ]] && sed -i 's/^#en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' "$MNT/etc/locale.gen"
echo "LANG=en_US.UTF-8" > "$MNT/etc/locale.conf"
echo "KEYMAP=us" > "$MNT/etc/vconsole.conf"
in_target locale-gen
mkdir -p "$MNT/var/log/journal" "$MNT/var/lib/raytone"
[[ -f $MNT/etc/nsswitch.conf ]] &&
  sed -i '/^hosts:/{/mdns_minimal/!s/ resolve / mdns_minimal [NOTFOUND=return] resolve /}' "$MNT/etc/nsswitch.conf"

units=$MNT/etc/systemd/system
for svc in emergency rescue; do
  mkdir -p "$units/$svc.service.d"
  cat > "$units/$svc.service.d/raytone-reboot.conf" <<'EOF'
# RaytoneOS bring-up: nobody may be at the console, so reboot (back to the GRUB default) instead of
# waiting at a shell. Remove once the drive is trusted.
[Service]
ExecStartPre=
ExecStart=
ExecStart=/usr/bin/systemctl --no-block reboot
EOF
done
# Started from sysinit.target without the default dependencies, so it is armed even when later
# startup stalls; a confirmed boot creates /run/raytone-keep.
cat > "$units/raytone-deadman.timer" <<'EOF'
[Unit]
Description=RaytoneOS bring-up: reboot if nobody has confirmed this boot
DefaultDependencies=no

[Timer]
OnBootSec=20min

[Install]
WantedBy=sysinit.target
EOF
cat > "$units/raytone-deadman.service" <<'EOF'
[Unit]
Description=RaytoneOS bring-up: reboot unless /run/raytone-keep exists
DefaultDependencies=no
Conflicts=shutdown.target
Before=shutdown.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'test -e /run/raytone-keep || systemctl reboot'
EOF
# A normal reboot that stalls (a unit that will not stop) is forced after 5 minutes instead of 30.
mkdir -p "$units/reboot.target.d"
cat > "$units/reboot.target.d/raytone-bounded.conf" <<'EOF'
[Unit]
JobTimeoutSec=5min
JobTimeoutAction=reboot-force
EOF
cat > "$units/raytone-boot-start.service" <<'EOF'
[Unit]
Description=RaytoneOS bring-up: record that this boot reached a writable root
DefaultDependencies=no
After=systemd-remount-fs.service
Before=sysinit.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'mkdir -p /var/lib/raytone; echo "$(date -Is) start $(uname -r)" >> /var/lib/raytone/boots.log'

[Install]
WantedBy=sysinit.target
EOF
# Thermal guard: without a running fan controller, or at 95 C, go back to JetPack. Not ordered after
# the services it watches, so a start that hangs cannot hold it back.
mkdir -p "$MNT/usr/lib/raytone"
cp -f "$HERE/thor-rootfs/thermal-guard" "$MNT/usr/lib/raytone/thermal-guard"
chmod 0755 "$MNT/usr/lib/raytone/thermal-guard"
cat > "$units/raytone-thermal-guard.service" <<'EOF'
[Unit]
Description=RaytoneOS bring-up: reboot if fan control stops or the SoC runs hot

[Service]
ExecStart=/usr/lib/raytone/thermal-guard
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
cat > "$units/raytone-boot-marker.service" <<'EOF'
[Unit]
Description=RaytoneOS bring-up: record this boot in /var/lib/raytone/boots.log
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'mkdir -p /var/lib/raytone; echo "$(date -Is) $(uname -r) $(uname -v) $(cat /proc/cmdline)" >> /var/lib/raytone/boots.log'

[Install]
WantedBy=multi-user.target
EOF

# 5. Accounts, SSH and network from the JetPack host.
if in_target getent passwd alarm > /dev/null; then in_target userdel -r alarm; fi
if ! in_target getent passwd "$user" > /dev/null; then
  in_target useradd -m -u 1000 -G wheel,video,render,audio,input -s /bin/bash "$user"
fi
{ set +x; } 2>/dev/null
awk -F: -v u="$user" '$1 == u {print $1 ":" $2}' "$HOST_ETC/shadow" | in_target chpasswd -e
in_target passwd -l root
install -d -m 0750 "$MNT/etc/sudoers.d"
# Removed first, so a re-run never writes into the read-only files it left last time.
rm -f "$MNT/etc/sudoers.d/10-wheel" "$MNT/etc/sudoers.d/raytone-temp"
echo '%wheel ALL=(ALL:ALL) ALL' > "$MNT/etc/sudoers.d/10-wheel"
echo "$user ALL=(ALL) NOPASSWD: ALL  # RaytoneOS bring-up only; remove when done" > "$MNT/etc/sudoers.d/raytone-temp"
chmod 0440 "$MNT/etc/sudoers.d/10-wheel" "$MNT/etc/sudoers.d/raytone-temp"
install -d -m 0700 "$MNT/home/$user/.ssh"
install -m 0600 "$HOST_HOME/.ssh/authorized_keys" "$MNT/home/$user/.ssh/authorized_keys"
in_target chown -R "$user:$user" "/home/$user/.ssh"
install -d -m 0700 "$MNT/etc/NetworkManager/system-connections"
install -m 0600 "${NM_PROFILES[@]}" "$MNT/etc/NetworkManager/system-connections/"

# 6. Machine ID, services and SSH host keys.
in_target systemd-machine-id-setup
in_target systemctl enable "${UNITS[@]}"
MASKED=("${MASK_ALWAYS[@]}")
for f in "$MNT"/usr/lib/systemd/system/*; do
  [[ -d $f ]] && continue
  [[ ${f##*/} =~ $MASK_RE ]] && MASKED+=("${f##*/}")
done
in_target systemctl mask "${MASKED[@]}"
in_target ssh-keygen -A

# 7. Verify before reporting success.
[[ -f $MNT/boot/vmlinuz-raytone-thor-linux ]] || die "no /boot/vmlinuz-raytone-thor-linux on the drive"
[[ -f $MNT/usr/lib/modules/$KVER/modules.dep ]] || die "no modules index for $KVER"
in_target test -e /etc/nvpmodel.conf || die "/etc/nvpmodel.conf does not resolve on the drive"
in_target test -e /etc/nvfancontrol.conf || die "/etc/nvfancontrol.conf does not resolve on the drive"
for u in "${UNITS[@]}"; do   # one at a time: is-enabled succeeds if any one of several is enabled
  in_target systemctl is-enabled "$u" > /dev/null || die "unit not enabled: $u"
done
for u in "${MASKED[@]}"; do
  [[ $(readlink "$MNT/etc/systemd/system/$u") == /dev/null ]] || die "unit not masked: $u"
done
id=$(cat "$MNT/etc/machine-id" 2>/dev/null) || true
[[ $id =~ ^[0-9a-f]{32}$ && $id != 00000000000000000000000000000000 ]] || die "no valid machine ID on the drive"
[[ $id != "$(cat "$HOST_ETC/machine-id" 2>/dev/null)" ]] || die "the drive's machine ID is JetPack's"
in_target timeout -k 1 5 true || die "timeout -k does not work on the drive; the thermal guard needs it"
in_target visudo -cf /etc/sudoers.d/10-wheel > /dev/null || die "sudoers 10-wheel does not parse"
in_target visudo -cf /etc/sudoers.d/raytone-temp > /dev/null || die "sudoers raytone-temp does not parse"
in_target sshd -t || die "sshd configuration does not validate"
in_target pacman -Q > "$MNT/var/lib/raytone/installed-packages.txt"
ls -la "$MNT/boot" > "$MNT/var/lib/raytone/boot-listing.txt"
sync
echo "verified: kernel, modules index, board links, units, sudoers, sshd configuration"
echo "installed: Arch Linux ARM root on $ROOT_DEV (PARTUUID=$root_partuuid)"
