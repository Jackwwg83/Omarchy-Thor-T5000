#!/bin/bash
# Publish new builds to the Thor USB drive's [raytone-thor] repository, so that omarchy-update on
# the drive picks them up. Installs nothing.
#
#   publish-thor-repo.sh --disk /dev/disk/by-id/usb-... --serial S [--write --confirm-serial S] PKG...
#   publish-thor-repo.sh --nvme /dev/disk/by-id/nvme-... --serial S [--write --confirm-serial S] PKG...
#
# --nvme: Omarchy installed on the NVMe (install-thor-nvme.sh) has its own repository on
# RAYTONE_OMARCHY (p12); JetPack runs from p1 of the same disk and publishes into p12, unmounted.
#
# Runs on JetPack as root with the drive not in use (the drive's Arch is not running): the signing
# key stays on the Thor's NVMe (~/raytone/signing). The drive must have the repository that
# install-thor-omarchy.sh created, and the key it trusts; no new key is ever made here. Each PKG is
# signed (once), copied, and added to the database; older files stay for rollback.
#
# A dry run unless --write. Tests: tests/test_publish_thor_repo.py (RAYTONE_* variables exist for them).
set -euo pipefail

HERE=$(dirname "$(readlink -f "$0")")
ORIG_ARGS=("$@")
die() { echo "publish-thor-repo: $*" >&2; exit 1; }
# shellcheck source=lib/usb.sh
source "$HERE/lib/usb.sh"
# shellcheck source=lib/thor-chroot.sh
source "$HERE/lib/thor-chroot.sh"
# shellcheck source=lib/thor-repo.sh
source "$HERE/lib/thor-repo.sh"

disk='' serial='' write=0 confirm='' dev='' nvme=''
PKG_FILES=()
while (($#)); do
  case $1 in
    --disk) disk=${2:-}; shift 2 ;;
    --nvme) nvme=${2:-}; shift 2 ;;
    --serial) serial=${2:-}; shift 2 ;;
    --write) write=1; shift ;;
    --confirm-serial) confirm=${2:-}; shift 2 ;;
    -*) die "unknown argument $1" ;;
    *) PKG_FILES+=("$1"); shift ;;
  esac
done
if [[ -n $nvme ]]; then
  [[ -z $disk && -n $serial ]] || die "usage: --nvme /dev/disk/by-id/nvme-... --serial SERIAL (not with --disk)"
  [[ $(basename "$nvme") == nvme-* && $(basename "$(dirname "$nvme")") == by-id ]] ||
    die "--nvme must be a /dev/disk/by-id/nvme-* link, got $nvme"
  dev=$(readlink -f "$nvme")
  name=$(basename "$dev")
  [[ $name =~ ^nvme[0-9]+n[0-9]+$ ]] || die "$nvme resolves to $dev, not a whole NVMe disk node"
  disk=$nvme
else
  resolve_usb_disk
fi
((${#PKG_FILES[@]})) || die "name at least one package file to publish"
for f in "${PKG_FILES[@]}"; do
  # a plain package file name: pacman's name-version-release-arch characters only
  pkgfile=${f##*/}
  [[ -f $f && $pkgfile =~ ^[A-Za-z0-9@._+-]+\.pkg\.tar\.(xz|zst)$ ]] || die "not a package file: $(printf %q "$pkgfile")"
done

MNT=${RAYTONE_TARGET_MOUNT:-/mnt/raytone-target}
HOST_ETC=${RAYTONE_HOST_ETC:-/etc}
SIGNING=${RAYTONE_SIGNING_HOME:-$HOME/raytone/signing}
ROOT_DEV=${dev}2
if [[ -n $nvme ]]; then
  ROOT_DEV=${dev}p12
  # the NVMe holds JetPack's running root on p1: check the disk and that p12 is Omarchy's, idle
  identity() {
    local type tran ser
    read -r type tran ser _ < <(lsblk -dn -b -o TYPE,TRAN,SERIAL,SIZE "$dev")
    [[ $type == disk && $tran == nvme ]] || die "$dev is '$type' on '$tran', not an NVMe disk"
    [[ $ser == "$serial" ]] || die "$dev serial is '$ser', expected '$serial'"
  }
  not_in_use() {
    [[ $(basename "$(findmnt -n -o SOURCE /)") != "${name}p12" ]] || die "$ROOT_DEV holds / (publish from JetPack)"
    [[ -z $(findmnt -rn -S "$ROOT_DEV") ]] || die "$ROOT_DEV is mounted"
  }
  check_layout() {
    [[ $(lsblk -n -o PARTLABEL,FSTYPE "$ROOT_DEV") == "RAYTONE_OMARCHY ext4" ]] ||
      die "$ROOT_DEV is not an ext4 RAYTONE_OMARCHY (install-thor-nvme.sh)"
  }
  suppress_automount() { :; }
  restore_automount() { :; }
fi

# name-version-release, as repo-add names the database entry
entry() { local e=${1##*/}; e=${e%.pkg.tar.*}; echo "${e%-*}"; }

if ((!write)); then
  identity
  not_in_use
  check_layout
  echo "target: [raytone-thor] on $ROOT_DEV (RAYTONE_ROOT on $disk)"
  echo "publish: ${PKG_FILES[*]##*/}"
  echo "dry run: nothing written. Add --write --confirm-serial $serial."
  exit 0
fi
[[ $confirm == "$serial" ]] || die "--confirm-serial must repeat the disk serial before anything is written"
[[ $EUID -eq 0 || ${RAYTONE_SKIP_ROOT_CHECK:-} == 1 ]] || die "must run as root to write"
if [[ ${RAYTONE_IN_NS:-} != 1 && ${RAYTONE_NO_UNSHARE:-} != 1 ]]; then
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
[[ -f $MNT/.raytone-unpacked && -f $MNT$REPO/$REPO_DB ]] ||
  die "$ROOT_DEV has no [raytone-thor] repository; run install-thor-omarchy.sh first"
repo_signing_key
thor_chroot_mount
# pacman accepts a signature when its key is valid in pacman's keyring: full (f) or ultimate (u),
# which install-thor-omarchy.sh's pacman-key --lsign-key gives the repository key.
validity=$(in_target gpg --homedir /etc/pacman.d/gnupg --batch --list-keys --with-colons "$fpr" 2>/dev/null |
  awk -F: '$1 == "pub" {print $2; exit}')
[[ $validity == [fu] ]] ||
  die "the drive's pacman does not trust the signing key $fpr (validity '${validity:-none}'; install-thor-omarchy.sh lsigns it)"
repo_publish --verify "${PKG_FILES[@]}"

listed=$(tar -tzf "$MNT$REPO/$REPO_DB" | sed 's|^\./||; s|/.*||' | sort -u)
for f in "${PKG_FILES[@]}"; do
  grep -qx "$(entry "$f")" <<< "$listed" || die "the database does not list $(entry "$f")"
done
sync
echo "published: $(for f in "${PKG_FILES[@]}"; do printf '%s ' "$(entry "$f")"; done)"
echo "on the drive: omarchy-update (or pacman -Syu) installs them"
