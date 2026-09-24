# Slice 1b evidence: Arch root and boot menu on the USB drive (staged, not yet booted), 2026-09-25

The JZAO drive (serial 2797824271339930) was written from JetPack twice:
- **Install 1**: pkgrel 1, before the Codex boot reviews. Files: `install-root.log`, `installed-packages.txt`,
  `usb-root-inspect.txt`, `boot-listing.txt`.
- **Install 2**: current. pkgrel 2 packages, with the fixes from four Codex review rounds (see DECISIONS.md,
  "Slice 1b boot configuration"). Files with `-2`, plus `masked-units.txt`, `install-boot-staged.log`, `grub.cfg.staged`.

The drive has **not been booted**. It is **not bootable**: the ESP has only `EFI/BOOT/BOOTAA64.EFI.staged`. The
attended procedure at the end of DECISIONS.md starts with `publish`.

Root: `/dev/sda2`, PARTUUID `ca5a56c6-4a4b-4e02-8183-ff166514ae3b`, ext4 UUID `4ae3be9c-…4dfa5`. Rootfs tarball
`ArchLinuxARM-aarch64-latest.tar.gz`, sha256 `42a4eeaa…9b319` (pinned in the gate0a evidence).

| Check (install 2) | Status | Evidence |
| --- | --- | --- |
| `raytone-thor-{linux,firmware,core}` 39.2.1-2 installed, with NVIDIA's license files | deployed path | `usb-root-inspect-2.txt`, `installed-packages-2.txt` (195) |
| Kernel `/boot/vmlinuz-raytone-thor-linux` and modules for `6.8.12-1021-tegra`. An initramfs is built too; no boot entry uses it | deployed path | `boot-listing-2.txt` |
| fstab: root by PARTUUID; efivarfs `ro` | deployed path | `usb-root-inspect-2.txt` |
| Machine ID: 32 hex digits, not JetPack's; `KEYMAP=us` | deployed path | `usb-root-inspect-2.txt` |
| 48 units masked: 41 found by name (TPM/PCR/factory-reset/hibernate/bless-boot/boot-*) and 7 always (firstboot, repart, sleep targets) | deployed path | `masked-units.txt` |
| Safety units enabled: dead-man (20 min); boot start and marker (records `uname -v`); thermal guard, which checks every 30 s and escalates to sysrq; emergency and rescue reboot; reboot forced after 5 min | deployed path | `install-root-2.log`, `usb-root-inspect-2.txt` (guard sha256 = repo) |
| NVIDIA services enabled: nv-load-display-modules, nvfancontrol, nvpmodel, nvpower | deployed path | `install-root-2.log` |
| GRUB staged: loader in a staging directory, then moved to `.staged`. Ready record of 247 sha256 lines verifies. Prefix `(,gpt1)/boot/grub` | deployed path | `install-boot-staged.log` |
| Menu: `jetpack-nvme` (default), `jetpack-grub`, `raytone-arch`, `raytone-arch-jetpack-kernel`, retry-reboot, uefi-menu; the staged `grub.cfg` equals the dry-run render | deployed path | `grub.cfg.staged`, `grub.cfg.dry-run`, `entries-1b.json` |
| `efibootmgr -v`, `nvbootctrl dump-slots-info` and the BIOS version are unchanged since Gate 0b | real data | read-only queries on the Thor, compared with `gate0b/run-*/state-after-*` |
| The drive boots; SSH; `nvidia-smi`; the fan follows the temperature; the dead-man brings JetPack back | **not run** | waits for the owner |

Expected noise in the logs: pacman hooks that need a running systemd (`System has not been booted with systemd`,
`Failed to check for chroot() environment`) fail or skip, because the install runs in a namespace chroot with
capabilities dropped. `Possibly missing firmware for module: 'xhci_pci'` concerns the PCI xHCI driver; the Thor's
ports use `xhci-tegra`, whose firmware the boot firmware loads (kernel-provenance.md). `passwd: password changed.`
comes from `chpasswd`; no hash is printed.

Not done yet: `pacman.conf` has no `IgnorePkg` line. Nothing pulls `linux-aarch64` back in (Arch's `base` does
not depend on a kernel), and Slice 2's `omarchy-refresh-pacman` rewrites `pacman.conf` anyway.
