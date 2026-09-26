#!/bin/bash
# Install upstream Omarchy with the Jetson AGX Thor layer on the Thor USB drive's Arch root.
#
#   install-thor-omarchy.sh --disk /dev/disk/by-id/usb-... --serial S --packages DIR --user NAME \
#       [--write --confirm-serial S]
#
# Runs on JetPack as root, like install-thor-root.sh (which must have installed the drive's root
# first), in the same namespace chroot (lib/thor-chroot.sh). This is how Omarchy's own ISO installs:
# omarchy-apply-system and omarchy-provision-user run in a chroot of the target, and Omarchy's
# firewall step only edits files there, never the running kernel's firewall.
#
#   1. The port's packages in DIR (omarchy, omarchy-settings, raytone-thor-omarchy,
#      raytone-thor-graphics, raytone-thor-nft-modules, hyprland; any others are added too) are signed with a local key
#      (GNUPGHOME=~/raytone/signing, created if missing, never leaves the Thor's NVMe) and become the
#      drive's [raytone-thor] repository at /var/lib/raytone/repo.
#   2. pacman.conf and mirrorlist: the Thor templates (repository order: port, Arch Linux ARM,
#      Omarchy aarch64). Omarchy's signing key is fetched and locally signed.
#   3. What Omarchy's ISO adds to Omarchy's packages, in its order (manifests/omarchy-iso-packages:
#      bootstrap tools, PipeWire audio), then the Thor graphics stack and Omarchy, then Omarchy's
#      base package list, read from the installed omarchy package, with
#      manifests/omarchy-arm-substitutions applied.
#   4. raytone-omarchy-apply-system --install-user NAME --first-install (upstream's system setup with
#      the Thor overrides; the firewall override keeps SSH and mDNS open and enables UFW last).
#   5. NAME already exists (install-thor-root.sh), so it gets /etc/skel the way upstream's
#      omarchy-reinstall-configs replays it (cp -af, existing files kept as numbered backups), then
#      omarchy-provision-user --force --first-install in Omarchy's first-boot context
#      (provision-owner): the default context would take the ISO's offline x86_64 Node tarball.
#       Then the menu entries that cannot work on the Thor are hidden (raytone-thor-menu-extension).
#   5b. As Omarchy's ISO does: SDDM remembers NAME (the greeter has no user field), and Wi-Fi
#       profiles are unbound from JetPack's interface name (Omarchy's iwd dependency keeps wlan0).
#   6. Checks: packages, SDDM and the bring-up units enabled, UFW enabled with SSH and mDNS allowed,
#      pacman.conf.
#
# A dry run unless --write. Tests: tests/test_install_thor_omarchy.py (RAYTONE_* variables exist for them).
set -euo pipefail

HERE=$(dirname "$(readlink -f "$0")")
ORIG_ARGS=("$@")
die() { echo "install-thor-omarchy: $*" >&2; exit 1; }
# shellcheck source=lib/usb.sh
source "$HERE/lib/usb.sh"
# shellcheck source=lib/thor-chroot.sh
source "$HERE/lib/thor-chroot.sh"
# shellcheck source=lib/thor-repo.sh
source "$HERE/lib/thor-repo.sh"

disk='' serial='' write=0 confirm='' pkgdir='' user='' dev=''
while (($#)); do
  case $1 in
    --disk) disk=${2:-}; shift 2 ;;
    --serial) serial=${2:-}; shift 2 ;;
    --write) write=1; shift ;;
    --confirm-serial) confirm=${2:-}; shift 2 ;;
    --packages) pkgdir=${2:-}; shift 2 ;;
    --user) user=${2:-}; shift 2 ;;
    *) die "unknown argument $1" ;;
  esac
done
resolve_usb_disk
[[ $user =~ ^[a-z_][a-z0-9_-]*$ ]] || die "--user NAME is required"
[[ -d $pkgdir ]] || die "--packages DIR is required"

REQUIRED=(omarchy omarchy-settings raytone-thor-omarchy raytone-thor-graphics raytone-thor-nft-modules hyprland)
for p in "${REQUIRED[@]}"; do
  compgen -G "$pkgdir/$p-[0-9]*.pkg.tar.*" | grep -qE '\.pkg\.tar\.(xz|zst)$' || die "package $p not found in '$pkgdir'"
