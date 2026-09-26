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
#   boot-entry   the kernel and an initramfs with the PCIe and NVMe modules to APP's /boot/raytone-thor/,
#                extlinux.conf.jetpack kept, and the omarchy L4TLauncher entry added and made the
#                default (thor_nvme.py extlinux), each file written in full and renamed into place
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
INITRD_SRC=${RAYTONE_INITRD_SRC:-/boot/initramfs-raytone-thor-linux.img}
INITRD_DST=/boot/raytone-thor/initrd
SYS=${RAYTONE_SYS:-/sys}
SERVICES=(ollama docker containerd)
MNT=${RAYTONE_NVME_MOUNT:-/mnt/raytone-nvme}
ROOT_MNT=${RAYTONE_ROOT_MOUNT:-/mnt/raytone-omarchy}
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
  [[ -f $backup/backup-complete && -f $backup/nvme-gpt.sfdisk && -f $backup/jetpack-app.tar.gz &&
     -f $backup/jetpack-app.tar.gz.sha256 && -f $backup/extlinux.conf ]] || die "no complete backup in $backup (run backup first)"
  (cd "$backup" && sha256sum -c --quiet jetpack-app.tar.gz.sha256) || die "the APP archive in $backup does not match its sha256"
}
# the kernel's view of a partition must be what the table says (partx refreshed it)
kernel_sees() {
  local n=$1 start=$2 size=$3 b
  b=$SYS/class/block/$(basename "$(p "$n")")
  [[ $(cat "$b/start" 2>/dev/null) == "$start" && $(cat "$b/size" 2>/dev/null) == "$size" ]] ||
    die "the kernel does not see $(p "$n") at $start+$size; reboot from the USB drive and rerun"
}
part_field() { sed -n "s|^.*p$1 : .*$2= *\([^,]*\).*|\1|p" "$work/current.sfdisk"; }
# write SRC to DST in full, flush it, then rename it into place
put() {
  install -m 0644 "$1" "$2.raytone-new"
  sync "$2.raytone-new" 2>/dev/null || sync
  cmp -s "$1" "$2.raytone-new" || die "$2 did not write back"
  mv -f "$2.raytone-new" "$2"
  sync
}
omarchy_uuid() {
  [[ -f $backup/omarchy-partuuid ]] || die "no $backup/omarchy-partuuid (shrink-app writes it)"
  tr 'A-Z' 'a-z' < "$backup/omarchy-partuuid"
}
run() { if ((write)); then echo "+ $*"; "$@"; else echo "would run: $*"; fi; }

