# Decisions

Each entry records a decision, who reviewed it, and what was done with the review.
Codex consultations run as `codex exec -s read-only`. When Codex and Claude disagree, work stops
until the project owner decides.

## 2026-09-24 — Architecture and v1 plan

Reviewed by Codex (12 findings, [raw output](reviews/2026-09-24-codex-plan-review.md)) and by an
independent Claude plan reviewer (15 findings). The approved result is [PLAN.md](PLAN.md).

| Decision | Reason | Source |
| --- | --- | --- |
| Use NVIDIA's L4T R39.2.1 binaries (kernel, out-of-tree and OpenRM modules, firmware, userspace) repackaged for Arch; no kernel build in v1 | Only stack with Thor GPU and display support; mainline has neither | Both |
| Prove the kernel/module/userspace set is one build from `dpkg-query -S`, `apt-cache policy` and `modinfo -F vermagic` on the machine | Mixed builds fail with bad module format or load the wrong `nvidia.ko` | Codex |
| Keep NVIDIA's library directories; allowlist what enters the loader path | Hard-coded paths, container CSV files and NGC images expect them; L4T copies of libgbm, libEGL, libwayland, libdrm or libvulkan must not shadow Arch's | Both |
| Keep a ledger of every L4T maintainer script and turn each line into a package step or a recorded exclusion | Unpacking `data.tar` alone loses board config links, udev permissions and loader config | Both |
| Boot from the USB drive with GRUB `--removable --no-nvram`; read-only efivars in every chroot | Without `--no-nvram`, `grub-install` in a chroot rewrites the running board's BootOrder | Plan reviewer |
| No `devicetree` command in GRUB; keep the firmware device tree | GRUB's `devicetree` skips the UEFI overlay step; JetPack itself boots without an FDT line | Plan reviewer |
| Split the first boot into 1a (USB GRUB boots JetPack's own kernel and rootfs, compare `/sys/firmware/fdt` and `/proc/cmdline`) and 1b (Arch) | Separates the boot path from the Arch root; the fallback DT choice is otherwise unverified | Plan reviewer |
| Ship a minimal initramfs, verify on a cold boot | Three built-in options are not proof that the USB root is found without one | Both |
| Prohibited-content test over every built package (bootloader, capsule, OTA and first-boot items) | Unpacked units can update QSPI or UEFI state that unplugging cannot undo | Both |
| `apt-mark hold nvidia-l4t-bootloader 'nvidia-l4t-kernel*'` on JetPack for v1 | A JetPack upgrade could move QSPI firmware past what the frozen R39.2.1 kernel supports | Plan reviewer |
| Gate 0 in two parts: 0a without stopping GDM (host L4T libraries bind-mounted read-only), 0b on screen with a timed GDM restart | Removes the display risk before any disk is written, with the least disruption | Both |
| Hyprland runs as a normal user under `seatd`; `AQ_DRM_DEVICES` uses a stable udev link | Running as root hides the permission problems SDDM will hit; card numbers change between boots | Plan reviewer |
| Package names use the `raytone-thor-` prefix; graphics declares `provides`/`conflicts` against `nvidia-utils` and `nvidia-open-dkms` | Keeps yay from replacing them from the AUR and keeps Arch's 610 driver out | Plan reviewer |
| v1 is HDMI only; sleep targets masked; OOM scores for Ollama and Docker | NVIDIA known issues 6241469 (DP over USB-C), 5525468 (suspend), 5699079 (large CUDA allocations) | Plan reviewer |
| Rewrite the build script for a chroot instead of reusing omarchy-spark's `clean-build.sh` | It needs Docker, uses a floating `latest` image and continues after a failed package | Codex |

### Disagreements settled by experiment

| Question | Codex | Plan reviewer | Resolution |
| --- | --- | --- | --- |
| Keep the boot loader's `bl_prof_*` arguments in the GRUB command line? | Drop them and verify | Copy `/proc/cmdline` verbatim | Slice 1a boots JetPack through GRUB without them and compares `/proc/cmdline` and `dmesg` |
| Which egl-wayland first? | L4T's 1.1.11, then compare | Arch's newer build (explicit sync) | Gate 0b tests both |

## 2026-09-24 — Gate 0a probe script (first sudo on the Thor)

Codex reviewed the first draft of `spikes/gate0/gate0a.sh` and judged it not safe to run as written.
All eight findings were applied before the first run:

| Finding | Change |
| --- | --- |
| The chroot got the host's whole writable `/dev` and `/run/udev` | Private tmpfs `/dev` with basic nodes only; GPU/display nodes added for the probe step; only `/run/udev/data`, read-only |
| Fresh `/proc` still showed host PIDs; root kept every capability | Mount + PID namespaces; package steps run with `sys_module`, `sys_admin`, `sys_rawio`, `mknod` and similar dropped from the bounding set; probes run as uid 1000 |
| `inside` could be called directly, and leftover agents could keep the namespace alive | `inside` refuses unless it is PID 1 of the new namespace; namespace teardown kills leftovers |
| `cp -L` onto the rootfs `resolv.conf` could follow a symlink onto the host (real bug) | Remove the link inside the root, then write a plain file; `WORK` must be a symlink-free path under `/home` |
| `cd` in the download step broke a relative `$0` (real bug); partial unpacks were reused | Absolute script path saved first; download in a subshell; unpack to `.partial` then rename; xattrs and ACLs kept |
| pacman 7 sandbox and stale keyrings not handled | Refresh `archlinuxarm-keyring` first; `DisableSandbox` only if the sandbox is the failure |
| Deny-list for L4T libraries, fixed driver version, Mesa fallback could pass as NVIDIA | NVIDIA-name allowlist with excluded files logged; duplicate names abort; driver version read from `modinfo`; NVIDIA-only and default EGL runs recorded separately |
| Probe failures did not change the exit status | Per-probe exit codes, 90 s timeouts, summary with pass/fail, non-zero exit on any failure |

## 2026-09-24 — Gate 0a result and Gate 0b probe (consult point 2)

Gate 0a showed the Orin failure mode (FBO on an imported dma-buf) does not occur on Thor; see
[evidence/gate0a](evidence/gate0a/README.md). Two design changes followed: the EGL platform glue
(egl-wayland, egl-gbm) is registered by absolute path in a directory chosen per run through
`__EGL_EXTERNAL_PLATFORM_CONFIG_DIRS`, instead of by soname in the shared directory (which also collided
with Arch's `egl-wayland`/`egl-gbm` package files); and gate0a.sh became a library for gate0b.sh.

Codex reviewed gate0b.sh three times before the first run ("not safe to run" twice, then two remaining
items). Everything below was applied:

| Finding | Change |
| --- | --- |
| Dead-man timer only started GDM; no bound on the test | Transient unit with `RuntimeMaxSec=900` and `ExecStopPost` that starts GDM however the unit ends; the 20-minute timer stops the unit first |
| seatd socket group came from the chroot's `video`, not the host GID the session runs with (would fail Hyprland for a harness reason) | `seatd -u probe`; readiness through `-n` on a FIFO plus liveness and socket checks |
| kmscube did not use the glue under test | kmscube gets the L4T glue directory explicitly |
| egl-wayland A/B also changed egl-gbm | Both rounds keep L4T egl-gbm; only egl-wayland differs; loaded libraries hashed per process |
| Rounds shared PID space, HOME and browser profile | Every process in the namespace except PID 1 is killed between rounds; separate HOME, runtime dir and profile |
| Failures, timeouts and invalid screenshots did not change the result | Required checks per round, completion marker, per-step exit codes, `--kill-after` on every bound |
| Query failures in the boot-state snapshot compared as "unchanged" | Per-query exit codes; only two successful queries are compared, otherwise "unverified" |
| `apt-mark hold` without a record of which holds were new | `apt-holds-added.txt` from a before/after set difference |
| GDM restore failure swallowed and the timer disarmed | Three bounded restore attempts; on failure the unit exits non-zero and the timer stays armed |
| `fuser` exit codes read as "display released" | Holders found by scanning `/proc/*/fd` |
| No observer: on-screen output was only asserted | Scanout judged from two DRM state samples (HDMI CRTC active, primary plane framebuffer at 2560×1440, framebuffer changing for kmscube) by `drm_scanout.py`; still to be confirmed by eye |

Found by Claude in the same pass: stopping GDM leaves the user's GNOME Xorg session (it held `card3`),
so the run also terminates X11/Wayland sessions and waits until nothing holds the display node.

The owner granted autonomous use of the machine overnight, so the run went ahead without an observer.

## 2026-09-24 — Gate 0b findings (overnight, no observer)

Runs are under `~/raytone/evidence/gate0b/run-*` on the Thor. Boot and firmware state (efibootmgr,
boot slots, BIOS version) compared unchanged after every run; GDM came back each time.

| Finding | Evidence | Consequence |
| --- | --- | --- |
| Stock Hyprland 0.56.2 starts on Thor from the Arch userspace, scans out 2560×1440 on the HDMI CRTC (kernel state), advertises `linux-drm-syncobj` (explicit sync), and handles DPMS off/on | `hyprland-*-scanout.txt`, `client-tests.log` | The compositor path works; the Orin blocker does not apply |
| Wayland EGL and Xwayland GLX clients fall back to llvmpipe | `egl-wayland-client.txt`, `xwayland-glxinfo.txt` | Unusable desktop without a fix |
| Cause: Thor exposes display (nvidia-drm on tegra264-display, `card3`/`renderD130`) and GPU (nvidia-drm on PCI, `card2`/`renderD129`) as two DRM devices. Aquamarine picks the display device's own render node; Hyprland advertises it as the dma-buf main device and in `wl_drm`. NVIDIA EGL cannot initialise on `renderD130` (Gate 0a), so clients drop to Mesa | Hyprland log: `Creating CDRMRenderer on gpu /dev/dri/renderD130`, `Using RENDERNODEFD` | Needs a code change, not configuration: neither aquamarine nor Hyprland has an override |
| Aliasing `renderD130` to the GPU node inside the probe root breaks NVIDIA's own EGL device enumeration (kmscube cannot initialise, Hyprland aborts) | run-20260924-225204 | Device-node tricks are ruled out for the real system too |
| Only advertising a different render node from aquamarine would make Hyprland's `eglDeviceFromDRMFD` pick EGL device 2 (`card2`), which fails to initialise | Hyprland `OpenGL.cpp` matching by primary node; Gate 0a devices 1–3 fail | Patch Hyprland, not aquamarine |
| Fix: Hyprland advertises the render node the chosen EGL device reports (`EGL_DRM_RENDER_NODE_FILE_EXT`, `renderD129` for device 0) in linux-dmabuf feedback and `wl_drm`, when it differs from its own; no change on single-device GPUs | `patches/hyprland-0.56.2-egl-render-node.patch`, `packages/hyprland` (Arch recipe, pkgrel 3.1) | Validated in run-20260924-230346: clients render on NVIDIA Thor; see [evidence/gate0b](evidence/gate0b/README.md) |
| kmscube polls stdin each frame and quits when it is readable; under systemd stdin is `/dev/null` | "user interrupted!" after the first frame | Harness fix: `-N` |
| kmscube's atomic mode cannot import the KMS out-fence into EGL (`create_fence: Assertion`) | `kmscube-atomic.txt` | Not on Hyprland's path (it passed); recorded, frame pacing measured with legacy flips |
| Hyprland exits with SIGSEGV after `hl.dsp.exit()` in both rounds | exit 139 | To investigate from the crash report |
| An NVRM assertion (`NV0080_CTRL_CMD_INTERNAL_MEMSYS_SET_ZBC_REFERENCED`, object not found) appears once per run | `kernel.txt` | Non-fatal; noted |

**Gate 0b verdict (2026-09-24, 23:05 SGT):** pass on kernel and compositor evidence, with the patched
Hyprland; eye confirmation owed to the owner. Open: Hyprland's SIGSEGV at exit. Worth offering the
render-node patch upstream (hyprwm/Hyprland), since it only acts when the EGL device reports a
render node different from the compositor's.
