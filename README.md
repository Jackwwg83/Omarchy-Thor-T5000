# Omarchy Thor T5000

An unofficial port of [Omarchy](https://github.com/basecamp/omarchy), the Hyprland desktop on Arch Linux, to the
**NVIDIA Jetson AGX Thor (T5000)**. It runs Arch Linux ARM with NVIDIA's own Jetson Linux (L4T R39.2.1) kernel,
GPU driver and firmware, repackaged as Arch packages, from an external USB drive. The JetPack install on the
internal NVMe stays untouched: unplug the drive, or pick the default boot entry, and the machine boots JetPack.

Part of RaytoneOS. The desktop layer follows [omarchy-spark](https://github.com/jdvmi00/omarchy-spark), the
Arch + Omarchy port for the DGX Spark. The Thor is a different platform: Tegra264, device-tree boot, and an L4T
kernel with out-of-tree modules. The kernel, drivers and boot chain here are therefore specific to Jetson.

> **Experimental.** It has been booted on one machine, with its owner at the keyboard. Read
> [Safety](#safety) before writing a drive, and know how to recover: unplug the drive and power-cycle.

## Status

| Stage | What | State |
| --- | --- | --- |
| Gate 0 | Arch userspace against L4T graphics: GBM, EGL, Vulkan on "NVIDIA Thor"; patched Hyprland on HDMI at 2560×1440; clients on the GPU | done ([evidence](docs/evidence/gate0b/README.md)) |
| Slice 1a | GRUB on the USB drive chainloads JetPack, or boots JetPack's kernel directly; same device tree and command line | done, attended ([evidence](docs/evidence/slice1b/attended/README.md)) |
| Slice 1b | Arch Linux ARM boots from the USB drive on NVIDIA's L4T kernel with no initramfs: GPU (`nvidia-smi`), Wi-Fi, fan control, hardware watchdog, efivarfs read-only | done, attended, 2026-09-25 (warm and cold boots, dead-man fallback, unplug test) ([evidence](docs/evidence/slice1b/attended/README.md)) |
| Slice 2 | Upstream Omarchy 4.0.4 unmodified, with a hash-gated Thor layer: SDDM → Hyprland + Quickshell on the NVIDIA GPU, HDMI and headphone audio, Bluetooth, `omarchy-update` from the port's signed repository; boots Omarchy by default | done, attended, 2026-09-26 ([evidence](docs/evidence/slice2/README.md), [following upstream](docs/UPSTREAM-SYNC.md)) |
| Slice 3 | CUDA 13 (sm_110), Docker with GPU through CDI, Ollama | next |

Plan: [docs/PLAN.md](docs/PLAN.md). Every design decision and review: [docs/DECISIONS.md](docs/DECISIONS.md).

## Tested hardware

- Jetson AGX Thor T5000 module on a carrier reported as `nvidia,p4071-0000` (`p3834-0008` module), in a system
  built by Leetop. JetPack 7.2.1 / L4T R39.2.1, UEFI firmware in QSPI.
- A JZAO 231 GiB USB 3.2 Gen 1 stick in a USB-A port (5 Gb/s). The USB-C ports did not detect it, which matches NVIDIA known issue 5251623.
- HDMI monitor at 2560×1440.

Leetop's JetPack install carries a rebuilt kernel and three drivers no package owns: RTL8852BE Wi-Fi, RTL8125
2.5GbE, and a Bluetooth driver. The Arch drive uses NVIDIA's own kernel. The two network drivers come from the local
JetPack install through [`raytone-thor-leetop-nic`](packages/raytone-thor-leetop-nic/PKGBUILD). That recipe
checks the files' sha256 and never redistributes them; their symbol CRCs match NVIDIA's kernel. Details:
[kernel-provenance.md](docs/evidence/slice1b/kernel-provenance.md). Another carrier board will need its own
equivalent, or none.

## How it works

- **Packages** ([packages/](packages/)): `raytone-thor-{linux,firmware,core,graphics}`. These are NVIDIA's L4T
  R39.2.1 `.deb`s, downloaded from `repo.download.nvidia.com` at build time and checked against pinned sha256s
  ([manifests/](manifests/)). They are laid out for Arch's merged `/usr`. A static check fails the build on
  prohibited content: bootloader updates, capsules, `nvbootctrl`. Nothing from NVIDIA is committed here.
- **Hyprland** ([patches/](patches/)): 0.56.2 with one patch. It advertises the EGL device's render node, so
  clients render on the Thor's GPU instead of falling back to llvmpipe. The Thor has separate display and GPU DRM nodes.
- **USB drive** ([scripts/](scripts/)):
  - `make-thor-usb.sh`: GPT with `RAYTONE_ESP` and `RAYTONE_ROOT`. It checks the disk's identity: transport, serial, size, not in use.
  - `install-thor-root.sh`: the Arch root, installed from JetPack in a namespace chroot.
  - `install-thor-boot.sh`: GRUB `--removable --no-nvram`, in three steps: `install` (staged), `publish` (makes the drive bootable), `arm-once` (one-shot test entry).
- **Boot**: UEFI → the drive's GRUB → default entry: JetPack's own boot loader on the NVMe. Arch and other test
  entries run once, set through grubenv `next_entry`. The Arch entry boots NVIDIA's kernel without an initramfs:
  the xHCI firmware is already loaded by the boot firmware, and USB storage, ext4 and SCSI are built in. The root
  is mounted `ro` first so it can be checked.

## Safety

What the tools never write: QSPI firmware, the NVMe partition table or ESP, JetPack's boot configuration, UEFI
variables. No `efibootmgr` writes, no capsules, no `nvbootctrl` writes. On the running Arch system:
- efivarfs is mounted read-only;
- units that can write UEFI variables or TPM NV storage are masked (tpm2-setup, pcr\*, factory-reset,
  hibernate-clear, boot-random-seed and others).

Bring-up safety nets on the drive:
- **Boot path:** GRUB's default returns to JetPack. `panic=10` and a bounded `rootwait` make a failed boot reboot instead of hanging.
- **Staged publishing:** `install` leaves the drive unbootable. `publish` refuses unless the last install finished (a sha256 ready record).
- **Runtime:** a dead-man timer reboots after 20 minutes unless the boot is confirmed. A thermal guard reboots when fan control stops or the SoC reaches 95 °C.
- **Stalls:** emergency and rescue mode reboot, and a stalled reboot is forced.

The UEFI firmware itself rewrites its auto-created boot option for the USB drive on most boots. This is the
firmware's behaviour with any removable drive, not something these tools do.

## Build and install (outline)

The tools run on the Thor, under JetPack, as root. Each takes `--write --confirm-serial <serial>`, and without it
only reports what it would do. The attended procedure is at the end of [docs/DECISIONS.md](docs/DECISIONS.md), and
the [evidence](docs/evidence/slice1b/README.md) shows real runs. There is no one-shot installer yet.

```
scripts/make-thor-usb.sh     --disk /dev/disk/by-id/usb-... --serial S [--write --confirm-serial S]
scripts/install-thor-root.sh --disk ... --serial S --tools-root ROOT --tarball ArchLinuxARM-aarch64-latest.tar.gz \
                             --tarball-sha256 HEX --packages PKGDIR --user NAME [--write --confirm-serial S]
scripts/install-thor-boot.sh install  --entries ENTRIES.json --default jetpack-nvme ... [--write ...]
scripts/install-thor-boot.sh publish  ... --write ...        # someone at the machine from here on
scripts/install-thor-boot.sh arm-once --entry raytone-arch ... --write ...
```

Tests: `python3 -m unittest discover -s tests`. They use stubbed tools and run on macOS or Linux.

## Layout

```
docs/        plan, decisions (with the Codex reviews), inventory, evidence of every gate and slice
manifests/   pinned L4T package set (names, versions, sha256)
packages/    PKGBUILDs: raytone-thor-*, hyprland
patches/     Hyprland render-node patch
scripts/     USB drive, root and boot installers; package repacking and checks
spikes/      Gate 0 probe harnesses (throwaway, kept for the record)
tests/       unit and behaviour tests for scripts/
```

## Credits

[Omarchy](https://github.com/basecamp/omarchy) by Basecamp · [omarchy-spark](https://github.com/jdvmi00/omarchy-spark) ·
[Arch Linux ARM](https://archlinuxarm.org) · [Hyprland](https://hyprland.org) · NVIDIA Jetson Linux.
Not affiliated with or endorsed by Basecamp, NVIDIA or Leetop.

## License

MIT for the contents of this repository ([LICENSE](LICENSE)). NVIDIA's packages, vendor drivers and upstream
projects keep their own licenses.
