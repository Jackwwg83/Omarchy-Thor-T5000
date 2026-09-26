#!/bin/bash
# Publish new builds to the Thor USB drive's [raytone-thor] repository, so that omarchy-update on
# the drive picks them up. Installs nothing.
#
#   publish-thor-repo.sh --disk /dev/disk/by-id/usb-... --serial S [--write --confirm-serial S] PKG...
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

disk='' serial='' write=0 confirm='' dev=''
PKG_FILES=()
while (($#)); do
  case $1 in
    --disk) disk=${2:-}; shift 2 ;;
    --serial) serial=${2:-}; shift 2 ;;
    --write) write=1; shift ;;
    --confirm-serial) confirm=${2:-}; shift 2 ;;
    -*) die "unknown argument $1" ;;
    *) PKG_FILES+=("$1"); shift ;;
  esac
done
resolve_usb_disk
((${#PKG_FILES[@]})) || die "name at least one package file to publish"
for f in "${PKG_FILES[@]}"; do
  # a plain package file name: pacman's name-version-release-arch characters only
  name=${f##*/}
  [[ -f $f && $name =~ ^[A-Za-z0-9@._+-]+\.pkg\.tar\.(xz|zst)$ ]] || die "not a package file: $(printf %q "$name")"
done

MNT=${RAYTONE_TARGET_MOUNT:-/mnt/raytone-target}
HOST_ETC=${RAYTONE_HOST_ETC:-/etc}
SIGNING=${RAYTONE_SIGNING_HOME:-$HOME/raytone/signing}
ROOT_DEV=${dev}2

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
