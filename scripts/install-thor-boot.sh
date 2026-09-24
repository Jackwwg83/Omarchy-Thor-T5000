#!/bin/bash
# Stage GRUB and the RaytoneOS boot menu on the Thor USB drive's ESP, make the drive bootable, or
# arm a one-shot entry.
#
#   install-thor-boot.sh install  --entries ENTRIES.json --default ID ...   stage GRUB, drive stays unbootable
#   install-thor-boot.sh publish  ...                                        check the ESP, make it bootable
#   install-thor-boot.sh arm-once --entry ID ...                             next boot from USB runs ID once
#   common: --disk /dev/disk/by-id/usb-... --serial S --tools-root DIR [--write --confirm-serial S]
#
# The drive is laid out by make-thor-usb.sh. grub-install runs in the tools root (an Arch Linux ARM
# root with the grub package) inside a private mount namespace whose sysfs is read-only and has no
# efivarfs, with --removable --no-nvram: no UEFI variable can be written. Only the drive's ESP is
# mounted read-write. `install` has grub-install write its removable loader into a staging directory
# the firmware never looks at and keeps it as BOOTAA64.EFI.staged, so the drive is not bootable at any
# point of an install, even an interrupted one; `publish` (taken with someone present, since a bad boot cannot be
# recovered remotely) checks grub.cfg with grub-script-check, the environment block and the modules
# the menu uses, then renames it. The menu comes from thor_boot.py. A dry run unless --write.
# Tests: tests/test_install_thor_boot.py (RAYTONE_* variables exist for them).
set -euo pipefail

HERE=$(dirname "$(readlink -f "$0")")
ORIG_ARGS=("$@")
die() { echo "install-thor-boot: $*" >&2; exit 1; }
# shellcheck source=lib/usb.sh
source "$HERE/lib/usb.sh"

cmd=${1:-}
shift || true
disk='' serial='' write=0 confirm='' entries='' entry='' tools='' dev='' default=''
while (($#)); do
  case $1 in
    --disk) disk=${2:-}; shift 2 ;;
    --serial) serial=${2:-}; shift 2 ;;
    --write) write=1; shift ;;
    --confirm-serial) confirm=${2:-}; shift 2 ;;
    --entries) entries=${2:-}; shift 2 ;;
    --entry) entry=${2:-}; shift 2 ;;
    --default) default=${2:-}; shift 2 ;;
    --tools-root) tools=${2:-}; shift 2 ;;
    *) die "unknown argument $1" ;;
  esac
done
case $cmd in
  install) [[ -f $entries && -n $default ]] || die "install needs --entries FILE and --default ID" ;;
  publish) ;;
  arm-once) [[ $entry =~ ^[a-z0-9-]+$ ]] || die "arm-once needs --entry ID" ;;
  *) die "usage: install-thor-boot.sh install|publish|arm-once ... (see the header)" ;;
esac
resolve_usb_disk
[[ -e $tools/usr/bin/grub-install ]] || die "tools root '$tools' has no grub-install"

BOOT=/mnt/raytone-esp                       # the ESP, as seen inside the tools root
ESP_MNT=${RAYTONE_ESP_MOUNT:-$tools$BOOT}   # the same mount, from the host
ESP_DEV=${dev}1
LOADER=EFI/BOOT/BOOTAA64.EFI
STAGING=raytone-staging                     # grub-install's --efi-directory, below the ESP root
# Modules the generated menu needs beyond GRUB's core image.
MODULES=(normal part_gpt fat ext2 search_fs_uuid chain linux loadenv reboot sleep echo test)

if [[ $cmd == install ]]; then
  menu=$(python3 "$HERE/thor_boot.py" grub-cfg --entries "$entries" --default "$default") ||
    die "cannot render grub.cfg from $entries"
fi
if ((!write)); then
  identity
  not_in_use
  check_layout
  echo "target: $disk -> $dev ($ESP_DEV is the ESP)"
  [[ $cmd == install ]] && printf '%s\n' "$menu"
  [[ $cmd == arm-once ]] && echo "would set next_entry=$entry"
  [[ $cmd == publish ]] && echo "would check the ESP and rename $LOADER.staged to $LOADER"
  echo "dry run: nothing written. Add --write --confirm-serial $serial."
  exit 0
