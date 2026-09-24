#!/bin/bash
# Partition and format the USB drive for the Thor port: GPT with a 512 MiB ESP (RAYTONE_ESP) and
# an ext4 root (RAYTONE_ROOT). A dry run unless --write and --confirm-serial SERIAL are both given.
#
#   make-thor-usb.sh --disk /dev/disk/by-id/usb-... --serial SERIAL [--write --confirm-serial SERIAL]
#
# Refuses anything that is not a whole USB disk with that serial and a plausible size, the disk that
# holds /, and disks with mounted partitions, active swap or holders (dm, LVM, RAID). The identity is
# checked again immediately before every destructive command. While writing, a runtime udev rule
# keeps desktop automounters away from the disk. Nothing else is touched: no boot entries, no
# internal disk. Tests: tests/test_make_thor_usb.py (RAYTONE_* variables exist for them).
set -euo pipefail

SYS=${RAYTONE_SYS:-/sys}
RULES=${RAYTONE_UDEV_RULES:-/run/udev/rules.d}
MIN_SIZE=$((8 * 1024 ** 3))
MAX_SIZE=$((2 * 1024 ** 4))
ESP_LABEL=RAYTONE_ESP
ROOT_LABEL=RAYTONE_ROOT

die() { echo "make-thor-usb: $*" >&2; exit 1; }

disk='' serial='' write=0 confirm=''
while (($#)); do
  case $1 in
    --disk) disk=${2:-}; shift 2 ;;
    --serial) serial=${2:-}; shift 2 ;;
    --write) write=1; shift ;;
    --confirm-serial) confirm=${2:-}; shift 2 ;;
    *) die "unknown argument $1" ;;
  esac
done
[[ -n $disk && -n $serial ]] ||
  die "usage: --disk /dev/disk/by-id/usb-... --serial SERIAL [--write --confirm-serial SERIAL]"
[[ $(basename "$disk") == usb-* && $(basename "$(dirname "$disk")") == by-id ]] ||
  die "--disk must be a /dev/disk/by-id/usb-* link, got $disk"
dev=$(readlink -f "$disk")
name=$(basename "$dev")
[[ $name =~ ^sd[a-z]+$ ]] || die "$disk resolves to $dev, not a whole USB disk node"

identity() { # abort unless $dev is still the expected whole USB disk
  local type tran ser size
  read -r type tran ser size < <(lsblk -dn -b -o TYPE,TRAN,SERIAL,SIZE "$dev")
  [[ $type == disk ]] || die "$dev is '$type', not a whole disk"
  [[ $tran == usb ]] || die "$dev is on '$tran', not a USB disk"
  [[ $ser == "$serial" ]] || die "$dev serial is '$ser', expected '$serial'"
  ((size >= MIN_SIZE && size <= MAX_SIZE)) || die "$dev size $size bytes is outside 8 GiB to 2 TiB"
}

not_in_use() {
  local rootsrc rootdisk h
  rootsrc=$(findmnt -n -o SOURCE /)
  rootdisk=$(lsblk -no PKNAME "$rootsrc" 2>/dev/null | head -1)
  [[ $rootdisk != "$name" && $rootsrc != "$dev" ]] || die "$dev holds /"
  [[ -z $(lsblk -n -o MOUNTPOINTS "$dev" | tr -d '[:space:]') ]] || die "$dev has mounted partitions"
  local sw
  for sw in $(swapon --show=NAME --noheadings); do
    [[ $(basename "$sw") =~ ^${name}[0-9]*$ ]] && die "$dev has active swap ($sw)"
  done
  for h in "$SYS/block/$name/holders"/* "$SYS/block/$name/$name"*/holders/*; do
    [[ -e $h ]] && die "$dev has holders ($(basename "$h"))"
  done
  return 0
}

run() { # run CMD... : destructive step, directly after a fresh identity check
  identity
  echo "+ $*"
  "$@"
}

rule=$RULES/90-raytone-noauto-$serial.rules
cleanup() { rm -f "$rule"; udevadm control --reload || true; }

identity
not_in_use
echo "target: $disk -> $dev, serial $serial"
echo "plan: GPT; 1: 512 MiB EF00 $ESP_LABEL (FAT32); 2: rest 8300 $ROOT_LABEL (ext4)"
if ((!write)); then
  echo "dry run: nothing written. Add --write --confirm-serial $serial to partition and format."
  exit 0
fi
[[ $confirm == "$serial" ]] || die "--confirm-serial must repeat the disk serial before anything is written"
[[ $EUID -eq 0 || ${RAYTONE_SKIP_ROOT_CHECK:-} == 1 ]] || die "must run as root to write"

trap cleanup EXIT
mkdir -p "$RULES"
echo "ENV{ID_SERIAL_SHORT}==\"$serial\", ENV{UDISKS_IGNORE}=\"1\", ENV{UDISKS_AUTO}=\"0\"" > "$rule"
echo "automount suppressed while writing: $(cat "$rule")"
udevadm control --reload

for p in "$dev"[0-9]*; do
  [[ -e $p ]] && run wipefs -a "$p"
done
run wipefs -a "$dev"
run sgdisk --zap-all "$dev"
run sgdisk -n 1:0:+512M -t 1:EF00 -c 1:$ESP_LABEL -n 2:0:0 -t 2:8300 -c 2:$ROOT_LABEL "$dev"
partprobe "$dev"
udevadm settle
labels=$(lsblk -n -o PARTLABEL "$dev" | xargs)
[[ $labels == "$ESP_LABEL $ROOT_LABEL" ]] || die "partition labels read back as '$labels'"
run mkfs.vfat -F 32 -n "$ESP_LABEL" "${dev}1"
run mkfs.ext4 -F -q -L "$ROOT_LABEL" "${dev}2"
udevadm settle
echo "$ESP_LABEL PARTUUID=$(blkid -s PARTUUID -o value "${dev}1")"
echo "$ROOT_LABEL PARTUUID=$(blkid -s PARTUUID -o value "${dev}2")"
