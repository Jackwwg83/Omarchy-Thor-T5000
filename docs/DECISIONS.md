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

## 2026-09-24 — Slice 1a: no unattended reboot (consult points 3 and 4)

Codex reviewed the format/GRUB/reboot runbook ([raw](reviews/2026-09-24-codex-slice1a-review.md)) and advised
against running it unattended. Claude agrees; there is no disagreement to escalate.

| Finding | Decision |
| --- | --- |
| GRUB 2.14's `exit` always returns `EFI_SUCCESS`; edk2 then opens its boot manager menu instead of trying the next boot option, so the planned "hand back to the firmware" fallback would strand the machine | Dropped as a recovery path. `exit` stays only as a manual menu item |
| A failed `search` leaves `root` on the USB ESP, so `chainloader /EFI/BOOT/BOOTAA64.efi` would load the USB's own GRUB | Every entry boots only inside `if search ...; then ... boot; fi`; otherwise it reboots after a pause |
| `fallback` takes entry numbers, not ids | Rendered as a number |
| The one-shot switched `default` without checking `save_env` | `default` changes only if `save_env` succeeded; `load_env` reads only `next_entry` |
| `lsblk -l` pads columns, so the layout check would reject a correct drive | `--raw` output |
| Automount suppression was applied after the in-use checks, and not at all by the installer | Rule first, then checks; checks repeated before each destructive step |
| The removable boot file was written before the rest of the ESP was verified | `install` leaves the USB unbootable (`BOOTAA64.EFI.staged`); a separate `publish` step, taken only with someone present, verifies the ESP with `grub-script-check` and makes it bootable |
| Rendered fields were not validated | Ids, titles, UUIDs, paths and kernel arguments validated before rendering |
| "No NVMe writes" was read as covering the tools root and JetPack's own operation | Scope clarified: prohibited are the NVMe partition table, the NVMe ESP, JetPack's boot configuration, UEFI variables and QSPI. `~/raytone` on the NVMe is the approved work area |

Overnight, work continues on everything that needs no reboot: the fixes above (test-first), formatting
the drive, staging GRUB, repackaging L4T and installing the Arch root on the drive. Publishing the ESP
and the reboot tests (default path first, then the one-shot, then Arch) wait for an observer.

## 2026-09-24 — Slice 1b root installer (consult point 5: NVIDIA services)

Codex reviewed `install-thor-root.sh` twice ([first](reviews/2026-09-24-codex-root-review.md),
[second](reviews/2026-09-24-codex-root-review2.md)); the second verdict was "可以执行 (写入 U 盘)" with
no new blockers. The drive is written from JetPack; its first boot happens with the owner present.

| Finding | Change |
| --- | --- |
| Hooks in the chroot could see host processes through a host-PID `/proc` | Mount + PID namespaces; `sys_admin`, `sys_ptrace`, `mknod`, `kill` also dropped |
| `.sig` files could be taken for packages | Excluded |
| Login and network checked only after the drive was changed | `authorized_keys`, the password hash and an active NetworkManager profile are required before anything is written |
| All NetworkManager profiles copied | Only the host's active, file-backed profiles |
| A partial unpack would be reused | `.raytone-unpacked` marker; an Arch root without it is refused |
| No proof the result boots | Kernel in `/boot`, modules index, board config links, each unit enabled (one at a time), sudoers parse, `sshd -t`, SSH host keys |
| Fan or power service failure would go unnoticed until the dead-man timer | Thermal guard 90 s after start: reboots (back to JetPack) if nvfancontrol is not active, no thermal zone reads, or any zone is at 95 °C |
| Dead-man and boot marker depended on normal start-up | Both start from `sysinit.target` without default dependencies |
| Password hash exposure | xtrace off before it is read; passed on stdin only |

Still open (accepted for writing the drive, to be covered by the attended first boot): `/proc/sys` is shared
with the host kernel in the chroot; the hardware watchdog is configured but unproven; unmount failures in
cleanup are ignored (the namespace teardown releases them).

## 2026-09-25 — Slice 1b boot configuration (consult point 4, before the first Arch boot)

