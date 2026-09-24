#!/bin/bash
# Gate 0b spike: put Hyprland on the Thor's HDMI output from the Arch probe root.
#
#   gate0b.sh prepare   no disruption: install the compositor stack, build kmscube
#   gate0b.sh run       stops GDM and the graphical session, runs kmscube and two
#                       Hyprland rounds, restores GDM
#
# `run` hands the disruptive part to a transient systemd unit with a 15-minute
# limit whose ExecStopPost starts GDM however the unit ends, so an SSH drop does
# not matter. A separate timer stops that unit and starts GDM after 20 minutes.
# Spike code (see README.md); namespace and library setup is shared with gate0a.sh.
set -euo pipefail
shopt -s nullglob
# shellcheck source=gate0a.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/gate0a.sh"
SCRIPT_0B=$(readlink -f "${BASH_SOURCE[0]}")
ASSETS=$(dirname "$SCRIPT_0B")/gate0b
EVID_BASE=$WORK/evidence/gate0b
EVID=${RUN_EVID:-$EVID_BASE}
PKGS_0B=(hyprland seatd foot xorg-xwayland mesa-utils vulkan-tools quickshell chromium grim wayland-utils
         gtk4-demos ttf-dejavu egl-wayland egl-gbm git meson ninja gcc pkgconf libdrm)
KMSCUBE_REPO=https://gitlab.freedesktop.org/mesa/kmscube.git
UNIT=raytone-gate0b
RESTORE=raytone-gdm-restore

inside_prepare() {
  require_namespace
  setup_root
  setup_packages "${PKGS_0B[@]}"
  if [[ ! -x $ROOT/usr/local/bin/kmscube ]]; then
    in_root bash -c "rm -rf /usr/local/src/kmscube && git clone --depth 1 $KMSCUBE_REPO /usr/local/src/kmscube &&
      cd /usr/local/src/kmscube && meson setup build --prefix=/usr/local && ninja -C build install"
  fi
  # Session programs look up their user; the Arch Linux ARM rootfs already names uid 1000 "alarm".
  in_root bash -c 'getent passwd 1000 >/dev/null || useradd -u 1000 -M -d /tmp/home -s /bin/bash probe'
  in_root bash -c 'git -C /usr/local/src/kmscube rev-parse HEAD' > "$EVID/kmscube-commit.txt"
  in_root bash -c '/usr/local/bin/kmscube --help 2>&1 | head -30' > "$EVID/kmscube-help.txt" || true
  in_root pacman -Q "${PKGS_0B[@]}" aquamarine glibc > "$EVID/versions.txt"
}

as_user() { # as_user TIMEOUT OUTFILE VAR=VALUE... CMD... : run in the probe root as uid 1000
  local t=$1 out=$2; shift 2
  timeout --kill-after=10 "$t" chroot --userspec=1000:1000 --groups=44,993 "$ROOT" \
    /usr/bin/env -i PATH=/usr/bin LANG=C.UTF-8 "$@" > "$out" 2>&1
}

result() { echo "$1: $2" | tee -a "$EVID/results.txt"; }

