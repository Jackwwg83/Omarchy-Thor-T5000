# Gate 0b evidence — 2026-09-24

The run kept here is `run-20260924-230346`, the first with the patched Hyprland
(`packages/hyprland`, 0.56.2-3.1). GDM and the user's GNOME session were stopped for it and
restored afterwards. Nobody watched the screen: the owner had granted the machine for the night.
On-screen output is therefore shown by the kernel's DRM state and by frame pacing, plus the
compositor's own screenshots; **confirmation by eye is still owed**.

Stack: Arch Linux ARM userspace in a namespace chroot on JetPack 7.2.1, L4T R39.2.1 libraries
(driver 595.78) bind-mounted read-only, Hyprland 0.56.2-3.1 (patched), aquamarine 0.15.1,
Quickshell 0.3.1, Chromium 153, seatd 0.9.3, HDMI monitor at 2560×1440.
The full Hyprland logs (9 MB each) are left on the Thor; `hyprland-*-excerpt.txt` keeps the lines
about device selection, sync and teardown. Monitor serial numbers are removed.

| Check | Status | Evidence |
| --- | --- | --- |
| Bare KMS: 600 legacy page flips in 8.62 s (74.97 Hz mode: 8.0 s plus start-up), HDMI CRTC active at 2560×1440, framebuffers rotating | real data | `kmscube-scanout.txt`, `kmscube-drm-*.txt` |
| Hyprland, both rounds: HDMI CRTC active with the compositor's framebuffer at 2560×1440 | real data | `hyprland-*-scanout.txt`, `session/hypr-*/drm-state-*.txt` |
| Native Wayland EGL client renders on "NVIDIA Thor/PCIe" (was llvmpipe before the patch) | real data | `session/hypr-*/egl-wayland-client.txt` |
| Xwayland GLX renders on "NVIDIA Thor/PCIe" (was llvmpipe) | real data | `session/hypr-*/xwayland-glxinfo.txt` |
| Hyprland advertises `renderD129` (GPU) instead of `renderD130` (display) to clients | real data | `hyprland-*-excerpt.txt` |
| Clients mapped by the compositor: foot, Chromium, GTK4 widget factory, vkcube (Vulkan), Quickshell panel | real data | `session/hypr-*/clients.json`, `screenshot-1.png` |
| Explicit sync: `linux-drm-syncobj` advertised and used by clients | real data | `wayland-info.txt`, `hyprland-*-excerpt.txt` (`New linux_syncobj`) |
| DPMS off/on through Hyprland, monitor back on | real data | `session/hypr-*/monitors-after-dpms.json`, `screenshot-2.png` |
| egl-wayland A/B: L4T 1.1.11 and Arch 1.1.22 both work; each round loaded the intended build | real data | `session/hypr-*/libs-quickshell.txt`, `glue-hashes.txt` |
| Hyprland exits with SIGSEGV after "Hyprland has reached the end" (teardown) | open | `hyprland-*-stdout.txt`; no core captured (JetPack's apport ignores the chroot) |
| kmscube atomic mode cannot import the KMS out-fence into EGL (`DrmFenceGetFromFile`) | recorded | `kmscube-atomic.txt`; not on Hyprland's path |
| Boot and firmware state unchanged across the run | real data | `state-*` files, `results.txt` |
| On-screen output confirmed by eye | **owed** | — |

Not established by Gate 0: boot from the USB drive, device-tree selection, module loading,
logind/SDDM, the Omarchy configuration itself.