Codex reviewed the Arch boot entries, the rendered `grub.cfg`, the kernel provenance note and both installers
([raw](reviews/2026-09-25-codex-boot1b-review.md)). Verdict: "不建议执行", with four minimal changes. Claude
agrees with every finding. One of its inferences was checked against new evidence rather than adopted as is
(item 5). There is no disagreement to escalate.

| Finding | Decision |
| --- | --- |
| `install` let grub-install write `EFI/BOOT/BOOTAA64.EFI` and renamed it afterwards: an interrupted install could leave a bootable, half-written ESP | grub-install writes into `raytone-staging/` below the ESP root, which the firmware never scans. `install` unpublishes a published drive first and refuses to finish if the firmware path exists. Tests cover a failed grub-install and an install over a published drive |
| The initramfs fallback entry can stop at mkinitcpio's emergency shell (no panic, no systemd units yet) | Entry removed. The image stays on the drive, unused |
| "The xHCI firmware is ready before `/init`, so it does not come from the initramfs" does not follow | Correct. Checked instead: JetPack's initrd carries only 2020 builds of `xusb.bin`, and the running controller reports a 2025-09-08 build that no file on disk has, so the boot firmware loads it. `CONFIG_EXTRA_FIRMWARE` is empty and `DEVTMPFS_MOUNT=y`. Booting without an initramfs is still the plan, as an attended experiment ([kernel-provenance.md](evidence/slice1b/kernel-provenance.md)) |
| UEFI variable writes were ruled out only for the install chroot | `CONFIG_EFI_VARS_PSTORE` is not set in either kernel. The drive's fstab mounts efivarfs read-only (applied by systemd-remount-fs), so the running system cannot write variables |
| Without an initramfs, `rw` skips `systemd-fsck-root` | Arch entries boot `ro`. fstab remounts the root read-write after the check |
| GPT auto-discovery on the first boots | `systemd.gpt_auto=0` on the Arch entries |
| A normal reboot that stalls, and PID 1 hangs, are not covered | `reboot.target` is forced after 5 minutes. The watchdog and the dead-man fallback get tested once with someone present (below). Automatic recovery from every failure is not promised |
| Thermal guard: a single check, run after an unbounded `nvpmodel -q`, and ordered after the services it watches | Separate script with behavioural tests. Checks every 30 s and decides before logging. Diagnostics have timeouts. Logs the fan tach. No ordering on the watched units. `Restart=on-failure` |
| Vendor-kernel compatibility was overstated; both kernels report the same `uname -r` | The note is corrected. The boot marker records `uname -v`. A boot with the vendor kernel counts as its own experiment, not as a pass for NVIDIA's kernel |
| Comparing FDTs "excluding /chosen" hides meaningful differences | Keep both raw FDTs. Normalise only known dynamic fields, and review `/chosen` separately |

Attended procedure (owner present, able to unplug the drive or cut power):
1. Re-run `install-thor-root.sh` (brings pkgrel 2 and the changes above), then `install-thor-boot.sh install` (staged).
2. `publish`, reboot, and check the default returns to JetPack: `/proc/cmdline`, `efibootmgr -v` and `nvbootctrl dump-slots-info` unchanged.
3. `arm-once jetpack-grub`, reboot. Save `/sys/firmware/fdt` and `/proc/cmdline`, then compare with the L4TLauncher boot as above.
4. `arm-once raytone-arch`, reboot, SSH in. Record:
   - `uname -r`, `uname -v`, the sha256 of the kernel
   - `/proc/cmdline`, `findmnt`, `swapon --show`
   - `lsmod`, and `dmesg` lines about symbol, version or firmware errors
   - `modinfo -n nvidia nvidia_drm`, `nvidia-smi`, `nvpmodel -q`
   - fan rpm, temperatures, `/var/lib/raytone/thermal.log`
   - watchdog: `/dev/watchdog*`, `systemctl show -p RuntimeWatchdogUSec`
   - efivarfs mounted `ro`
5. Test the dead-man once: create no `/run/raytone-keep` and let it reboot the machine at 20 minutes. It should come back to JetPack. After that, a later boot creates the keep file.
6. Only if 4 fails: `arm-once raytone-arch-jetpack-kernel`.