holders() { # holders NODE : PIDs with NODE open, from /proc (independent of fuser's exit codes)
  local p fd
  for p in /proc/[0-9]*; do
    for fd in "$p"/fd/*; do
      [[ $(readlink "$fd" 2>/dev/null) == "$1" ]] && { echo "${p#/proc/} $(cat "$p/comm" 2>/dev/null)"; break; }
    done
  done
  return 0
}

# Everything in this PID namespace except PID 1 (this shell): the previous round's leftovers.
kill_round() { kill -TERM -1 2>/dev/null || true; sleep 2; kill -KILL -1 2>/dev/null || true; sleep 1; }

# Runs as PID 1 of the private namespaces, after host_run stopped GDM and freed the display.
inside_run() {
  require_namespace
  setup_root
  setup_l4t
  add_gpu_nodes
  local n card rc failed=0
  # Device nodes stay usable on a read-only bind; seatd opens input devices for Hyprland.
  [[ -d /dev/input ]] && bind_ro /dev/input "$ROOT/dev/input"
  for n in /dev/tty[0-9] /dev/tty[0-9][0-9]; do bind_node "$n" "$ROOT$n"; done
  card=$(display_card)
  [[ -n $card ]] || { result display-node "none found"; exit 1; }
  result display-node "$card"

  mkdir -p "$ROOT/tmp/raytone-0b" "$ROOT/evidence" "$EVID/session"
  mkdir -p "$ROOT/tmp/.X11-unix" && chmod 1777 "$ROOT/tmp/.X11-unix"
  cp "$ASSETS"/* "$ROOT/tmp/raytone-0b/" && chmod 0755 "$ROOT/tmp/raytone-0b/client-tests.sh"
  chown 1000:1000 "$EVID/session" && mount --bind "$EVID/session" "$ROOT/evidence"
  sha256sum "$L4T_NV/libnvidia-egl-wayland.so.1" "$ROOT$ARCH_EGL_WAYLAND" "$L4T_NV/libnvidia-egl-gbm.so.1" \
    > "$EVID/glue-hashes.txt" 2>&1 || true

  # 1. Bare KMS, legacy page flips: kmscube waits for each flip event, so 600 frames should take
  # about 8 s at the 74.97 Hz preferred mode. -N: kmscube otherwise polls stdin every frame and quits
  # on the first readable byte; under systemd stdin is /dev/null, always readable.
  rc=0
  local t0 t1 elapsed alive=0 scan i samples=()
  t0=$(date +%s.%N)
  as_user 40 "$EVID/kmscube.txt" __EGL_EXTERNAL_PLATFORM_CONFIG_DIRS="${GLUE_DIR[l4t]}" \
    /usr/local/bin/kmscube -N -c 600 -D "$card" &
  local kms_pid=$!
  # Without an observer, the kernel's view is the evidence: active CRTC, mode, framebuffers in rotation.
  sleep 3
  for i in 1 2 3 4 5 6; do
    as_user 3 "$EVID/kmscube-drm-$i.txt" drm_info "$card" || true
    samples+=("$EVID/kmscube-drm-$i.txt")
    sleep 0.2
  done
  kill -0 "$kms_pid" 2>/dev/null && alive=1
  wait "$kms_pid" || rc=$?
  t1=$(date +%s.%N)
  elapsed=$(awk -v a="$t0" -v b="$t1" 'BEGIN { printf "%.2f", b - a }')
  scan=$(python3 "$(dirname "$SCRIPT_0B")/drm_scanout.py" "${samples[@]}" --require-flip |
         tee "$EVID/kmscube-scanout.txt" | tail -1) || true
  echo "600 frames in ${elapsed}s (exit $rc)" >> "$EVID/kmscube-scanout.txt"
  if [[ $rc == 0 && $alive == 1 && $scan == "SCANOUT PASS" ]] &&
     awk -v e="$elapsed" 'BEGIN { exit !(e >= 7 && e <= 14) }'; then
    result kmscube "600 page-flipped frames in ${elapsed}s (paced by the display), HDMI CRTC active at 2560x1440, framebuffers rotating"
  else
    result kmscube "FAIL exit $rc, alive while sampled: $alive, 600 frames in ${elapsed}s, $scan"; failed=1
  fi
  kill_round
  # Atomic with fences, informational: kmscube imports the KMS out-fence into EGL, which failed before.
  rc=0
  as_user 20 "$EVID/kmscube-atomic.txt" __EGL_EXTERNAL_PLATFORM_CONFIG_DIRS="${GLUE_DIR[l4t]}" \
    /usr/local/bin/kmscube -A -N -c 300 -D "$card" || rc=$?
  result kmscube-atomic-informational "exit $rc: $(grep -m1 -E 'Assertion|failed' "$EVID/kmscube-atomic.txt" || echo 'no error printed')"
  kill_round

  # 2. Hyprland rounds: same egl-gbm, egl-wayland from L4T (with a manual window) then from Arch.
  local glue manual t home xdg seatd_pid ready session_user
  session_user=$(chroot "$ROOT" getent passwd 1000 | cut -d: -f1)
  result session-user "uid 1000 is '$session_user' in the probe root"
  for glue in l4t arch; do
    manual=0 t=240
    [[ $glue == l4t && ${RAYTONE_MANUAL:-0} == 1 ]] && manual=1 t=330
    home=/tmp/home-$glue xdg=/tmp/xdg-$glue
    mkdir -p "$ROOT$home" "$ROOT$xdg" && chown 1000:1000 "$ROOT$home" "$ROOT$xdg" && chmod 0700 "$ROOT$xdg"
    echo "active VT before $glue: $(cat /sys/class/tty/tty0/active)" >> "$EVID/vt.txt"
    rm -f "$ROOT/run/seatd.sock" "$ROOT/tmp/seatd-ready"
    mkfifo "$ROOT/tmp/seatd-ready"
    exec 4<>"$ROOT/tmp/seatd-ready"
    setpriv --bounding-set -sys_module,-sys_rawio,-bpf,-perfmon,-sys_boot,-sys_time -- \
      chroot "$ROOT" /usr/bin/seatd -u "$session_user" -l info -n 3 3>"$ROOT/tmp/seatd-ready" > "$EVID/seatd-$glue.txt" 2>&1 &
    seatd_pid=$!
    ready=0
    read -r -t 10 -u 4 _ && ready=1
    exec 4<&-
    if (( ! ready )) || ! kill -0 "$seatd_pid" 2>/dev/null || [[ ! -S $ROOT/run/seatd.sock ]]; then
      result "hyprland-$glue" "FAIL seatd not ready (seatd-$glue.txt)"; failed=1; kill_round; continue
    fi
    rc=0
    as_user "$t" "$EVID/hyprland-$glue-stdout.txt" HOME="$home" XDG_RUNTIME_DIR="$xdg" \
      LIBSEAT_BACKEND=seatd SEATD_SOCK=/run/seatd.sock AQ_DRM_DEVICES="$card" AQ_TRACE=1 HYPRLAND_TRACE=1 \
      __EGL_EXTERNAL_PLATFORM_CONFIG_DIRS="${GLUE_DIR[$glue]}" RAYTONE_GLUE="$glue" RAYTONE_MANUAL="$manual" \
      Hyprland --config /tmp/raytone-0b/hyprland.lua || rc=$?
    echo "active VT after $glue: $(cat /sys/class/tty/tty0/active)" >> "$EVID/vt.txt"
    cp "$ROOT$xdg"/hypr/*/hyprland.log "$EVID/hyprland-$glue.log" 2>/dev/null || true
    cp -r "$ROOT$home/.cache/hyprland" "$EVID/hyprland-$glue-crash" 2>/dev/null || true
    local sess=$EVID/session/hypr-$glue required_fail
    required_fail=$(cat "$sess/required-failures" 2>/dev/null || echo missing)
    scan=$(python3 "$(dirname "$SCRIPT_0B")/drm_scanout.py" "$sess"/drm-state-*.txt \
           2>&1 | tee "$EVID/hyprland-$glue-scanout.txt" | tail -1) || true
    if [[ $rc -eq 0 && -f $sess/done && $required_fail == 0 && $scan == "SCANOUT PASS" ]]; then
      result "hyprland-$glue" "client tests passed, kernel shows Hyprland's framebuffer on the HDMI CRTC at 2560x1440, session exited cleanly"
    else
      result "hyprland-$glue" "FAIL exit $rc, client tests $([[ -f $sess/done ]] && echo finished || echo 'did not finish'), required failures: $required_fail, $scan"
      failed=1
    fi
    result "hyprland-$glue-informational" "$(cat "$sess/informational" 2>/dev/null || echo 'none recorded')"
    kill_round
    rm -f "$ROOT/run/seatd.sock"
  done
  return $failed
}