fi
[[ $confirm == "$serial" ]] || die "--confirm-serial must repeat the disk serial before anything is written"
[[ $EUID -eq 0 || ${RAYTONE_SKIP_ROOT_CHECK:-} == 1 ]] || die "must run as root to write"

# Everything below runs in a private mount namespace; its mounts vanish with it.
if [[ ${RAYTONE_IN_NS:-} != 1 && ${RAYTONE_NO_UNSHARE:-} != 1 ]]; then
  exec unshare --mount --propagation private -- env RAYTONE_IN_NS=1 bash "$0" "${ORIG_ARGS[@]}"
fi

trap restore_automount EXIT
suppress_automount
identity
not_in_use
check_layout

bind_node() { touch "$2"; mount --bind "$1" "$2"; }
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
size_of() { stat -c %s "$1" 2>/dev/null || stat -f %z "$1"; }

case $cmd in
  install)
    # A drive published earlier stops being bootable before anything else changes.
    if [[ -e $ESP_MNT/$LOADER ]]; then
      mkdir -p "$ESP_MNT/EFI/BOOT" && mv -f "$ESP_MNT/$LOADER" "$ESP_MNT/$LOADER.staged" && sync
      echo "unpublished: $LOADER moved to $LOADER.staged"
    fi
    echo "+ grub-install into $ESP_DEV/$STAGING (the firmware does not look there)"
    rm -rf "${ESP_MNT:?}/$STAGING" && mkdir -p "$ESP_MNT/$STAGING"
    in_tools grub-install --target=arm64-efi "--efi-directory=$BOOT/$STAGING" "--boot-directory=$BOOT/boot" \
      --removable --no-nvram || die "grub-install failed; the drive is still not bootable"
    [[ -f $ESP_MNT/$STAGING/$LOADER ]] || die "$STAGING/$LOADER missing after grub-install"
    mkdir -p "$ESP_MNT/EFI/BOOT"
    mv -f "$ESP_MNT/$STAGING/$LOADER" "$ESP_MNT/$LOADER.staged"
    rm -rf "${ESP_MNT:?}/$STAGING"
    mkdir -p "$ESP_MNT/boot/grub"
    printf '%s\n' "$menu" > "$ESP_MNT/boot/grub/grub.cfg"
    in_tools grub-editenv "$BOOT/boot/grub/grubenv" create
    [[ $(size_of "$ESP_MNT/boot/grub/grubenv") == 1024 ]] || die "grubenv is not a 1024-byte environment block"
    [[ ! -e $ESP_MNT/$LOADER ]] || die "$LOADER exists after install; the drive must stay unbootable"
    sync
    echo "staged: $LOADER.staged, boot/grub/grub.cfg, boot/grub/grubenv. The drive is not bootable until 'publish'."
    ;;
  publish)
    [[ -f $ESP_MNT/$LOADER.staged ]] || die "nothing staged: $LOADER.staged is missing (run install)"
    in_tools grub-script-check "$BOOT/boot/grub/grub.cfg" || die "grub-script-check rejects boot/grub/grub.cfg"
    [[ $(size_of "$ESP_MNT/boot/grub/grubenv") == 1024 ]] || die "grubenv is not a 1024-byte environment block"
    for m in "${MODULES[@]}"; do
      [[ -f $ESP_MNT/boot/grub/arm64-efi/$m.mod ]] || die "GRUB module $m.mod is missing"
    done
    mv -f "$ESP_MNT/$LOADER.staged" "$ESP_MNT/$LOADER"
    sync
    echo "published: $LOADER. The firmware boots this drive first (BootOrder) and GRUB's default applies."
    ;;
  arm-once)
    grep -q -- "--id $entry {" "$ESP_MNT/boot/grub/grub.cfg" || die "entry '$entry' is not in grub.cfg"
    in_tools grub-editenv "$BOOT/boot/grub/grubenv" set "next_entry=$entry"
    in_tools grub-editenv "$BOOT/boot/grub/grubenv" list | grep -qx "next_entry=$entry" ||
      die "next_entry did not read back"
    sync
    echo "armed: the next boot from the USB drive runs '$entry' once, then the default again"
    ;;
esac
