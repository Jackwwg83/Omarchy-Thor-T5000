#!/bin/bash
# Started by Hyprland (hyprland.start) inside a Gate 0b round. Launches the client
# set, records what the compositor reports with a bound on every step, writes a
# completion marker, then exits the session.
E=/evidence/hypr-${RAYTONE_GLUE:-unknown}
rm -rf "$E" && mkdir -p "$E"
exec >> "$E/client-tests.log" 2>&1
step() { echo "[$(date +%T)] $*"; }
t() { # t OUTFILE SECONDS CMD... : bounded step with its exit code logged
  local out=$1 secs=$2 rc=0; shift 2
  timeout --kill-after=5 "$secs" "$@" > "$E/$out" 2>&1 || rc=$?
  step "$out rc=$rc"
  return $rc
}
REQ_FAIL=0
require() { # require DESCRIPTION CMD... : a check the round must pass
  if "${@:2}"; then step "REQUIRED ok: $1"; else step "REQUIRED FAIL: $1"; REQ_FAIL=$((REQ_FAIL + 1)); fi
}
libs_of() { # libs_of NAME PID : graphics libraries a process actually mapped, with hashes
  [[ -n $2 && -r /proc/$2/maps ]] || { step "$1: no process"; return; }
  grep -oE '/[^ ]+\.so[^ ]*' "/proc/$2/maps" | sort -u | grep -E 'EGL|gbm|nvidia|egl|vulkan|GLX' |
    while read -r f; do echo "$(sha256sum "$f" | cut -c1-16)  $f"; done > "$E/libs-$1.txt"
}
png_ok() { [[ -s $1 && $(head -c 8 "$1" | od -An -tx1 | tr -d ' \n') == 89504e470d0a1a0a ]]; }

step "round up, glue=$RAYTONE_GLUE manual=$RAYTONE_MANUAL"
sleep 3
t hyprctl-version.txt 10 hyprctl version
t monitors.json 10 hyprctl monitors -j
require "monitor reported at 2560x1440" grep -q '"width": 2560' "$E/monitors.json"
t systeminfo.txt 10 hyprctl systeminfo
t wayland-info.txt 15 wayland-info
step "syncobj global advertised: $(grep -c linux_drm_syncobj "$E/wayland-info.txt")"

foot --title raytone-foot bash -c "echo 'RaytoneOS Gate 0b  glue=$RAYTONE_GLUE'; echo; \
  eglinfo -B -p wayland 2>&1 | head -12; echo; echo 'type here to test the keyboard'; exec bash" &
sleep 2
t egl-wayland-client.txt 15 eglinfo -B -p wayland
t xwayland-glxinfo.txt 20 glxinfo -B
step "native EGL client renderer: $(grep -m1 -i 'renderer' "$E/egl-wayland-client.txt")"
step "Xwayland GLX renderer: $(grep -m1 'OpenGL renderer' "$E/xwayland-glxinfo.txt")"
require "native Wayland EGL client on NVIDIA" grep -q -i 'renderer.*NVIDIA' "$E/egl-wayland-client.txt"
require "Xwayland GLX on NVIDIA" grep -q 'OpenGL renderer.*NVIDIA' "$E/xwayland-glxinfo.txt"

timeout 25 vkcube --wsi wayland > "$E/vkcube.txt" 2>&1 &
quickshell -p /tmp/raytone-0b/shell.qml > "$E/quickshell.txt" 2>&1 &
timeout 60 gtk4-widget-factory > "$E/gtk4.txt" 2>&1 &
chromium --ozone-platform=wayland --no-sandbox --no-first-run --user-data-dir="$HOME/chromium" \
  chrome://gpu > "$E/chromium.txt" 2>&1 &
sleep 18

t screenshot-1.log 15 grim "$E/screenshot-1.png"
require "screenshot-1 is a PNG" png_ok "$E/screenshot-1.png"
t clients.json 10 hyprctl clients -j
# Kernel view of the scanout while the compositor runs: active CRTC, mode, FB_ID changing between reads.
t drm-state-1.txt 10 drm_info "$AQ_DRM_DEVICES"
sleep 1
t drm-state-2.txt 10 drm_info "$AQ_DRM_DEVICES"
libs_of hyprland "$(pidof -s Hyprland)"
libs_of quickshell "$(pgrep -n -x quickshell)"
libs_of chromium-gpu "$(pgrep -n -f -- '--type=gpu-process')"

# Informational checks: reported in the round's results, not required for it to pass.
info() { echo "$*" >> "$E/informational"; step "INFO $*"; }
off=0 on=0
t dpms-off.txt 10 hyprctl dispatch 'hl.dsp.dpms({ action = "off" })' || off=$?
sleep 4
t dpms-on.txt 10 hyprctl dispatch 'hl.dsp.dpms({ action = "on" })' || on=$?
sleep 4
info "dpms dispatch off/on exit $off/$on"
info "wayland syncobj global advertised: $(grep -c linux_drm_syncobj "$E/wayland-info.txt")"
info "first FB_ID line changed between drm samples: $([[ $(grep -m1 '"FB_ID"' "$E/drm-state-1.txt") != $(grep -m1 '"FB_ID"' "$E/drm-state-2.txt") ]] && echo yes || echo no)"
t screenshot-2.log 15 grim "$E/screenshot-2.png"
require "screenshot-2 after DPMS is a PNG" png_ok "$E/screenshot-2.png"
t monitors-after-dpms.json 10 hyprctl monitors -j
info "dpmsStatus after dpms on: $(grep -o '"dpmsStatus": [a-z]*' "$E/monitors-after-dpms.json")"

if [[ $RAYTONE_MANUAL == 1 ]]; then
  step "manual window: 75 s"
  sleep 75
fi
step "round finished, required failures: $REQ_FAIL"
echo "$REQ_FAIL" > "$E/required-failures"
date > "$E/done"
pkill -f chromium
timeout 10 hyprctl dispatch 'hl.dsp.exit()'