work=$(mktemp -d)
trap 'umount "$MNT" 2>/dev/null || true; umount "$ROOT_MNT" 2>/dev/null || true; rm -rf "$work"' EXIT
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
      rm -f "$backup/backup-complete"
      mount -o ro,noload "$(p 1)" "$MNT"
      cp "$MNT/boot/extlinux/extlinux.conf" "$backup/extlinux.conf"
      # any tar error fails the backup (sockets, which tar cannot archive, are only a warning)
      (cd "$MNT" && tar --numeric-owner --xattrs --acls --warning=no-file-ignored -czpf "$backup/jetpack-app.tar.gz.part" .) ||
        die "tar failed; the backup is not usable"
      umount "$MNT"
      gzip -t "$backup/jetpack-app.tar.gz.part" || die "the APP archive does not read back"
      [[ $(tar -tzf "$backup/jetpack-app.tar.gz.part" | grep -c "^./boot/extlinux/extlinux.conf$") == 1 ]] ||
        die "the APP archive lacks /boot/extlinux/extlinux.conf"
      mv -f "$backup/jetpack-app.tar.gz.part" "$backup/jetpack-app.tar.gz"
      (cd "$backup" && sha256sum jetpack-app.tar.gz > jetpack-app.tar.gz.sha256)
      date -u +%FT%TZ > "$backup/backup-complete"
      echo "backed up: $backup (partition table, APP, extlinux.conf)"
    else
      echo "would back up the partition table, APP (read-only mount) and extlinux.conf into $backup"
    fi
    ;;
  shrink-app)
    need_state original
    backup_ok
    cmp -s "$work/current.sfdisk" "$backup/nvme-gpt.sfdisk" || die "the table changed since the backup"
    [[ $(dumpe2fs -h "$(p 1)" 2>/dev/null | awk -F: '/^Block size/{gsub(/ /,"",$2); print $2}') == 4096 ]] ||
      die "APP's ext4 block size is not 4096; the resize2fs block count would be wrong"
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
      partx -u "$dev" || die "the kernel did not take the new table (partx); reboot from the USB drive, then check"
      [[ $(state || true) == split ]] || die "the table did not come out split; restore: sfdisk $dev < $backup/nvme-gpt.sfdisk"
      kernel_sees 1 "$(part_field 1 start)" "$(part_field 1 size)"
      kernel_sees 12 "$(part_field 12 start)" "$(part_field 12 size)"
      e2fsck -f -n "$(p 1)" || die "APP does not check clean after the shrink"
      echo "APP: $APP_GIB GiB, PARTUUID $APP_PARTUUID; RAYTONE_OMARCHY: PARTUUID $uuid"
    fi
    ;;
  create-root)
    need_state split
    uuid=$(omarchy_uuid)
    kernel_sees 12 "$(part_field 12 start)" "$(part_field 12 size)"
    [[ $(blkid -o value -s PARTUUID "$(p 12)" 2>/dev/null) == "$uuid" ]] || die "$(p 12) is not PARTUUID $uuid"
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
      [[ ! -e $SRC_ROOT/var/lib/pacman/db.lck ]] || die "pacman is running (db.lck); let it finish"
      # the source must be quiet: nobody logged in at the Thor (the greeter and SSH sessions are fine)
      sessions=$(loginctl list-sessions --no-legend) || die "cannot list the login sessions (loginctl)"
      [[ -z $(awk '$6 == "user" && $4 != "-"' <<< "$sessions") ]] ||
        die "someone is logged in at the Thor; log out of the desktop and text consoles first"
      stopped=()
      for s in "${SERVICES[@]}"; do
        if systemctl is-active --quiet "$s"; then systemctl stop "$s"; stopped+=("$s"); fi
      done
      trap 'umount "$MNT" 2>/dev/null || true; rm -rf "$work"; for s in "${stopped[@]}"; do systemctl start "$s" || true; done' EXIT
      mount -o noatime "$(p 12)" "$MNT"
      # a clone that stopped half way resumes: the marker names the partition it was writing
      if [[ -n $(ls -A "$MNT" | grep -vxE 'lost\+found|\.raytone-cloning|\.raytone-cloned') ]]; then
        [[ $(cat "$MNT/.raytone-cloning" 2>/dev/null) == "$uuid" || $(cat "$MNT/.raytone-cloned" 2>/dev/null) == "$uuid" ]] ||
          die "$(p 12) holds something that is not this clone"
      fi
      # the backup (53 GB of JetPack) stays on the USB drive, wherever it is under the source root
      src_real=$(readlink -f "$SRC_ROOT"); src_real=${src_real%/}; bk_real=$(readlink -f "$backup"); backup_exclude=()
      [[ $bk_real == "$src_real"/* ]] && backup_exclude=("--exclude=${bk_real#"$src_real"}/")
      rm -f "$MNT/.raytone-cloned"
      echo "$uuid" > "$MNT/.raytone-cloning"
      sync
      for pass in 1 2; do
      echo "+ rsync pass $pass"
      rsync -aHAXS --numeric-ids --delete --one-file-system \
        --exclude=/proc/* --exclude=/sys/* --exclude=/dev/* --exclude=/run/* --exclude=/tmp/* --exclude=/mnt/* \
        "${backup_exclude[@]}" --exclude=/home/*/cudatest/ --exclude=/home/*/ollamatest/ \
        --exclude=/home/*/nftspike/ --exclude=/home/*/nctktest/ --exclude=/.raytone-cloned --exclude=/.raytone-cloning \
        "$SRC_ROOT/" "$MNT/"
      done
      planner fstab --in "$MNT/etc/fstab" --root-partuuid "$uuid" > "$work/fstab"
      install -m 0644 "$work/fstab" "$MNT/etc/fstab"
      install -d "$MNT/etc/raytone"
      printf 'APP_PARTUUID=%s\nKERNEL=%s\nINITRD=%s\n' "$APP_PARTUUID" "$KERNEL_DST" "$INITRD_DST" > "$MNT/etc/raytone/nvme-boot.conf"
      echo "$uuid" > "$MNT/.raytone-cloned"
      rm -f "$MNT/.raytone-cloning"
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
    [[ -f $INITRD_SRC ]] || die "no initramfs at $INITRD_SRC"
    lsinitcpio "$INITRD_SRC" > "$work/initrd.list" || die "cannot list $INITRD_SRC"
    for m in pcie-tegra264.ko phy-tegra194-p2u.ko nvme.ko nvme-core.ko; do
      grep -q "/$m\$" "$work/initrd.list" || die "$INITRD_SRC lacks $m (mkinitcpio -P after installing raytone-thor-omarchy)"
    done
    [[ $(blkid -o value -s PARTUUID "$(p 12)" 2>/dev/null | tr 'A-Z' 'a-z') == "$uuid" ]] || die "$(p 12)'s PARTUUID is not $uuid"
    if ((write)); then
      # a skipped or interrupted clone must not become the default entry: check it, read-only, first
      # noload keeps the check read-only, so the journal must have nothing to replay (clone unmounts cleanly)
      dumpe2fs -h "$(p 12)" 2>/dev/null > "$work/p12.h" || die "cannot read $(p 12)'s superblock"
      grep -qE '^Filesystem state: +clean$' "$work/p12.h" && ! grep -q needs_recovery "$work/p12.h" ||
        die "$(p 12) is not cleanly unmounted (needs journal recovery); run clone again"
      mkdir -p "$ROOT_MNT"
      mount -o ro,noload "$(p 12)" "$ROOT_MNT"
      [[ $(cat "$ROOT_MNT/.raytone-cloned" 2>/dev/null) == "$uuid" && ! -e $ROOT_MNT/.raytone-cloning ]] ||
        die "$(p 12) holds no finished clone (run clone)"
      [[ $(awk '!/^[[:space:]]*#/ && $2 == "/" {print $1}' "$ROOT_MNT/etc/fstab") == "PARTUUID=$uuid" ]] ||
        die "the clone's fstab does not mount $(p 12) as /"
      printf 'APP_PARTUUID=%s\nKERNEL=%s\nINITRD=%s\n' "$APP_PARTUUID" "$KERNEL_DST" "$INITRD_DST" > "$work/nvme-boot.conf"
      cmp -s "$work/nvme-boot.conf" "$ROOT_MNT/etc/raytone/nvme-boot.conf" ||
        die "the clone's /etc/raytone/nvme-boot.conf is missing or wrong (kernel updates would not reach APP)"
      umount "$ROOT_MNT"
      mount -o noatime "$(p 1)" "$MNT"
      for d in boot boot/extlinux boot/extlinux/extlinux.conf boot/raytone-thor; do
        [[ ! -L $MNT/$d ]] || die "/$d on APP is a link"
      done
      planner extlinux --in "$MNT/boot/extlinux/extlinux.conf" --root-partuuid "$uuid" --kernel "$KERNEL_DST" \
        --initrd "$INITRD_DST" > "$work/extlinux.conf" || die "APP's extlinux.conf is not the recorded one; nothing changed"
      [[ -e $MNT/boot/extlinux/extlinux.conf.jetpack ]] || cp -p "$MNT/boot/extlinux/extlinux.conf" "$MNT/boot/extlinux/extlinux.conf.jetpack"
      cmp -s "$MNT/boot/extlinux/extlinux.conf.jetpack" "$backup/extlinux.conf" || die "extlinux.conf.jetpack is not the backed-up file"
      mkdir -p "$(dirname "$MNT$KERNEL_DST")"
      # kernel and initramfs first, each in full; the menu changes last, in one rename
      put "$KERNEL_SRC" "$MNT$KERNEL_DST"
      put "$INITRD_SRC" "$MNT$INITRD_DST"
      put "$work/extlinux.conf" "$MNT/boot/extlinux/extlinux.conf"
      umount "$MNT"
      echo "L4TLauncher: omarchy (default, root PARTUUID $uuid) and JetPack's primary; original in extlinux.conf.jetpack"
    else
      echo "would copy $KERNEL_SRC to APP $KERNEL_DST and add the omarchy entry (default) to APP's extlinux.conf"
    fi
    ;;
esac