done
# Version order: when DIR holds several builds of a package, the newest is added to the database last.
mapfile -t PKG_FILES < <(compgen -G "$pkgdir/*.pkg.tar.*" | grep -E '\.pkg\.tar\.(xz|zst)$' | sort -V)

MNT=${RAYTONE_TARGET_MOUNT:-/mnt/raytone-target}
HOST_ETC=${RAYTONE_HOST_ETC:-/etc}
SIGNING=${RAYTONE_SIGNING_HOME:-$HOME/raytone/signing}
TEMPLATES=$HERE/../packages/raytone-thor-omarchy/pacman
SUBSTITUTIONS=$HERE/../manifests/omarchy-arm-substitutions
ISO_PACKAGES=$HERE/../manifests/omarchy-iso-packages
OMARCHY_KEY=40DFB630FF42BCFFB047046CF0134EE680CAC571
ROOT_DEV=${dev}2
[[ -f $TEMPLATES/pacman.conf && -f $TEMPLATES/mirrorlist ]] || die "no pacman templates in $TEMPLATES"
[[ -f $ISO_PACKAGES ]] || die "no $ISO_PACKAGES"

if ((!write)); then
  identity
  not_in_use
  check_layout
  echo "target: $ROOT_DEV (RAYTONE_ROOT on $disk)"
  echo "repository: ${PKG_FILES[*]##*/}"
  echo "then: Omarchy base list from the omarchy package, apply-system with the Thor overrides, provision $user"
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
[[ -f $MNT/.raytone-unpacked && -f $MNT/etc/arch-release ]] ||
  die "$ROOT_DEV holds no RaytoneOS Arch root; run install-thor-root.sh first"
thor_chroot_mount
# Omarchy's libalpm hook refuses direct pacman runs unless this is set.
pac() { in_target OMARCHY_ALLOW_DIRECT_PACMAN=1 pacman "$@"; }

# 1. Sign and publish the port's packages as the drive's repository.
repo_signing_key --create
repo_publish "${PKG_FILES[@]}"

# 2. Repositories and keys.
target_no_links etc/pacman.conf etc/pacman.d/mirrorlist
mkdir -p "$MNT/etc/pacman.d"
install -m 0644 "$TEMPLATES/pacman.conf" "$MNT/etc/pacman.conf"
install -m 0644 "$TEMPLATES/mirrorlist" "$MNT/etc/pacman.d/mirrorlist"
in_target pacman-key --add "$REPO/raytone-thor.gpg"
in_target pacman-key --lsign-key "$fpr"
in_target pacman-key --recv-keys "$OMARCHY_KEY" --keyserver keys.openpgp.org
in_target pacman-key --lsign-key "$OMARCHY_KEY"

