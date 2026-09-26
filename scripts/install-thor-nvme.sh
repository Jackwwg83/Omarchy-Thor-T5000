#!/bin/bash
# Install the USB drive's Omarchy onto the Thor's NVMe next to JetPack (Slice 4).
#
#   install-thor-nvme.sh STEP --nvme /dev/disk/by-id/nvme-... --serial S --backup-dir DIR \
#       [--write --confirm-serial S]
#
#   backup       NVMe partition table (sfdisk --dump), JetPack's APP as a tar, extlinux.conf, into DIR
#   shrink-app   e2fsck, resize2fs APP to 950 GiB, then the table from thor_nvme.py split (APP keeps
#                start, PARTUUID, type, name; RAYTONE_OMARCHY takes the rest), then e2fsck again
#   create-root  mkfs.ext4 on RAYTONE_OMARCHY (refused when it already holds a filesystem)
#   clone        the running root (the USB drive's Omarchy) into RAYTONE_OMARCHY, fstab moved to it
#   boot-entry   the kernel to APP's /boot/raytone-thor/, extlinux.conf.jetpack kept, and the omarchy
#                L4TLauncher entry added and made the default (thor_nvme.py extlinux)
#
# Runs as root on the Thor booted from the USB drive: the running root must not be on the NVMe, and
# no NVMe partition may be mounted. Every step checks the NVMe's identity (serial, size) and that
# its table is the recorded one, original or split as the step needs (manifests/, thor_nvme.py).
# Nothing touches the ESP, UEFI variables, QSPI or TPM. A dry run unless --write.
# Tests: tests/test_install_thor_nvme.py (RAYTONE_* variables exist for them).
set -euo pipefail

HERE=$(dirname "$(readlink -f "$0")")
die() { echo "install-thor-nvme: $*" >&2; exit 1; }
NVME_SIZE=2048408248320  # bytes, XG7000-2TB as recorded 2026-09-26
APP_GIB=950
APP_PARTUUID=1b3479b0-b4c2-4a1b-8b81-86d864b3944e
KERNEL_SRC=${RAYTONE_KERNEL_SRC:-/boot/vmlinuz-raytone-thor-linux}
KERNEL_DST=/boot/raytone-thor/Image
MNT=${RAYTONE_NVME_MOUNT:-/mnt/raytone-nvme}
SRC_ROOT=${RAYTONE_SOURCE_ROOT:-/}
PY=${RAYTONE_PYTHON:-python3}
planner() { "$PY" "$HERE/thor_nvme.py" "$@"; }

step=${1:-}; shift || true
nvme='' serial='' write=0 confirm='' backup=''
while (($#)); do
  case $1 in
    --nvme) nvme=${2:-}; shift 2 ;;
    --serial) serial=${2:-}; shift 2 ;;
    --backup-dir) backup=${2:-}; shift 2 ;;
    --write) write=1; shift ;;
    --confirm-serial) confirm=${2:-}; shift 2 ;;
    *) die "unknown argument $1" ;;
  esac
done
case $step in backup|shrink-app|create-root|clone|boot-entry) ;; *) die "usage: install-thor-nvme.sh backup|shrink-app|create-root|clone|boot-entry ... (see the header)" ;; esac
[[ -n $nvme && -n $serial && -n $backup ]] || die "--nvme, --serial and --backup-dir are required"
[[ $(basename "$nvme") == nvme-* && $(basename "$(dirname "$nvme")") == by-id ]] || die "--nvme must be a /dev/disk/by-id/nvme-* link"
dev=$(readlink -f "$nvme")
[[ $(basename "$dev") =~ ^nvme[0-9]+n1$ ]] || die "$nvme resolves to $dev, not an NVMe namespace"
p() { echo "${dev}p$1"; }

