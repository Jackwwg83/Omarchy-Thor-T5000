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
