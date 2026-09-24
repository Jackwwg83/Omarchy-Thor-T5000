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
# and a boot marker records every boot in /var/lib/raytone/boots.log. NVIDIA's systemd watchdog
# setting (RuntimeWatchdogSec=120) comes with raytone-thor-core. Nothing that writes UEFI variables
# (efibootmgr, grub, fwupd) is installed. A dry run unless --write.
# Tests: tests/test_install_thor_root.py (RAYTONE_* variables exist for them).
set -euo pipefail

HERE=$(dirname "$(readlink -f "$0")")
ORIG_ARGS=("$@")
die() { echo "install-thor-root: $*" >&2; exit 1; }
# shellcheck source=lib/usb.sh
source "$HERE/lib/usb.sh"

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
for p in raytone-thor-firmware raytone-thor-linux raytone-thor-core; do
  f=$(compgen -G "$pkgdir/$p-[0-9]*.pkg.tar.*" | sort -V | tail -1) || true
  [[ -n $f ]] || die "package $p not found in '$pkgdir'"
  PKG_FILES+=("$f")
done

MNT=${RAYTONE_TARGET_MOUNT:-/mnt/raytone-target}
HOST_ETC=${RAYTONE_HOST_ETC:-/etc}
HOST_HOME=${RAYTONE_HOST_HOME:-/home/$user}
MIRROR=${PKG_MIRROR:-https://mirrors.tuna.tsinghua.edu.cn/archlinuxarm}
ROOT_DEV=${dev}2
HOSTNAME_=raytone-thor
BASE_PKGS=(networkmanager openssh sudo avahi nss-mdns linux-firmware-realtek wireless-regdb iw vim less htop)
UNITS=(sshd NetworkManager avahi-daemon systemd-timesyncd raytone-deadman.timer raytone-boot-marker
       nv-load-display-modules nvfancontrol nvpmodel nvpower)
DROP_CAPS=-sys_module,-sys_rawio,-sys_boot,-sys_time,-bpf,-perfmon,-mac_admin,-mac_override,-syslog,-wake_alarm

if ((!write)); then
  identity
  not_in_use
  check_layout
  echo "target: $ROOT_DEV (RAYTONE_ROOT on $disk)"
  echo "rootfs: $(basename "$tarball") sha256 ok"
  echo "packages: ${PKG_FILES[*]##*/}"
  echo "dry run: nothing written. Add --write --confirm-serial $serial."
  exit 0
fi
[[ $confirm == "$serial" ]] || die "--confirm-serial must repeat the disk serial before anything is written"
[[ $EUID -eq 0 || ${RAYTONE_SKIP_ROOT_CHECK:-} == 1 ]] || die "must run as root to write"
if [[ ${RAYTONE_IN_NS:-} != 1 && ${RAYTONE_NO_UNSHARE:-} != 1 ]]; then
  exec unshare --mount --propagation private -- env RAYTONE_IN_NS=1 bash "$0" "${ORIG_ARGS[@]}"
fi

trap restore_automount EXIT
suppress_automount
identity
not_in_use
check_layout
mkdir -p "$MNT"
mount -t ext4 -o noatime "$ROOT_DEV" "$MNT"
root_partuuid=$(blkid -s PARTUUID -o value "$ROOT_DEV")
[[ -n $root_partuuid ]] || die "no PARTUUID for $ROOT_DEV"

# 1. Unpack the rootfs once, with the tools root's bsdtar.
if [[ ! -f $MNT/etc/arch-release ]]; then
  [[ -z $(find "$MNT" -mindepth 1 -maxdepth 1 ! -name lost+found -print -quit) ]] ||
    die "$ROOT_DEV is neither empty nor an Arch root; refusing to unpack over it"
  mkdir -p "$tools/mnt/raytone-target" "$tools/mnt/raytone-cache"
  mount --bind "$MNT" "$tools/mnt/raytone-target"
  mount --bind "$(dirname "$(readlink -f "$tarball")")" "$tools/mnt/raytone-cache"
  echo "+ unpacking $(basename "$tarball")"
  chroot "$tools" /usr/bin/env -i PATH=/usr/bin bsdtar -xpf "/mnt/raytone-cache/$(basename "$tarball")" -C /mnt/raytone-target
  umount "$tools/mnt/raytone-cache" "$tools/mnt/raytone-target"
fi
[[ -f $MNT/etc/arch-release ]] || die "unpacking the rootfs failed"

# 2. A chroot of the drive: fresh proc, read-only sysfs without efivarfs, private /dev, own /run and /tmp.
bind_node() { touch "$2"; mount --bind "$1" "$2"; }
mkdir -p "$MNT"/{proc,sys,dev,run,tmp}
mount -t proc proc "$MNT/proc"
mount -t sysfs -o ro,nosuid,nodev,noexec sysfs "$MNT/sys"
mount -t tmpfs -o mode=0755,nosuid tmpfs "$MNT/dev"
for n in null zero full random urandom tty; do bind_node "/dev/$n" "$MNT/dev/$n"; done
mkdir -p "$MNT/dev/pts" "$MNT/dev/shm"
mount -t devpts -o newinstance,ptmxmode=0666 devpts "$MNT/dev/pts"
ln -sf pts/ptmx "$MNT/dev/ptmx"
ln -sf /proc/self/fd "$MNT/dev/fd"
ln -sf /proc/self/fd/0 "$MNT/dev/stdin"
ln -sf /proc/self/fd/1 "$MNT/dev/stdout"
ln -sf /proc/self/fd/2 "$MNT/dev/stderr"
mount -t tmpfs -o mode=0755 tmpfs "$MNT/run"
mount -t tmpfs -o mode=1777 tmpfs "$MNT/tmp"
rm -f "$MNT/etc/resolv.conf"
cat "$HOST_ETC/resolv.conf" > "$MNT/etc/resolv.conf" 2>/dev/null || true
in_target() {
  setpriv --no-new-privs --bounding-set "$DROP_CAPS" -- \
    chroot "$MNT" /usr/bin/env -i PATH=/usr/bin HOME=/root LANG=C.UTF-8 "$@"
}

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
printf '# RaytoneOS Thor USB drive\nPARTUUID=%s / ext4 defaults,noatime 0 1\n' "$root_partuuid" > "$MNT/etc/fstab"
ln -sfn "$(readlink "$HOST_ETC/localtime")" "$MNT/etc/localtime"
[[ -f $MNT/etc/locale.gen ]] && sed -i 's/^#en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' "$MNT/etc/locale.gen"
echo "LANG=en_US.UTF-8" > "$MNT/etc/locale.conf"
in_target locale-gen || true
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
cat > "$units/raytone-deadman.timer" <<'EOF'
[Unit]
Description=RaytoneOS bring-up: reboot if nobody has confirmed this boot

[Timer]
OnBootSec=20min

[Install]
WantedBy=timers.target
EOF
cat > "$units/raytone-deadman.service" <<'EOF'
[Unit]
Description=RaytoneOS bring-up: reboot unless /run/raytone-keep exists

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'test -e /run/raytone-keep || systemctl reboot'
EOF
cat > "$units/raytone-boot-marker.service" <<'EOF'
[Unit]
Description=RaytoneOS bring-up: record this boot in /var/lib/raytone/boots.log
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'mkdir -p /var/lib/raytone; echo "$(date -Is) $(uname -r) $(cat /proc/cmdline)" >> /var/lib/raytone/boots.log'

[Install]
WantedBy=multi-user.target
EOF

# 5. Accounts, SSH and network from the JetPack host.
if in_target getent passwd alarm > /dev/null; then in_target userdel -r alarm; fi
if ! in_target getent passwd "$user" > /dev/null; then
  in_target useradd -m -u 1000 -G wheel,video,render,audio,input -s /bin/bash "$user"
fi
hash=$(awk -F: -v u="$user" '$1 == u {print $2}' "$HOST_ETC/shadow")
[[ $hash == \$* ]] || die "no password hash for $user on the host"
printf '%s:%s\n' "$user" "$hash" | in_target chpasswd -e
unset hash
in_target passwd -l root
install -d -m 0750 "$MNT/etc/sudoers.d"
echo '%wheel ALL=(ALL:ALL) ALL' > "$MNT/etc/sudoers.d/10-wheel"
echo "$user ALL=(ALL) NOPASSWD: ALL  # RaytoneOS bring-up only; remove when done" > "$MNT/etc/sudoers.d/raytone-temp"
chmod 0440 "$MNT/etc/sudoers.d/10-wheel" "$MNT/etc/sudoers.d/raytone-temp"
install -d -m 0700 "$MNT/home/$user/.ssh"
install -m 0600 "$HOST_HOME/.ssh/authorized_keys" "$MNT/home/$user/.ssh/authorized_keys"
in_target chown -R "$user:$user" "/home/$user/.ssh"
install -d -m 0700 "$MNT/etc/NetworkManager/system-connections"
for c in "$HOST_ETC"/NetworkManager/system-connections/*.nmconnection; do
  [[ -e $c ]] && install -m 0600 "$c" "$MNT/etc/NetworkManager/system-connections/"
done

# 6. Services, then a record of what was installed.
in_target systemctl enable "${UNITS[@]}"
in_target pacman -Q > "$MNT/var/lib/raytone/installed-packages.txt" || true
ls -la "$MNT/boot" > "$MNT/var/lib/raytone/boot-listing.txt" 2>&1 || true
sync
echo "installed: Arch Linux ARM root on $ROOT_DEV (PARTUUID=$root_partuuid)"
