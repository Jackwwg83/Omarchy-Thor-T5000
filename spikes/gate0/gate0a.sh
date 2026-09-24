#!/bin/bash
# Gate 0a spike: probe Arch Linux ARM userspace against the host's L4T graphics
# libraries on a running JetPack system, without stopping the display manager.
#
# Spike code (see README.md): it answers one question and is then discarded in
# favour of tested build tooling. Run as the normal user on the Thor. The only
# privileged part runs in fresh mount and PID namespaces, so its mounts and any
# leftover processes disappear when it exits. gate0b.sh sources this file for
# the shared setup functions.
set -euo pipefail
shopt -s nullglob

SCRIPT=$(readlink -f "${BASH_SOURCE[0]}")
WORK=${WORK:-$HOME/raytone}
ROOT=$WORK/probe-root
EVID=${EVID:-$WORK/evidence/gate0a}
CACHE=$WORK/cache
TARBALL=ArchLinuxARM-aarch64-latest.tar.gz
MIRROR=${MIRROR:-http://os.archlinuxarm.org/os}
ALARM_KEY=68B3537F39A313B3E574D06777193F152BDBE6A6
L4T_NV=/usr/lib/aarch64-linux-gnu/nvidia
L4T_DIRS=("$L4T_NV" /usr/lib/aarch64-linux-gnu/tegra-egl /opt/nvidia/l4t-gpu-libs)
# Only NVIDIA-named libraries enter the loader path; L4T's own libvulkan,
# libv4l and Ada runtime copies must not shadow Arch's. The EGL platform glue
# (egl-wayland, egl-gbm) is registered by absolute path instead, so the L4T and
# Arch builds can be swapped without touching the loader cache.
ALLOW_RE='^(libnv|libcuda|libGLX_nvidia|libEGL_nvidia|libGLES(v1_CM|v2)_nvidia|libtegra|libjetsonpower|libgstnv|libv4l2_nv|libVkLayer_json_gen|libVkSCLayer|libvulkansc)'
GLUE_RE='^libnvidia-egl-(wayland|gbm)\.so'
GPU_NODES=(/dev/nvidia0 /dev/nvidia1 /dev/nvidiactl /dev/nvidia-modeset /dev/nvidia-uvm /dev/nvidia-uvm-tools
           /dev/host1x-fence /dev/nvmap)
PROBE_PKGS=(mesa libglvnd vulkan-icd-loader drm-info mesa-utils vulkan-tools gcc pkgconf libdrm)
# EGL platform glue per variant, each registered by absolute path in its own directory. Both keep
# L4T's egl-gbm; "arch" swaps only egl-wayland for Arch's newer build, so an A/B has one variable.
declare -A GLUE_DIR=([l4t]=/etc/raytone/egl-l4t [arch]=/etc/raytone/egl-arch)
ARCH_EGL_WAYLAND=/usr/lib/libnvidia-egl-wayland.so.1
GLUE=${GLUE:-l4t}
# Capabilities the package manager never needs; dropping them also keeps it
# from loading modules, remounting efivarfs or touching raw devices.
DROP_CAPS=-sys_module,-sys_rawio,-sys_admin,-sys_ptrace,-sys_boot,-sys_time,-mknod,-sys_pacct,-syslog,-mac_admin,-mac_override,-wake_alarm,-block_suspend,-bpf,-perfmon,-linux_immutable,-sys_tty_config,-lease

check_work() {
  [[ $WORK == /home/*/* && $(readlink -f "$WORK") == "$WORK" ]] ||
    { echo "WORK must be an absolute path under /home without symlinks: $WORK" >&2; exit 1; }
  local p
  for p in "$ROOT" "$EVID" "$CACHE"; do
    [[ ! -L $p ]] || { echo "refusing symlinked path $p" >&2; exit 1; }
  done
}

fetch_rootfs() (
  mkdir -p "$CACHE" "$EVID"
  cd "$CACHE"
  if [[ ! -f $TARBALL ]]; then
    curl -fL --retry 5 -C - -o "$TARBALL.part" "$MIRROR/$TARBALL"
    mv "$TARBALL.part" "$TARBALL"
  fi
  curl -fsL -o "$TARBALL.md5" "$MIRROR/$TARBALL.md5"
  curl -fsL -o "$TARBALL.sig" "$MIRROR/$TARBALL.sig"
  md5sum -c "$TARBALL.md5"
  gnupg=$(mktemp -d)
  GNUPGHOME=$gnupg gpg -q --keyserver hkps://keyserver.ubuntu.com --recv-keys "$ALARM_KEY"
  GNUPGHOME=$gnupg gpg -q --verify "$TARBALL.sig" "$TARBALL"
  GNUPGHOME=$gnupg gpgconf --kill all
  rm -rf "$gnupg"
  { echo "tarball: $TARBALL"; echo "sha256: $(sha256sum "$TARBALL" | cut -d' ' -f1)"
    echo "signature: good, key $ALARM_KEY"; } > "$EVID/rootfs.txt"
)

# Read-only facts from the JetPack host for the package ledger (kept out of git).
host_facts() {
  local out=$CACHE/l4t-host p m
  mkdir -p "$out/maintscripts" "$out/etc"
  # -W also lists packages dpkg knows but has not installed (e.g. the nvgpu set); keep installed ones.
  dpkg-query -W -f='${db:Status-Abbrev}\t${Package}\t${Version}\n' 'nvidia-l4t-*' |
    awk -F'\t' '$1 ~ /^ii/ {print $2 "\t" $3}' > "$out/packages.tsv"
  local pkgs=()
  mapfile -t pkgs < <(cut -f1 "$out/packages.tsv")
  for p in "${pkgs[@]}"; do dpkg -L "$p" | sed "s|^|$p\t|"; done > "$out/files.tsv"
  apt-cache policy "${pkgs[@]}" > "$out/apt-policy.txt" 2>&1
  for m in nvidia nvidia_drm nvidia_modeset nvidia_uvm tegra_dce host1x nvethernet r8125 rtw89_8852be ext4; do
    printf '%s\t%s\t%s\n' "$m" "$(modinfo -n "$m" 2>/dev/null)" "$(modinfo -F vermagic "$m" 2>/dev/null)"
  done > "$out/modules.tsv"
  for p in /var/lib/dpkg/info/nvidia-l4t-*.{preinst,postinst,prerm,postrm,triggers,conffiles}; do cp "$p" "$out/maintscripts/"; done
  for p in /etc/modprobe.d /etc/depmod.d; do [[ -d $p ]] && cp -rL "$p" "$out/etc/"; done
  [[ -f /etc/systemd/nv-load-gpu-libs.sh ]] && cp -L /etc/systemd/nv-load-gpu-libs.sh "$out/"
  systemctl cat nv-load-display-modules.service nvfancontrol.service nvpmodel.service nvpower.service \
    nvcpupowerfix.service nv_hugetlbfs_init.service nv-graphics.service > "$out/units.txt" 2>&1 || true
  uname -r > "$out/kernel.txt"
}

in_root() { # run as root inside the probe root with dangerous capabilities dropped
  # no_new_privs lets pacman 7 apply its Landlock download sandbox without CAP_SYS_ADMIN.
  setpriv --no-new-privs --bounding-set "$DROP_CAPS" -- \
    chroot "$ROOT" /usr/bin/env -i PATH=/usr/bin HOME=/root LANG=C.UTF-8 "$@"
}

PASS=() FAIL=()
probe() { # probe NAME CMD... : run as the unprivileged user, output to $EVID/NAME.txt
  local name=$1; shift
  local rc=0
  timeout 90 chroot --userspec=1000:1000 --groups=44,993 "$ROOT" \
    /usr/bin/env -i PATH=/usr/bin HOME=/tmp LANG=C.UTF-8 \
    __EGL_EXTERNAL_PLATFORM_CONFIG_DIRS="${GLUE_DIR[$GLUE]}" "$@" > "$EVID/$name.txt" 2>&1 || rc=$?
  echo "exit: $rc" >> "$EVID/$name.txt"
  if (( rc == 0 )); then PASS+=("$name"); else FAIL+=("$name (exit $rc)"); fi
}

bind_ro() { mkdir -p "$2"; mount --bind "$1" "$2"; mount -o remount,bind,ro "$2"; }
bind_node() { touch "$2"; mount --bind "$1" "$2"; }

require_namespace() {
  [[ ${RAYTONE_NS:-} == 1 && $$ -eq 1 && $EUID -eq 0 ]] ||
    { echo "inside: only reachable through the namespace wrapper" >&2; exit 1; }
  check_work
}

# Unpack once, then mount the root with a private /dev, sysfs read-only and own /run and /tmp.
setup_root() {
  if [[ ! -f $ROOT/etc/arch-release ]]; then
    rm -rf "$ROOT.partial" && mkdir -p "$ROOT.partial"
    tar --xattrs --xattrs-include='*' --acls --numeric-owner -xpf "$CACHE/$TARBALL" -C "$ROOT.partial"
    rm -rf "$ROOT" && mv "$ROOT.partial" "$ROOT"
  fi
  # The root must be a mount point, as arch-chroot does, or pacman's disk space check fails.
  mount --bind "$ROOT" "$ROOT"
  mount -t proc proc "$ROOT/proc"
  mount -t sysfs -o ro,nosuid,nodev,noexec sysfs "$ROOT/sys"
  mount -t tmpfs -o mode=0755,nosuid tmpfs "$ROOT/dev"
  local n
  for n in null zero full random urandom tty; do bind_node "/dev/$n" "$ROOT/dev/$n"; done
  mkdir -p "$ROOT/dev/pts" "$ROOT/dev/shm"
  mount -t devpts -o newinstance,ptmxmode=0666 devpts "$ROOT/dev/pts"
  ln -s pts/ptmx "$ROOT/dev/ptmx"
  mount -t tmpfs -o mode=1777 tmpfs "$ROOT/dev/shm"
  ln -s /proc/self/fd "$ROOT/dev/fd"
  mount -t tmpfs -o mode=0755 tmpfs "$ROOT/run"
  mount -t tmpfs -o mode=1777 tmpfs "$ROOT/tmp"
  rm -f "$ROOT/etc/resolv.conf" && cat /etc/resolv.conf > "$ROOT/etc/resolv.conf"
}

setup_packages() { # setup_packages PKG... : keyring and full upgrade once, then the requested packages
  if [[ -n ${PKG_MIRROR:-} ]]; then
    printf 'Server = %s/$arch/$repo\n' "$PKG_MIRROR" > "$ROOT/etc/pacman.d/mirrorlist"
  fi
  if [[ ! -f $ROOT/.raytone-probe-ready ]]; then
    in_root pacman-key --init
    in_root pacman-key --populate archlinuxarm
    if ! in_root pacman -Sy --noconfirm archlinuxarm-keyring 2>&1 | tee "$EVID/pacman-keyring.txt"; then
      grep -qi -E 'sandbox|landlock' "$EVID/pacman-keyring.txt" || exit 1
      # Only when the download sandbox is the failure; the option belongs in [options].
      grep -q '^DisableSandbox' "$ROOT/etc/pacman.conf" ||
        sed -i '/^\[options\]/a DisableSandbox' "$ROOT/etc/pacman.conf"
      in_root pacman -Sy --noconfirm archlinuxarm-keyring
    fi
    if in_root pacman -Q linux-aarch64 >/dev/null 2>&1; then in_root pacman -Rdd --noconfirm linux-aarch64; fi
    in_root pacman -Su --noconfirm
    touch "$ROOT/.raytone-probe-ready"
  fi
  # Earlier probe runs wrote these registrations by hand; drop them unless a package owns them.
  local f
  for f in /usr/share/egl/egl_external_platform.d/{10_nvidia_wayland,15_nvidia_gbm}.json; do
    [[ -e $ROOT$f ]] && ! in_root pacman -Qo "$f" >/dev/null 2>&1 && rm -f "$ROOT$f"
  done
  in_root pacman -S --noconfirm --needed "$@"
  in_root gpgconf --homedir /etc/pacman.d/gnupg --kill all || true
}

# Host L4T libraries read-only at their own paths, an allowlisted loader directory, and registrations.
setup_l4t() {
  local d f base farm=$ROOT/usr/lib/raytone-l4t
  for d in "${L4T_DIRS[@]}"; do bind_ro "$d" "$ROOT$d"; done
  rm -rf "$farm" && mkdir -p "$farm"
  : > "$EVID/l4t-excluded.txt"
  for f in "$L4T_NV"/*.so* /usr/lib/aarch64-linux-gnu/tegra-egl/*.so* /opt/nvidia/l4t-gpu-libs/openrm/*.so*; do
    base=$(basename "$f")
    if [[ ! $base =~ $ALLOW_RE || $base =~ $GLUE_RE ]]; then echo "$f" >> "$EVID/l4t-excluded.txt"; continue; fi
    [[ ! -e $farm/$base ]] || { echo "duplicate library name $base" >&2; exit 1; }
    ln -s "$f" "$farm/$base"
  done
  echo /usr/lib/raytone-l4t > "$ROOT/etc/ld.so.conf.d/raytone-l4t.conf"

  mkdir -p "$ROOT/etc/glvnd/egl_vendor.d" "$ROOT/usr/lib/gbm" "$ROOT/etc/vulkan/icd.d" \
           "$ROOT${GLUE_DIR[l4t]}" "$ROOT${GLUE_DIR[arch]}"
  cp /usr/share/glvnd/egl_vendor.d/10_nvidia.json "$ROOT/etc/glvnd/egl_vendor.d/10_nvidia.json"
  local reg='{"file_format_version":"1.0.0","ICD":{"library_path":"%s"}}\n'
  # shellcheck disable=SC2059
  {
    printf "$reg" "$L4T_NV/libnvidia-egl-wayland.so.1" > "$ROOT${GLUE_DIR[l4t]}/10_nvidia_wayland.json"
    printf "$reg" "$L4T_NV/libnvidia-egl-gbm.so.1" > "$ROOT${GLUE_DIR[l4t]}/15_nvidia_gbm.json"
    printf "$reg" "$L4T_NV/libnvidia-egl-gbm.so.1" > "$ROOT${GLUE_DIR[arch]}/15_nvidia_gbm.json"
    rm -f "$ROOT${GLUE_DIR[arch]}/10_nvidia_wayland.json"
    [[ -e $ROOT$ARCH_EGL_WAYLAND ]] &&
      printf "$reg" "$ARCH_EGL_WAYLAND" > "$ROOT${GLUE_DIR[arch]}/10_nvidia_wayland.json"
  }
  cp -L "$L4T_NV/nvidia_icd.json" "$ROOT/etc/vulkan/icd.d/nvidia_icd.json"
  ln -sfn "$(readlink -f /usr/lib/aarch64-linux-gnu/gbm/nvidia-drm_gbm.so)" "$ROOT/usr/lib/gbm/nvidia-drm_gbm.so"
  ln -sfn "$(readlink -f /usr/lib/aarch64-linux-gnu/gbm/tegra_gbm.so)" "$ROOT/usr/lib/gbm/tegra_gbm.so"
  in_root ldconfig
}

# GPU and display nodes; udev database read-only, never its control socket.
add_gpu_nodes() {
  local n
  for n in "${GPU_NODES[@]}"; do [[ -e $n ]] && bind_node "$n" "$ROOT$n"; done
  bind_ro /dev/dri "$ROOT/dev/dri"
  [[ -d /dev/nvidia-caps ]] && bind_ro /dev/nvidia-caps "$ROOT/dev/nvidia-caps"
  [[ -d /run/udev/data ]] && bind_ro /run/udev/data "$ROOT/run/udev/data"
  return 0
}

# DRM nodes by what they are, since card/renderD numbers can change between boots.
thor_drm_nodes() {
  local node dev
  for node in /sys/class/drm/*; do
    [[ $(basename "$node") =~ ^(card|renderD)[0-9]+$ ]] || continue
    dev=$(cat "$node/device/uevent" 2>/dev/null)
    [[ $dev == *OF_COMPATIBLE_0=nvidia,tegra264-display* || $dev == *PCI_ID=10DE:2B00* ]] && echo "/dev/dri/$(basename "$node")"
  done
  return 0
}
display_card() { # the KMS node with connectors
  local node
  for node in $(thor_drm_nodes); do
    [[ $(basename "$node") == card* ]] || continue
    grep -q OF_COMPATIBLE_0=nvidia,tegra264-display "/sys/class/drm/$(basename "$node")/device/uevent" && echo "$node"
  done
  return 0
}

probes_0a() {
  local drv node
  drv=$(modinfo -F version nvidia)
  probe versions pacman -Q "${PROBE_PKGS[@]}" glibc
  probe ldcache bash -c "ldconfig -p | grep -E 'libvulkan\.|libgbm|libEGL|libGLX|libnvidia-allocator|libcuda\.|libnvidia-egl'"
  probe ldd bash -c "rc=0; for l in /usr/lib/raytone-l4t/libEGL_nvidia.so.0 /usr/lib/raytone-l4t/libGLX_nvidia.so.0 \
      /usr/lib/raytone-l4t/libnvidia-allocator.so.1 /usr/lib/raytone-l4t/libnvidia-eglcore.so.$drv \
      $L4T_NV/libnvidia-egl-gbm.so.1 $L4T_NV/libnvidia-egl-wayland.so.1 \
      /usr/lib/raytone-l4t/libnvidia-rmapi-tegra.so.$drv /usr/lib/raytone-l4t/libcuda.so.1; do \
      echo \"== \$l\"; ldd \$l || rc=1; ldd \$l | grep -q 'not found' && rc=1; done; exit \$rc"
  probe drm_info drm_info
  probe egl_surfaceless env __EGL_VENDOR_LIBRARY_FILENAMES=/etc/glvnd/egl_vendor.d/10_nvidia.json eglinfo -B -p surfaceless
  # eglinfo passes EGL_DEFAULT_DISPLAY for GBM, which NVIDIA's GBM platform rejects; gbmprobe uses a real device.
  probe egl_gbm_default_display eglinfo -B -p gbm
  probe vulkan vulkaninfo --summary
  grep -H . /sys/module/nvidia_drm/parameters/* /sys/module/nvidia_modeset/parameters/* > "$EVID/kms_params.txt" 2>&1 || true

  rm -f "$EVID"/egl_device_*.txt "$EVID/egl_gbm.txt" "$EVID/drm_info_json.txt" && : > "$EVID/drm-nodes.txt"
  for node in $(thor_drm_nodes); do
    echo "$(basename "$node"): $(grep -E '^(DRIVER|OF_COMPATIBLE_0|PCI_ID)=' "/sys/class/drm/$(basename "$node")/device/uevent" | tr '\n' ' ')" \
      >> "$EVID/drm-nodes.txt"
  done
  cp "$(dirname "$SCRIPT")/gbmprobe.c" "$ROOT/tmp/gbmprobe.c"
  probe gbmprobe_build bash -c 'cd /tmp && gcc -O1 -Wall -o gbmprobe gbmprobe.c $(pkg-config --cflags --libs gbm egl glesv2 libdrm)'
  for node in $(thor_drm_nodes); do
    probe "gbmprobe_$(basename "$node")" /tmp/gbmprobe "$node"
    probe "devplat_$(basename "$node")" /tmp/gbmprobe --device-platform "$node"
  done

  {
    echo "driver: $drv  glue: $GLUE"
    echo "pass: ${PASS[*]:-none}"
    echo "fail: ${FAIL[*]:-none}"
    for f in "$EVID"/gbmprobe_*D*.txt "$EVID"/gbmprobe_card*.txt; do echo "$(basename "$f" .txt): $(grep '^RESULT' "$f" || echo 'no result')"; done
    echo "nvidia in Vulkan probe: $(grep -c -i 'NVIDIA Thor' "$EVID/vulkan.txt" || true) lines"
    echo "not proven here: page flips, compositor behaviour, seat permissions, boot, module selection"
  } > "$EVID/summary.txt"
  cat "$EVID/summary.txt"
  (( ${#FAIL[@]} == 0 ))
}

inside() {
  require_namespace
  setup_root
  setup_packages "${PROBE_PKGS[@]}"
  setup_l4t
  add_gpu_nodes
  probes_0a
}

enter_namespace() { # enter_namespace STAGE : rerun this file's STAGE as PID 1 of fresh mount/PID namespaces
  sudo unshare --mount --pid --fork --propagation private -- \
    env RAYTONE_NS=1 WORK="$WORK" EVID="$EVID" GLUE="$GLUE" PKG_MIRROR="${PKG_MIRROR:-}" bash "$1" "$2"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  case ${1:-all} in
    inside) inside ;;
    all)
      check_work
      fetch_rootfs
      host_facts
      rc=0
      enter_namespace "$SCRIPT" inside || rc=$?
      sudo chown -R "$(id -u):$(id -g)" "$EVID"
      exit $rc
      ;;
    *) echo "usage: $0 [all]" >&2; exit 2 ;;
  esac
fi
