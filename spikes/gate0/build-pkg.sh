#!/bin/bash
# Spike helper: build one recipe from packages/ with makepkg inside the probe root, as uid 1000,
# and install the result there. Shares the namespace setup with gate0a.sh; replaced later by the
# tested build tooling.
#
#   build-pkg.sh PKGDIR            build, install into the probe root
#   NODEPS=1 build-pkg.sh PKGDIR   repackaging recipes: no dependency install, makepkg --nodeps, not installed
set -euo pipefail
shopt -s nullglob
# shellcheck source=gate0a.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/gate0a.sh"
SCRIPT_BP=$(readlink -f "${BASH_SOURCE[0]}")
EVID=$WORK/evidence/build
OUT=$WORK/pkgs

inside_build() {
  require_namespace
  setup_root
  local name=$1 src=$2 b=/build/$1
  setup_packages base-devel
  mkdir -p "$ROOT/build/out" "$ROOT/build-home"
  rm -rf "$ROOT$b" && cp -rL "$src" "$ROOT$b"
  chown -R 1000:1000 "$ROOT$b" "$ROOT/build/out" "$ROOT/build-home"
  # Dependencies as root (makepkg -s would need sudo inside the root).
  [[ ${NODEPS:-} == 1 ]] || in_root bash -c "cd $b && source PKGBUILD && pacman -S --noconfirm --needed --asdeps \"\${depends[@]%%[<>=]*}\" \"\${makedepends[@]%%[<>=]*}\""
  timeout 7200 chroot --userspec=1000:1000 "$ROOT" /usr/bin/env -i PATH=/usr/bin HOME=/build-home LANG=C.UTF-8 \
    MAKEFLAGS="-j$(nproc)" PKGDEST=/build/out bash -c "cd $b && makepkg --noconfirm --cleanbuild ${NODEPS:+--nodeps}" \
    > "$EVID/$name-makepkg.log" 2>&1
  mkdir -p "$OUT"
  cp "$ROOT"/build/out/*.pkg.tar.* "$OUT/"
  [[ ${NODEPS:-} == 1 ]] && { ls "$OUT"/"$name"-[0-9]*.pkg.tar.* > "$EVID/$name-built.txt"; return 0; }
  local pkg
  for pkg in "$ROOT"/build/out/"$name"-[0-9]*.pkg.tar.*; do in_root pacman -U --noconfirm "/build/out/$(basename "$pkg")"; done
  in_root pacman -Q "$name" > "$EVID/$name-installed.txt"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  case ${1:-} in
    inside-build) inside_build "$2" "$3" ;;
    *)
      [[ -f ${1:-}/PKGBUILD ]] || { echo "usage: $0 PKGDIR" >&2; exit 2; }
      check_work
      mkdir -p "$EVID"
      src=$(readlink -f "$1")
      sudo unshare --mount --pid --fork --propagation private -- \
        env RAYTONE_NS=1 WORK="$WORK" EVID="$EVID" PKG_MIRROR="${PKG_MIRROR:-}" NODEPS="${NODEPS:-}" bash "$SCRIPT_BP" inside-build "$(basename "$src")" "$src"
      sudo chown -R "$(id -u):$(id -g)" "$EVID" "$OUT"
      ;;
  esac
fi
