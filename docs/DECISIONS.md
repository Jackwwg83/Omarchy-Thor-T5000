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
| UEFI variable writes were ruled out only for the install chroot | `CONFIG_EFI_VARS_PSTORE` is not set in either kernel. The drive's fstab mounts efivarfs read-only, applied by systemd-remount-fs. (Narrowed after the re-review, see below: before that remount, PID 1 and early units can still write) |
| Without an initramfs, `rw` skips `systemd-fsck-root` | Arch entries boot `ro`. fstab remounts the root read-write after the check |
| GPT auto-discovery on the first boots | `systemd.gpt_auto=0` on the Arch entries |
| A normal reboot that stalls, and PID 1 hangs, are not covered | `reboot.target` is forced after 5 minutes. The watchdog and the dead-man fallback get tested once with someone present (below). Automatic recovery from every failure is not promised |
| Thermal guard: a single check, run after an unbounded `nvpmodel -q`, and ordered after the services it watches | Separate script with behavioural tests. Checks every 30 s and decides before logging. Diagnostics have timeouts. Logs the fan tach. No ordering on the watched units. `Restart=on-failure` |
| Vendor-kernel compatibility was overstated; both kernels report the same `uname -r` | The note is corrected. The boot marker records `uname -v`. A boot with the vendor kernel counts as its own experiment, not as a pass for NVIDIA's kernel |
| Comparing FDTs "excluding /chosen" hides meaningful differences | Keep both raw FDTs. Normalise only known dynamic fields, and review `/chosen` separately |

### Re-review of the fixes

Codex re-reviewed `3740f65..71f8d5c` ([raw](reviews/2026-09-25-codex-boot1b-review2.md)). Its verdict was
"不建议执行", with three minimal changes. Claude agrees with all three, and found a fourth problem itself.

| Finding | Decision |
| --- | --- |
| efivarfs is writable until systemd-remount-fs runs. `systemd-hibernate-clear.service` (sysinit, not ordered after remount-fs) can delete `HibernateLocation` in that window | The guarantee is narrowed: nothing *left enabled* writes UEFI variables before the remount. Masked on the drive: `systemd-hibernate-clear`, `systemd-boot-random-seed`, `systemd-boot-clear-sysfail` and `systemd-boot-update`. JetPack has none of the variables these units test for (no `HibernateLocation`, `Loader*` or `Stub*` among its 56), so their conditions are false anyway. PID 1's own lock-down of `LoaderSystemToken` changes inode flags only, and that variable does not exist here. A read-only efivarfs from PID 1 onwards would need an initramfs or an init wrapper; not done for v1 |
| (Claude) The Thor has an fTPM (`/dev/tpm0`). systemd 261's `tpm2-setup` creates a persistent SRK, and the `pcr*` units include NV-index PCRs: writes to TPM NV storage | Masked: `systemd-tpm2-setup{-early,}` and `systemd-pcr{machine,nvdone,phase,phase-sysinit,product}`. Their `ConditionSecurity=measured-os` should be false under GRUB, but that is not relied on |
| (Claude) The unpacked rootfs has an empty `/etc/machine-id` and no `vconsole.conf`. Claimed at first: the first boot would be a systemd "first boot", with `systemd-firstboot --prompt-keymap-auto` waiting at the HDMI console and preset-all running. **Corrected in round 3:** in systemd 261 an empty file is not a first boot (only a missing file or `uninitialized` is); an empty ID is generated at every boot and not kept | The installer runs `systemd-machine-id-setup`, writes `KEYMAP=us` and masks `systemd-firstboot`. `systemd-repart` and the sleep targets are masked too (plan: JetPack known issue 5525468). Every mask is verified |
| Thermal guard: the service query and hwmon reads came before the temperature decision and had no hard limit, and a refused reboot ended the guard with exit 0 | Temperatures are judged first. Every command runs as `timeout -k 2 …`. A refused reboot becomes `--force`, then `--force --force`. The guard keeps checking after a request. Tests cover a query that ignores TERM, refused requests, and heating inside one process. The fan tach is logged only |
| A failed install left the old `.staged` loader publishable | `install` removes `boot/grub/raytone-ready` first and writes it last, with the sha256 of the loader, `grub.cfg` and the modules. `publish` verifies that record and consumes it |
| The prefix check was a substring match | The check now matches the NUL-terminated string exactly. It passes on the real staged loader. It is a regression alarm, not proof that the drive boots |
| The firmware-source note stated an inference as fact | Reworded as an inference. The attended boot is the test |

### Round 3

Codex reviewed `71f8d5c..5504a7c` ([raw](reviews/2026-09-25-codex-boot1b-review3.md)). Verdict: "不建议执行",
with three minimal changes plus two strengthening suggestions. Claude agrees with all of them.