record_state() { # record_state LABEL : read-only snapshot of boot and firmware state, one file per query
  local q rc
  declare -A cmd=([efibootmgr]="efibootmgr -v" [slots]="nvbootctrl dump-slots-info" [bios]="cat /sys/class/dmi/id/bios_version")
  for q in "${!cmd[@]}"; do
    rc=0
    ${cmd[$q]} > "$EVID/state-$1-$q.txt" 2>&1 || rc=$?
    echo "$rc" > "$EVID/state-$1-$q.rc"
  done
}

compare_state() {
  local q
  for q in efibootmgr slots bios; do
    if [[ $(cat "$EVID/state-before-$q.rc") == 0 && $(cat "$EVID/state-after-$q.rc") == 0 ]]; then
      if cmp -s "$EVID/state-before-$q.txt" "$EVID/state-after-$q.txt"; then result "state-$q" unchanged
      else result "state-$q" "CHANGED"; fi
    else
      result "state-$q" "unverified (query exit $(cat "$EVID/state-before-$q.rc")/$(cat "$EVID/state-after-$q.rc"))"
    fi
  done
}

restore_gdm() { systemctl --no-block start gdm || true; }

# Runs as root in the transient systemd unit.
host_run() {
  check_work
  mkdir -p "$EVID"
  exec > >(tee -a "$EVID/host-run.log") 2>&1
  trap restore_gdm EXIT
  local start rc=0 card s held=1
  start=$(date '+%Y-%m-%d %H:%M:%S')
  echo "gate0b host_run start $start, evidence $EVID"
  systemctl stop "$RESTORE.timer" "$RESTORE.service" 2>/dev/null || true
  systemd-run --unit "$RESTORE" --collect --on-active=20min /usr/bin/bash -c "systemctl stop $UNIT; systemctl start gdm"
  card=$(display_card)
  grep -q '^connected' /sys/class/drm/"$(basename "$card")"-HDMI-A-*/status ||
    { result preflight "no HDMI monitor connected on $card; GDM left running"; systemctl stop "$RESTORE.timer"; exit 1; }
  record_state before

  # Freeze JetPack's boot loader and kernel packages for v1; record which holds are new.
  apt-mark showhold | sort > "$EVID/apt-holds-before.txt"
  local hold=()
  mapfile -t hold < <(dpkg-query -W -f='${db:Status-Abbrev}\t${Package}\n' 'nvidia-l4t-bootloader' 'nvidia-l4t-kernel*' |
                      awk -F'\t' '$1 ~ /^.i/ {print $2}')
  apt-mark hold "${hold[@]}"
  apt-mark showhold | sort | comm -13 "$EVID/apt-holds-before.txt" - > "$EVID/apt-holds-added.txt"
  result apt-hold "$(wc -l < "$EVID/apt-holds-added.txt") packages newly held (apt-holds-added.txt)"

  systemctl stop gdm
  # Stopping GDM does not always end the user's X11/Wayland session; end it so it releases the display.
  for s in $(loginctl list-sessions --no-legend | awk '{print $1}'); do
    case $(loginctl show-session "$s" -p Type --value) in x11|wayland) loginctl terminate-session "$s" ;; esac
  done
  for _ in $(seq 20); do [[ -z $(holders "$card") ]] && { held=0; break; }; sleep 1; done
  holders "$card" > "$EVID/display-holders.txt"
  if (( held )); then
    result preflight "display node still in use after 20 s (display-holders.txt); tests skipped"
    rc=3
  else
    unshare --mount --pid --fork --propagation private -- \
      env RAYTONE_NS=1 WORK="$WORK" RUN_EVID="$EVID" RAYTONE_MANUAL="${RAYTONE_MANUAL:-0}" \
        bash "$SCRIPT_0B" inside-run || rc=$?
  fi

  local ok=0
  for _ in 1 2 3; do
    systemctl start gdm || true
    sleep 10
    systemctl is-active --quiet gdm && [[ -n $(holders "$card") ]] && { ok=1; break; }
  done
  holders "$card" > "$EVID/display-holders-after.txt"
  if (( ok )); then
    result gdm-restored "active, display held by: $(awk '{print $2}' "$EVID/display-holders-after.txt" | sort -u | tr '\n' ' ')"
    systemctl stop "$RESTORE.timer" 2>/dev/null || true
  else
    result gdm-restored "FAIL: not active or not holding the display; the 20-minute restore timer stays armed"
    rc=4
  fi
  record_state after
  compare_state
  grep -q CHANGED "$EVID/results.txt" && rc=5
  journalctl -k --since "$start" --no-pager | grep -E -i 'NVRM|Xid|nvidia|drm|hdmi' > "$EVID/kernel.txt" || true
  chown -R 1000:1000 "$EVID"
  echo "gate0b host_run done, rc=$rc"
  return $rc
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  case ${1:-} in
    inside-prepare) inside_prepare ;;
    inside-run) inside_run ;;
    host-run) host_run ;;
    prepare)
      check_work
      mkdir -p "$EVID"
      enter_namespace "$SCRIPT_0B" inside-prepare
      sudo chown -R "$(id -u):$(id -g)" "$EVID"
      ;;
    run)
      check_work
      [[ -x $ROOT/usr/local/bin/kmscube ]] || { echo "run '$0 prepare' first" >&2; exit 1; }
      ! systemctl is-active --quiet "$UNIT" || { echo "$UNIT is already running" >&2; exit 1; }
      run_evid=$EVID_BASE/run-$(date +%Y%m%d-%H%M%S)
      sudo systemd-run --unit "$UNIT" --collect -p RuntimeMaxSec=900 -p TimeoutStopSec=30 \
        -p "ExecStopPost=/usr/bin/systemctl --no-block start gdm" \
        --setenv=WORK="$WORK" --setenv=RUN_EVID="$run_evid" --setenv=RAYTONE_MANUAL="${RAYTONE_MANUAL:-0}" \
        bash "$SCRIPT_0B" host-run
      echo "started $UNIT, evidence in $run_evid; follow with: journalctl -fu $UNIT"
      ;;
    *) echo "usage: $0 prepare|run" >&2; exit 2 ;;
  esac
fi