# 3. The Thor graphics stack and Omarchy, then Omarchy's own base list.
pac -Syu --noconfirm
# First, as Omarchy's ISO does: its bootstrap set and archinstall's PipeWire audio, before Omarchy's
# own packages, so a `jack` dependency later resolves to pipewire-jack (jack2 conflicts with it).
ISO_PKGS=()
while read -r name _; do
  [[ -z $name || $name == \#* ]] || ISO_PKGS+=("$name")
done < "$ISO_PACKAGES"
pac -S --noconfirm --needed "${ISO_PKGS[@]}"
pac -S --noconfirm --needed raytone-thor-graphics hyprland omarchy omarchy-settings raytone-thor-omarchy
base=$MNT/usr/share/omarchy/install/omarchy-base.packages
[[ -f $base ]] || die "no $base after installing omarchy"
BASE_PKGS=()
while read -r name _; do
  [[ -z $name || $name == \#* ]] && continue
  sub=$(awk -v n="$name" '$1 == n {print $2}' "$SUBSTITUTIONS")
  [[ $sub == - ]] && continue
  BASE_PKGS+=("${sub:-$name}")
done < "$base"
pac -S --noconfirm --needed "${BASE_PKGS[@]}"
in_target gpgconf --homedir /etc/pacman.d/gnupg --kill all || true

# 4. Omarchy's system setup with the Thor overrides, then the user.
in_target OMARCHY_ALLOW_DIRECT_PACMAN=1 raytone-omarchy-apply-system --install-user "$user" --first-install ||
  die "raytone-omarchy-apply-system failed (log: /var/log/omarchy-install.log on the drive)"
as_user() {
  setpriv --no-new-privs --bounding-set "$DROP_CAPS" -- \
    chroot --userspec="$user:$user" "$MNT" /usr/bin/env -i PATH=/usr/bin HOME="/home/$user" USER="$user" LANG=C.UTF-8 \
    OMARCHY_SETUP_CONTEXT=provision-owner "$@"
}
as_user cp -af --backup=numbered /etc/skel/. "/home/$user/" || die "copying /etc/skel into /home/$user failed"
as_user omarchy-provision-user --force --first-install || die "omarchy-provision-user failed"
as_user raytone-thor-menu-extension || die "hiding the Thor-incompatible menu entries failed"
# As archinstall's PipeWire audio setup does for each user.
wants=/home/$user/.config/systemd/user/default.target.wants
as_user mkdir -p "$wants"
for u in pipewire-pulse.service pipewire-pulse.socket; do
  as_user ln -sf "/usr/lib/systemd/user/$u" "$wants/$u"
done

# 5b. What Omarchy's ISO does after setup (omarchy-iso configure_login, unencrypted): the greeter is
# password-only and logs in SDDM's last user, so seed it. No autologin: SDDM stays the auth screen.
target_no_links etc/sddm.conf.d/99-omarchy-login.conf var/lib/sddm/state.conf etc/NetworkManager/system-connections
install -d -m 0755 "$MNT/etc/sddm.conf.d" "$MNT/var/lib/sddm"
printf '[Theme]\nCurrent=omarchy\n\n[Users]\nRememberLastUser=true\nRememberLastSession=true\n' \
  > "$MNT/etc/sddm.conf.d/99-omarchy-login.conf"
printf '[Last]\nSession=omarchy.desktop\nUser=%s\n' "$user" > "$MNT/var/lib/sddm/state.conf"
in_target chown sddm:sddm /var/lib/sddm /var/lib/sddm/state.conf
# Omarchy's aarch64 dependency iwd ships 80-iwd.link (NamePolicy=keep kernel): Wi-Fi is wlan0 here,
# not the predictable name the profiles copied from JetPack are bound to. Unbind Wi-Fi profiles.
for f in "$MNT"/etc/NetworkManager/system-connections/*.nmconnection; do
  [[ -f $f ]] || continue
  target_no_links "${f#"$MNT"}"
  [[ -r $f ]] || die "cannot read ${f#"$MNT"}; not unbinding it from JetPack's interface name"
  grep -qx 'type=wifi' "$f" || continue
  # A fresh file (mktemp: new name, O_EXCL, 0600, as NetworkManager requires; the profile holds
  # the PSK) that replaces the profile in one rename, or not at all.
  tmp=$(mktemp "$f.XXXXXX") || die "cannot create a temporary file next to ${f#"$MNT"}"
  rc=0
  grep -vE '^interface-name=' "$f" > "$tmp" || rc=$?
  # grep: 1 only means no line was left, which a profile never is; anything else is a failure
  if ((rc > 1)) || [[ ! -s $tmp ]] || ! mv -f "$tmp" "$f"; then
    rm -f "$tmp"
    die "rewriting ${f#"$MNT"} failed; it is left as it was"
  fi
done

# 6. Verify.
in_target pacman -Q omarchy omarchy-settings raytone-thor-omarchy raytone-thor-graphics hyprland > /dev/null ||
  die "not every package is installed"
for u in sddm raytone-deadman.timer raytone-thermal-guard; do
  in_target systemctl is-enabled "$u" > /dev/null || die "unit not enabled: $u"
done
grep -qx "ENABLED=yes" "$MNT/etc/ufw/ufw.conf" || die "UFW is not enabled for the next boot"
grep -qE "^### tuple ### allow tcp 22 " "$MNT/etc/ufw/user.rules" || die "firewall does not allow SSH (22/tcp)"
grep -qE "^### tuple ### allow udp 5353 " "$MNT/etc/ufw/user.rules" || die "firewall does not allow mDNS (5353/udp)"
cmp -s "$TEMPLATES/pacman.conf" "$MNT/etc/pacman.conf" || die "/etc/pacman.conf is not the Thor template after setup"
target_no_links var/lib/raytone/installed-packages-omarchy.txt
in_target pacman -Q > "$MNT/var/lib/raytone/installed-packages-omarchy.txt" 2>/dev/null || true
sync
echo "verified: packages, sddm and bring-up units, UFW with SSH and mDNS, pacman.conf"
echo "installed: Omarchy $(in_target pacman -Q omarchy 2>/dev/null | awk '{print $2}') with the Thor layer on $ROOT_DEV"