| Finding | Decision |
| --- | --- |
| The last level, `systemctl reboot --force --force`, had no limit; it syncs first, and `sync()` can block beyond any timeout | That call runs in the background. If the machine is still up 30 s later, the guard writes `b` to `/proc/sysrq-trigger` (reboot without syncing; the USB root may need fsck). Log lines are written in the background, so a stuck drive cannot stop the guard. Tests cover a refused and a hanging immediate reboot. The install checks that `timeout -k` works on the drive |
| `grep -q` in the prefix check closes the pipe early, and under pipefail `tr`'s SIGPIPE (141) rejects a real, megabyte-sized core image | `grep -xF … > /dev/null` reads to the end. A regression test uses a 2 MiB image |
| `systemd-pcrlogin@.service` is started by logind and writes the `login` NvPCR. The varlink sockets (pcrextend, pcrlock, factory-reset) and the preset `systemd-tpm2-clear` were missed too | A fixed list is replaced by masking by name. Every `systemd-pcr*`, `systemd-tpm2-*`, factory-reset, bless-boot, hibernate and `boot-update/random-seed/clear-sysfail` unit found on the drive is masked and verified: 41 on the current root, none essential. Generators stay; what they pull in is masked |
| The ready record did not cover grubenv | `publish` refuses a grubenv that already has `next_entry`, so the first boot after publish is the default |
| machine-id: empty is not "first boot" (see the corrected row above); check the ID's format | Generating an ID stays. The ID must be 32 hex digits, not all zeros, and not JetPack's |

### Round 4: go

Codex reviewed `5504a7c..f1febe9` ([raw](reviews/2026-09-25-codex-boot1b-review4.md)). Verdict: "可以执行
（重跑 install-thor-root.sh 和 staged install，早上按 DECISIONS.md 的有人值守步骤测试）". It found nothing that
must change. Its optional points:
- The comments said more than the code guarantees. They are narrowed: sysrq applies only after the immediate-reboot level; the guard's own commands still run from the drive; the mask scan covers `/usr/lib/systemd/system` by name.
- Keep the list of masked units as evidence. Done from the real install ([masked-units.txt](evidence/slice1b/masked-units.txt)).
- Check `CONFIG_MAGIC_SYSRQ` on the drive's kernel during the attended boot.
- Background log writes are not capped. Accepted for a short, attended test.

Accepted as the attended test's job (no change): a hang before PID 1 or of PID 1 itself is not recovered
automatically, the hardware watchdog is unproven, and a forced reboot may leave the USB root needing fsck.

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

## 2026-09-25 — `bl_prof_*` settled by the Slice 1a experiment

The plan left `bl_prof_*` open: the two reviewers disagreed, and the Slice 1a experiment was to decide. With
GRUB loading JetPack's own kernel and initrd directly, L4TLauncher never runs, so the arguments are absent,
and JetPack boots normally: GDM, no failed units, `nvidia-smi`. The device tree is identical apart from
`/chosen`. Decision: the Arch entries do not carry `bl_prof_*` (`thor_boot.cmdline` drops them, as it already
did). Evidence: [attended/README.md](evidence/slice1b/attended/README.md), step 3.

## 2026-09-25 — Slice 2: upstream Omarchy 4.0.4 with a thin Thor layer (consult point 6)

Omarchy is installed from upstream's own recipes (omarchy-pkgs, pinned to v4.0.4), unpatched, and set up
by upstream's `omarchy-apply-system` with four hash-gated overrides (nvidia, snapper, post-install pacman,
firewall). The installer runs from JetPack in a namespace chroot, as Omarchy's ISO does with
arch-chroot, with network and module capabilities dropped and `/proc/sys` read-only, so upstream's
firewall step cannot touch JetPack's live firewall. Codex round 1 raised the host firewall, the ISO's
x86_64 Node path in `provision-user`, the missing `/etc/skel` for an existing user, and the
refresh-pacman/update bypass; the first three were fixed, the last is deferred to Slice 2.2. Round 2:
go, with "do not click the update notification before 2.2".

First boot found three faults that neither the stub tests nor the reviews caught (Codex had listed
"a real UFW integration test" as optional): the greeter's empty user, the Wi-Fi profile bound to
JetPack's interface name, and `nft_limit` missing from NVIDIA's kernel. Decision for the firewall
(owner, option A of three): build the missing nf_tables module from NVIDIA's own R39.2.1 kernel
source rather than editing ufw's rules or switching ufw to iptables-legacy, so upstream's rules stay
unmodified. Evidence: [slice2/README.md](evidence/slice2/README.md).

## 2026-09-26 — Slice 2.2, first night (owner away, no reboot)

- **omarchy-update is left as upstream wrote it.** It only syncs against the configured repositories;
  what rewrites pacman.conf is `omarchy-refresh-pacman` (also behind `omarchy-channel-set`), and its
  `pre-refresh-pacman` hook puts the Thor's configuration back before the sync. The first real update
  waits for a fresh backup and something to update (Codex: no-go before that).
