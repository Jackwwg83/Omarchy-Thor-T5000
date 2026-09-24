#!/bin/bash
# Install GRUB and the RaytoneOS boot menu on the Thor USB drive's ESP, or arm a one-shot entry.
#
#   install-thor-boot.sh install  --entries ENTRIES.json --disk DISK --serial S --tools-root DIR [--write --confirm-serial S]
#   install-thor-boot.sh arm-once --entry ID             --disk DISK --serial S --tools-root DIR [--write --confirm-serial S]
#
# DISK is the drive's /dev/disk/by-id/usb-* link, laid out by make-thor-usb.sh. grub-install runs in
# the tools root (an Arch Linux ARM root with the grub package) inside a private mount namespace whose
# sysfs is read-only and has no efivarfs, with --removable --no-nvram: no UEFI variable can be
# written. Only the drive's ESP is mounted read-write. The menu comes from thor_boot.py: its default
# hands back to the firmware, and arm-once makes one entry boot once. A dry run unless --write.
# Tests: tests/test_install_thor_boot.py (RAYTONE_* variables exist for them).
set -euo pipefail

HERE=$(dirname "$(readlink -f "$0")")
ORIG_ARGS=("$@")
die() { echo "install-thor-boot: $*" >&2; exit 1; }
# shellcheck source=lib/usb.sh
source "$HERE/lib/usb.sh"

cmd=${1:-}
shift || true
disk='' serial='' write=0 confirm='' entries='' entry='' tools='' dev='' name=''
while (($#)); do
  case $1 in
    --disk) disk=${2:-}; shift 2 ;;
    --serial) serial=${2:-}; shift 2 ;;
    --write) write=1; shift ;;
    --confirm-serial) confirm=${2:-}; shift 2 ;;
    --entries) entries=${2:-}; shift 2 ;;
    --entry) entry=${2:-}; shift 2 ;;
    --tools-root) tools=${2:-}; shift 2 ;;
    *) die "unknown argument $1" ;;
  esac
done
case $cmd in
  install) [[ -f $entries ]] || die "install needs --entries FILE" ;;
  arm-once) [[ $entry =~ ^[a-z0-9-]+$ ]] || die "arm-once needs --entry ID" ;;
  *) die "usage: install-thor-boot.sh install|arm-once ... (see the header)" ;;
esac
resolve_usb_disk
[[ -e $tools/usr/bin/grub-install ]] || die "tools root '$tools' has no grub-install"

BOOT=/mnt/raytone-esp                       # the ESP, as seen inside the tools root
ESP_MNT=${RAYTONE_ESP_MOUNT:-$tools$BOOT}   # the same mount, from the host
ESP_DEV=${dev}1

check_layout() {
  local layout
  layout=$(lsblk -ln -o NAME,PARTLABEL,FSTYPE "$dev")
  grep -qx "${name}1 RAYTONE_ESP vfat" <<< "$layout" || die "$dev partition 1 is not a FAT RAYTONE_ESP (run make-thor-usb.sh)"
  grep -qx "${name}2 RAYTONE_ROOT ext4" <<< "$layout" || die "$dev partition 2 is not an ext4 RAYTONE_ROOT"
}

identity
not_in_use
check_layout
if [[ $cmd == install ]]; then
  menu=$(python3 "$HERE/thor_boot.py" grub-cfg --entries "$entries") || die "cannot render grub.cfg from $entries"
fi
if ((!write)); then
  echo "target: $disk -> $dev ($ESP_DEV is the ESP)"
  [[ $cmd == install ]] && printf '%s\n' "$menu"
  [[ $cmd == arm-once ]] && echo "would set next_entry=$entry"
  echo "dry run: nothing written. Add --write --confirm-serial $serial."
  exit 0
fi
[[ $confirm == "$serial" ]] || die "--confirm-serial must repeat the disk serial before anything is written"
[[ $EUID -eq 0 || ${RAYTONE_SKIP_ROOT_CHECK:-} == 1 ]] || die "must run as root to write"

# Everything below runs in a private mount namespace; its mounts vanish with it.
if [[ ${RAYTONE_IN_NS:-} != 1 && ${RAYTONE_NO_UNSHARE:-} != 1 ]]; then
  exec unshare --mount --propagation private -- env RAYTONE_IN_NS=1 bash "$0" "${ORIG_ARGS[@]}"
fi

bind_node() { touch "$2"; mount --bind "$1" "$2"; }
identity
mkdir -p "$ESP_MNT" "$tools/proc" "$tools/sys" "$tools/dev"
mount -t vfat -o rw,nosuid,nodev,noexec,umask=0022 "$ESP_DEV" "$ESP_MNT"
mount -t proc proc "$tools/proc"
mount -t sysfs -o ro,nosuid,nodev,noexec sysfs "$tools/sys"
mount -t tmpfs -o mode=0755 tmpfs "$tools/dev"
for n in null zero urandom "$dev" "$ESP_DEV"; do
  [[ $n == /* ]] || n=/dev/$n
  bind_node "$n" "$tools/dev/$(basename "$n")"
done
in_tools() { chroot "$tools" /usr/bin/env -i PATH=/usr/bin LANG=C.UTF-8 "$@"; }

if [[ $cmd == install ]]; then
  echo "+ grub-install into $ESP_DEV"
  in_tools grub-install --target=arm64-efi "--efi-directory=$BOOT" "--boot-directory=$BOOT/boot" --removable --no-nvram
  mkdir -p "$ESP_MNT/boot/grub"
  printf '%s\n' "$menu" > "$ESP_MNT/boot/grub/grub.cfg"
  in_tools grub-editenv "$BOOT/boot/grub/grubenv" create
  [[ -f $ESP_MNT/EFI/BOOT/BOOTAA64.EFI ]] || die "EFI/BOOT/BOOTAA64.EFI missing after grub-install"
  compgen -G "$ESP_MNT/boot/grub/arm64-efi/*.mod" > /dev/null || die "GRUB modules missing after grub-install"
  [[ $(stat -c %s "$ESP_MNT/boot/grub/grubenv" 2>/dev/null || stat -f %z "$ESP_MNT/boot/grub/grubenv") == 1024 ]] ||
    die "grubenv is not a 1024-byte environment block"
  echo "installed: EFI/BOOT/BOOTAA64.EFI, boot/grub/grub.cfg, boot/grub/grubenv (no next_entry)"
else
  grep -q -- "--id $entry {" "$ESP_MNT/boot/grub/grub.cfg" || die "entry '$entry' is not in grub.cfg"
  in_tools grub-editenv "$BOOT/boot/grub/grubenv" set "next_entry=$entry"
  in_tools grub-editenv "$BOOT/boot/grub/grubenv" list | grep -qx "next_entry=$entry" ||
    die "next_entry did not read back"
  echo "armed: the next boot from the USB drive runs '$entry' once, then the default again"
fi