identity() {
  local type tran ser size
  read -r type tran ser size < <(lsblk -dn -b -o TYPE,TRAN,SERIAL,SIZE "$dev")
  [[ $type == disk && $tran == nvme ]] || die "$dev is $type on $tran, not an NVMe disk"
  [[ $ser == "$serial" ]] || die "$dev serial is '$ser', expected '$serial'"
  [[ $size == "$NVME_SIZE" ]] || die "$dev is $size bytes, recorded $NVME_SIZE"
}
not_in_use() {
  local rootsrc
  rootsrc=$(findmnt -n -o SOURCE /)
  [[ $rootsrc != "$dev"* ]] || die "the running root ($rootsrc) is on the NVMe; boot from the USB drive"
  [[ -z $(lsblk -n -o MOUNTPOINTS "$dev" | tr -d '[:space:]') ]] || die "an NVMe partition is mounted"
}
# state: the table as recorded (original) or split for Omarchy; anything else stops everything
state() {
  sfdisk --dump "$dev" > "$work/current.sfdisk"
  planner check --dump "$work/current.sfdisk" || die "the NVMe's partition table is not the recorded one"
}
need_state() { local s; s=$(state) || exit 1; [[ $s == "$1" ]] || die "$step needs the $1 table, the NVMe has the $s one"; }
backup_ok() {
  [[ -f $backup/nvme-gpt.sfdisk && -f $backup/jetpack-app.tar.gz.sha256 && -f $backup/extlinux.conf ]] ||
    die "no complete backup in $backup (run backup first)"
}
omarchy_uuid() {
  [[ -f $backup/omarchy-partuuid ]] || die "no $backup/omarchy-partuuid (shrink-app writes it)"
  tr 'A-Z' 'a-z' < "$backup/omarchy-partuuid"
}
run() { if ((write)); then echo "+ $*"; "$@"; else echo "would run: $*"; fi; }

work=$(mktemp -d)
trap 'umount "$MNT" 2>/dev/null || true; rm -rf "$work"' EXIT
identity
not_in_use
if ((write)); then
  [[ $confirm == "$serial" ]] || die "--confirm-serial must repeat the NVMe serial before anything is written"
  [[ $EUID -eq 0 || ${RAYTONE_SKIP_ROOT_CHECK:-} == 1 ]] || die "must run as root to write"
fi
case $(readlink -f "$backup") in "$dev"*|/mnt/raytone-nvme*) die "the backup must not be on the NVMe" ;; esac
mkdir -p "$MNT"