- **What Omarchy's ISO adds is part of "real Omarchy".** Omarchy's base list leaves the audio stack to
  archinstall (PipeWire's ALSA plugin, pipewire-pulse), as it leaves SDDM's last user to the ISO; the
  installer mirrors those ISO steps (`manifests/omarchy-iso-packages`, sources noted), in the ISO's
  order. zram is not taken: a swap device would show Hibernate, which the Thor cannot do.
- **The menu hides 24 entries**, each with evidence (`docs/evidence/slice2/menu.md`), through the
  user's extension file, the only one Omarchy's shell reads; users that exist before an upgrade get it
  and the pacman hook from the package's scriptlet (`raytone-thor-user-setup`).
- **Bluetooth runs BlueZ as Arch and Omarchy expect**: NVIDIA's drop-in (Ubuntu path, audio plugins
  off) is dropped from raytone-thor-firmware. The RTL8852BU adapter needs the vendor firmware the
  JetPack install uses, pinned like the Wi-Fi firmware (next attended session).
- **Codex review of the night's commits** found two P1 and three P2 issues, all fixed and confirmed
  in re-review: host writes through links on the drive, the hook missing for existing users, an
  unmatched menu marker deleting the user's entries, stale or untrusted signatures (now: key validity
  in the drive's keyring, every package verified from a staging copy before the repository changes,
  the verified copy is what gets published), and upstream-bump ignoring recipe-only changes and
  closing the gate on rerun.

## 2026-09-26 — Slice 2.3: Omarchy by default, dead-man retired; NVMe after Slice 3

- **Default boot is Omarchy** (entries-2.json), JetPack second in a 3 s menu; the Slice 1 test entries
  are gone, ids kept. A broken Omarchy loops until someone picks JetPack or unplugs the drive; the
  owner accepts manual recovery because every reboot is attended. Codex: go (key action review).
- **The dead-man timer is retired on the drive** (`disable --now` after creating the keep file, per
  Codex, so it cannot fire mid-update). The installers still enable it for a fresh install's first,
  unattended boots; retiring it is a commissioning step once the owner has accepted the boot.
- **Headphone routing starts with the APE card** (udev), not sound.target, which starts with the
  first card (Codex).
- **Install to the NVMe (dual boot) after Slice 3** (owner, 2026-09-26): the USB drive stays the
  test bed while CUDA/Docker/Ollama land, and the NVMe step, which lifts the "never write the NVMe
  partition table or ESP" rule, gets its own plan, Codex review and approval, with a full JetPack
  backup first.

## 2026-09-26 — Slice 3: CUDA 13.2, Docker GPU through CDI, Ollama

- **CUDA from NVIDIA's Jetson repository** (common r39.2, the same content as the SBSA repository),
  pinned in `manifests/cuda-13.2.json` after checking the index signature and hashes; laid out as
  Ubuntu installs it (`/usr/local/cuda-13.2`, `cuda`/`cuda-13` links). cuDNN and TensorRT left out.
- **Host compiler: Arch's gcc 16** (owner's choice over building gcc 15), with nvcc's
  `-allow-unsupported-compiler -std=c++17` through `NVCC_PREPEND_FLAGS`: gcc 16 defaults to C++20,
  whose headers nvcc rejects. Verified with a real CUDA program; building gcc 15 stays the fallback.
- **Ollama: the official arm64 build** (owner's choice over building for sm_110), CUDA 12 backend
  removed (ollama#13033); sm_110 runs its PTX, compiled once per user cache. The Omarchy menu entry
  installs this package.
- **CDI in CSV mode, regenerated at every boot into /run/cdi**, after NVIDIA's display stack; the
  toolkit's own pacman hook is desktop-only. OOMScoreAdjust for Ollama (known issue 5699079).

## 2026-09-26 — Slice 4: Omarchy on the NVMe next to JetPack

- **Owner lifted two rules for this slice only**: the NVMe partition table (APP shrinks, p12 added)
  and JetPack's `extlinux.conf` (one entry added, made the default). QSPI, the ESP, UEFI variables
  and TPM NV stay untouched. Split 950/955 GiB; Omarchy the default in the 3 s menu (owner).
- **Boot through L4TLauncher's extlinux.conf on APP**, not the ESP: kernel and initramfs are copied to
  APP `/boot/raytone-thor/`, and later kernels follow through a pacman hook (`nvme-boot.conf`).
- **Initramfs on the NVMe** (Codex): NVIDIA's kernel has the PCIe controller, its PHY and NVMe as
  modules; the drive boots without one, the NVMe cannot.
- **The script checks before each step**: disk identity, the recorded table (original or split),
  a verified backup, what the kernel sees after partx. The clone needs a quiet source (no user logged
  in at the Thor, no pacman lock, AI services stopped), and the boot entry needs a finished,
  cleanly unmounted clone that mounts p12 as `/`. Codex: GO after five rounds
  (docs/evidence/slice4/README.md).
