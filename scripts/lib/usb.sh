# Shared USB target checks for the Thor drive tools (make-thor-usb.sh, install-thor-boot.sh).
# Callers set $disk and $serial and define die(); resolve_usb_disk sets $dev and $name.
# shellcheck shell=bash

SYS=${RAYTONE_SYS:-/sys}
MIN_SIZE=$((8 * 1024 ** 3))
MAX_SIZE=$((2 * 1024 ** 4))

resolve_usb_disk() {
  [[ -n $disk && -n $serial ]] ||
    die "usage: --disk /dev/disk/by-id/usb-... --serial SERIAL [--write --confirm-serial SERIAL]"
  [[ $(basename "$disk") == usb-* && $(basename "$(dirname "$disk")") == by-id ]] ||
    die "--disk must be a /dev/disk/by-id/usb-* link, got $disk"
  dev=$(readlink -f "$disk")
  name=$(basename "$dev")
  [[ $name =~ ^sd[a-z]+$ ]] || die "$disk resolves to $dev, not a whole USB disk node"
}

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


RULES=${RAYTONE_UDEV_RULES:-/run/udev/rules.d}
automount_rule=''

suppress_automount() { # keep desktop automounters off the target while the tools work on it
  automount_rule=$RULES/90-raytone-noauto-$serial.rules
  mkdir -p "$RULES"
  echo "ENV{ID_SERIAL_SHORT}==\"$serial\", ENV{UDISKS_IGNORE}=\"1\", ENV{UDISKS_AUTO}=\"0\"" > "$automount_rule"
  echo "automount suppressed: $(cat "$automount_rule")"
  udevadm control --reload
  udevadm trigger --action=change "$dev" || true   # apply the rule to the device already present
  udevadm settle || true
}

restore_automount() {
  [[ -n $automount_rule ]] && rm -f "$automount_rule"
  udevadm control --reload || true
}