case $step in
  backup)
    need_state original
    if ((write)); then
      install -d -m 0700 "$backup"
      cp "$work/current.sfdisk" "$backup/nvme-gpt.sfdisk"
      mount -o ro,noload "$(p 1)" "$MNT"
      cp "$MNT/boot/extlinux/extlinux.conf" "$backup/extlinux.conf"
      (cd "$MNT" && tar --numeric-owner --xattrs --acls -czpf "$backup/jetpack-app.tar.gz" .) ||
        echo "tar reported errors (sockets are skipped); see the check below" >&2
      umount "$MNT"
      gzip -t "$backup/jetpack-app.tar.gz" || die "the APP backup does not read back"
      (cd "$backup" && sha256sum jetpack-app.tar.gz > jetpack-app.tar.gz.sha256)
      echo "backed up: $backup (partition table, APP, extlinux.conf)"
    else
      echo "would back up the partition table, APP (read-only mount) and extlinux.conf into $backup"
    fi
    ;;
  shrink-app)
    need_state original
    backup_ok
    cmp -s "$work/current.sfdisk" "$backup/nvme-gpt.sfdisk" || die "the table changed since the backup"
    used=$(( $(dumpe2fs -h "$(p 1)" 2>/dev/null | awk -F: '/^Block count/{b=$2} /^Free blocks/{f=$2} END{print b-f}') * 4096 ))
    [[ -f $backup/omarchy-partuuid ]] || { ((write)) && uuidgen | tr 'a-z' 'A-Z' > "$backup/omarchy-partuuid"; }
    uuid=$( [[ -f $backup/omarchy-partuuid ]] && cat "$backup/omarchy-partuuid" || echo 00000000-0000-4000-8000-000000000000)
    planner split --dump "$work/current.sfdisk" --app-gib "$APP_GIB" --uuid "$uuid" --app-used-bytes "$used" > "$work/split.sfdisk" ||
      die "no valid split"
    blocks=$(planner app-blocks --dump "$work/split.sfdisk")
    run e2fsck -f -p "$(p 1)"
    run resize2fs "$(p 1)" "$blocks"
    run sfdisk --no-reread --no-tell-kernel "$dev" < "$work/split.sfdisk"
    if ((write)); then
      partx -u "$dev" || true
      [[ $(state || true) == split ]] || die "the table did not come out split; restore: sfdisk $dev < $backup/nvme-gpt.sfdisk"
      e2fsck -f -n "$(p 1)" || die "APP does not check clean after the shrink"
      echo "APP: $APP_GIB GiB, PARTUUID $APP_PARTUUID; RAYTONE_OMARCHY: PARTUUID $uuid"
    fi
    ;;
  create-root)
    need_state split
    if [[ -n $(blkid -o value -s TYPE "$(p 12)" 2>/dev/null) ]]; then
      die "$(p 12) already holds a filesystem; not reformatting it"
    fi
    run mkfs.ext4 -q -L RAYTONE_OMARCHY "$(p 12)"
    ;;
  clone)
    need_state split
    uuid=$(omarchy_uuid)
    [[ $(blkid -o value -s TYPE "$(p 12)" 2>/dev/null) == ext4 ]] || die "$(p 12) has no ext4 (run create-root)"
    if ((write)); then
      mount -o noatime "$(p 12)" "$MNT"
      [[ -z $(ls -A "$MNT" | grep -vx lost+found) || -f $MNT/.raytone-cloned ]] || die "$(p 12) holds something else"
      rsync -aHAXS --numeric-ids --delete --one-file-system \
        --exclude=/proc/* --exclude=/sys/* --exclude=/dev/* --exclude=/run/* --exclude=/tmp/* --exclude=/mnt/* \
        --exclude=/var/lib/raytone/nvme-backup/ --exclude=/home/*/cudatest/ --exclude=/home/*/ollamatest/ \
        --exclude=/home/*/nftspike/ --exclude=/home/*/nctktest/ --exclude=/.raytone-cloned \
        "$SRC_ROOT/" "$MNT/"
      planner fstab --in "$MNT/etc/fstab" --root-partuuid "$uuid" > "$work/fstab"
      install -m 0644 "$work/fstab" "$MNT/etc/fstab"
      install -d "$MNT/etc/raytone"
      printf 'APP_PARTUUID=%s\nKERNEL=%s\n' "$APP_PARTUUID" "$KERNEL_DST" > "$MNT/etc/raytone/nvme-boot.conf"
      date -u +%FT%TZ > "$MNT/.raytone-cloned"
      sync
      umount "$MNT"
      echo "cloned: $SRC_ROOT into $(p 12) (PARTUUID $uuid), fstab moved"
    else
      echo "would copy $SRC_ROOT into $(p 12) (PARTUUID $uuid) and move its fstab root there"
    fi
    ;;
  boot-entry)
    need_state split
    uuid=$(omarchy_uuid)
    [[ -f $KERNEL_SRC ]] || die "no kernel at $KERNEL_SRC"
    if ((write)); then
      mount -o noatime "$(p 1)" "$MNT"
      for d in boot boot/extlinux boot/extlinux/extlinux.conf boot/raytone-thor; do
        [[ ! -L $MNT/$d ]] || die "/$d on APP is a link"
      done
      planner extlinux --in "$MNT/boot/extlinux/extlinux.conf" --root-partuuid "$uuid" --kernel "$KERNEL_DST" \
        > "$work/extlinux.conf" || die "APP's extlinux.conf is not the recorded one; nothing changed"
      [[ -e $MNT/boot/extlinux/extlinux.conf.jetpack ]] || cp -p "$MNT/boot/extlinux/extlinux.conf" "$MNT/boot/extlinux/extlinux.conf.jetpack"
      cmp -s "$MNT/boot/extlinux/extlinux.conf.jetpack" "$backup/extlinux.conf" || die "extlinux.conf.jetpack is not the backed-up file"
      mkdir -p "$(dirname "$MNT$KERNEL_DST")"
      install -m 0644 "$KERNEL_SRC" "$MNT$KERNEL_DST"
      install -m 0644 "$work/extlinux.conf" "$MNT/boot/extlinux/extlinux.conf"
      sync
      umount "$MNT"
      echo "L4TLauncher: omarchy (default, root PARTUUID $uuid) and JetPack's primary; original in extlinux.conf.jetpack"
    else
      echo "would copy $KERNEL_SRC to APP $KERNEL_DST and add the omarchy entry (default) to APP's extlinux.conf"
    fi
    ;;
esac
