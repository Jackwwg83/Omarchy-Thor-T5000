# Slice 1b evidence: Arch root on the USB drive (installed, not yet booted), 2026-09-25

`scripts/install-thor-root.sh --write` ran on JetPack against the JZAO drive (serial
2797824271339930) and exited 0 after its own checks. The drive has **not been booted**. Boot
tests wait for the owner to be present; see SCRATCHPAD.md for the order.

Root: `/dev/sda2`, PARTUUID `ca5a56c6-4a4b-4e02-8183-ff166514ae3b`. Rootfs tarball
`ArchLinuxARM-aarch64-latest.tar.gz`, sha256 `42a4eeaa…9b319` (pinned in the gate0a evidence).

| Check | Status | Evidence |
| --- | --- | --- |
| Rootfs unpacked, keyring initialised, `linux-aarch64` removed, system upgraded | deployed path | `install-root.log` |
| `raytone-thor-{linux,firmware,core}` installed from local packages | deployed path | `installed-packages.txt` (195 packages) |
| Kernel `/boot/vmlinuz-raytone-thor-linux`, fallback initramfs, modules for `6.8.12-1021-tegra` | deployed path | `boot-listing.txt`, `usb-root-inspect.txt` |
| depmod picks OpenRM from `updates/opensource-gpu-disp` | deployed path | `usb-root-inspect.txt` |
| nvpmodel and nvfancontrol linked to the P3834-0008 / P4071-0000 board files | deployed path | `usb-root-inspect.txt` |
| Loader path limited to `/usr/lib/raytone-l4t` (NVIDIA-named libraries only) | deployed path | `usb-root-inspect.txt` |
| Login: user `nvidia` (uid 1000, wheel/video/render/audio/input), host password hash, SSH key; root locked | deployed path | `usb-root-inspect.txt`; script checks `sshd -t`, `visudo -cf` |
| One active NetworkManager profile copied (0600); name not recorded here | deployed path | `usb-root-inspect.txt` |
| Bring-up safety units enabled: deadman timer (20 min), boot start and marker, thermal guard, emergency/rescue → reboot | deployed path | `install-root.log` (`Created symlink …`) |
| NVIDIA services enabled: nv-load-display-modules, nvfancontrol, nvpmodel, nvpower | deployed path | `install-root.log` |
| The drive boots; SSH; `nvidia-smi`; fan responds to temperature | **not run** | waits for the owner |

Expected noise in the log: pacman hooks that need a running systemd (`System has not been
booted with systemd`, `Failed to check for chroot() environment`) fail or skip, because the
install runs in a namespace chroot with capabilities dropped. `Possibly missing firmware for
module: 'xhci_pci'` is about the PCI xHCI driver; the Thor's USB ports use the built-in
`xhci-tegra`.

Found in this run, not yet acted on:
- `pacman.conf` has no `IgnorePkg` line. The plan says to add `linux-aarch64` there; nothing
  pulls it back in today (Arch's `base` does not depend on a kernel), so this waits for the
  Omarchy slice, where `omarchy-refresh-pacman` rewrites `pacman.conf` anyway.
