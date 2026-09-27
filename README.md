# Omarchy Thor T5000

An unofficial port of [Omarchy](https://github.com/basecamp/omarchy), the Hyprland desktop on Arch Linux, to the
**NVIDIA Jetson AGX Thor (T5000)**. It runs Arch Linux ARM with NVIDIA's own Jetson Linux (L4T R39.2.1) kernel,
GPU driver and firmware, repackaged as Arch packages. It includes CUDA 13.2, Docker with the GPU, and Ollama.

There are two ways to run it:

| | **A. From a USB drive** (recommended to try it) | **B. On the internal NVMe, next to JetPack** (advanced) |
| --- | --- | --- |
| What changes on the Thor | JetPack's partitions and boot are not touched (the tools only keep their work files, such as the signing key, in a directory in JetPack) | JetPack's partition is shrunk, a partition is added, and JetPack's boot menu gets an entry |
| How to go back | Unplug the drive | Menu key `1` boots JetPack; a full undo needs the backup, or a reflash |
| Speed | USB 3 speed (fine for a desktop and AI work) | NVMe speed |
| Risk | Low | Real: a mistake can leave JetPack unbootable until you reflash it |

> **Experimental.** Built and tested on one machine, with its owner at the keyboard. Every script is a dry
> run unless given `--write --confirm-serial <serial>` and checks the target disk's identity before it writes,
> but read [Safety](#safety) and have a [way to reflash JetPack](#before-you-start-a-way-to-reflash-jetpack) first.

Part of RaytoneOS, by Raytone AI Lab. The desktop layer follows [omarchy-spark](https://github.com/jdvmi00/omarchy-spark),
the Arch + Omarchy port for the DGX Spark. The Thor is a different platform: Tegra264, device-tree boot, and an L4T
kernel with out-of-tree modules. The kernel, drivers and boot chain here are therefore specific to Jetson.

## Status

| Stage | What | State |
| --- | --- | --- |
| Gate 0 | Arch userspace against L4T graphics: GBM, EGL, Vulkan on "NVIDIA Thor"; patched Hyprland on HDMI at 2560×1440; clients on the GPU | done ([evidence](docs/evidence/gate0b/README.md)) |
| Slice 1 | Arch Linux ARM boots from a USB drive on NVIDIA's L4T kernel through the drive's GRUB: GPU (`nvidia-smi`), Wi-Fi, fan control, hardware watchdog, efivarfs read-only; JetPack still one menu entry away | done, attended, 2026-09-25 ([evidence](docs/evidence/slice1b/attended/README.md)) |
| Slice 2 | Upstream Omarchy 4.0.4 unmodified, with a hash-gated Thor layer: SDDM → Hyprland + Quickshell on the NVIDIA GPU, HDMI and headphone audio, Bluetooth, `omarchy-update` from the port's signed repository | done, attended, 2026-09-26 ([evidence](docs/evidence/slice2/README.md), [following upstream](docs/UPSTREAM-SYNC.md)) |
| Slice 3 | CUDA 13.2 (nvcc with gcc 16, cuBLAS) on sm_110, Docker containers with the GPU through CDI, Ollama on the GPU | done, attended, 2026-09-26 ([evidence](docs/evidence/slice3/README.md)) |
| Slice 4 | The same Omarchy on the internal NVMe, dual boot with JetPack through NVIDIA's own boot menu; the USB drive no longer needed | done, attended, 2026-09-27 ([evidence](docs/evidence/slice4/README.md)) |

Plan: [docs/PLAN.md](docs/PLAN.md). Every design decision and review: [docs/DECISIONS.md](docs/DECISIONS.md).

## Tested hardware

- Jetson AGX Thor T5000 module on a carrier reported as `nvidia,p4071-0000` (`p3834-0008` module), in a system
  built by Leetop. JetPack 7.2.1 / L4T R39.2.1 on a 2 TB NVMe, UEFI firmware in QSPI.
- A JZAO 231 GiB USB 3.2 Gen 1 stick in a USB-A port (5 Gb/s). The USB-C ports did not detect it, which matches
  NVIDIA known issue 5251623.
- HDMI monitor at 2560×1440.

Leetop's JetPack install carries a rebuilt kernel and three drivers no package owns: RTL8852BE Wi-Fi, RTL8125
2.5GbE, and a Bluetooth driver. The port uses NVIDIA's own kernel. The two network drivers come from the local
JetPack install through [`raytone-thor-leetop-nic`](packages/raytone-thor-leetop-nic/PKGBUILD). That recipe
checks the files' sha256 and never redistributes them; their symbol CRCs match NVIDIA's kernel. Details:
[kernel-provenance.md](docs/evidence/slice1b/kernel-provenance.md). **Another carrier board will need its own
equivalent, or none.**

## Before you start: a way to reflash JetPack

Have this ready before writing anything. It is required for the NVMe install (B), and strongly recommended for
the USB drive (A).

- **Your carrier vendor's JetPack flash package** for your exact board and L4T release (for this machine:
  Leetop's, for L4T R39.2.1). A generic NVIDIA image may lack the carrier's drivers.
- **A computer that can flash it**: NVIDIA's flashing tools run on an x86_64 Ubuntu host, connected to the
  Thor's flashing USB-C port, with the Thor in Force Recovery mode (see your carrier's manual for the buttons).
  Check once that the host sees the Thor in recovery mode before you rely on it.
- A reflash restores JetPack as shipped. Anything you keep in JetPack comes back only from your own backup;
  the NVMe install (B) makes one of JetPack's root partition for you.

None of the tools here write QSPI (the UEFI firmware), so recovery mode and the flash path stay available.

## A. Run from a USB drive (recommended to try it)

What you need: the Thor with JetPack 7.2.1 (L4T R39.2.1) on its NVMe, a USB 3 drive of at least 128 GB in a
**USB-A** port (it will be erased), network access, and a monitor, keyboard and mouse.

The tools run on the Thor, under JetPack, as root. Each is a dry run until given `--write --confirm-serial
<serial>` (the drive's serial, as `lsblk -o NAME,SERIAL` shows it). There is no one-shot installer yet: the
steps below are the ones used on the test machine, and the [evidence](docs/evidence/) shows each real run.

1. **Build the packages.** Each directory under [packages/](packages/) is an Arch PKGBUILD, built with
   `makepkg` in an Arch Linux ARM environment (a chroot on JetPack for the first build, the drive itself later).
   NVIDIA's `.deb`s are downloaded from `repo.download.nvidia.com` at build time and checked against the sha256s
   in [manifests/](manifests/); `scripts/check_package.py` must report 0 problems for each package.
2. **Prepare the drive** (erases it: GPT with `RAYTONE_ESP` and `RAYTONE_ROOT`):
   ```
   scripts/make-thor-usb.sh --disk /dev/disk/by-id/usb-... --serial S [--write --confirm-serial S]
   ```
3. **Install the Arch root** (the verified Arch Linux ARM tarball, NVIDIA's kernel, firmware and drivers; your
   JetPack user, password and SSH keys; your Wi-Fi profiles):
   ```
   scripts/install-thor-root.sh --disk ... --serial S --tools-root ROOT --tarball ArchLinuxARM-aarch64-latest.tar.gz \
       --tarball-sha256 HEX --packages PKGDIR --user NAME [--write --confirm-serial S]
   ```
4. **Install Omarchy** (upstream Omarchy the way its ISO does it, with the Thor layer, and the port's signed
   package repository on the drive):
   ```
   scripts/install-thor-omarchy.sh --disk ... --serial S --packages PKGDIR --user NAME [--write --confirm-serial S]
   ```
5. **Make it bootable** (GRUB on the drive's ESP only, `--removable --no-nvram`: no UEFI variable is written).
   Stage the menu first, then publish it with someone at the machine:
   ```
   scripts/install-thor-boot.sh install --entries ENTRIES.json --default raytone-arch --disk ... --serial S --tools-root ROOT [--write ...]
   scripts/install-thor-boot.sh publish --disk ... --serial S --tools-root ROOT --write --confirm-serial S
   ```
   [`docs/evidence/slice2/entries-2.json`](docs/evidence/slice2/entries-2.json) is the menu used here (Omarchy
   first, JetPack second); its UUIDs are this machine's, so write your own from `blkid`.
6. **Boot it.** With the drive plugged in, the firmware boots it first. GRUB offers
   "RaytoneOS Omarchy (USB drive)" (default) and "JetPack on the internal NVMe" for 3 seconds.
   To go back to JetPack for good, unplug the drive.
7. **Accept the boot.** For the first boots, a dead-man timer reboots the machine after 20 minutes unless the
   boot is confirmed (a safety net for boots nobody watches). Once the desktop works, retire it:
   ```
   sudo touch /run/raytone-keep && sudo systemctl disable --now raytone-deadman.timer
   ```
   **Do this before the NVMe install (B)**, or the timer can reboot the machine in the middle of it.
8. **CUDA and Ollama** are in the port's repository but not installed by the steps above:
   `sudo pacman -S raytone-thor-cuda raytone-thor-ollama`, then `sudo systemctl enable --now ollama` (the package
   does not enable its service). Ollama is also under Install > AI in the Omarchy menu.

## B. Install on the NVMe, next to JetPack (advanced, read all of this first)

> **Warning.** This rewrites the NVMe's partition table (JetPack's partition is shrunk to 950 GiB) and
> JetPack's boot menu (`/boot/extlinux/extlinux.conf`). A power cut or a mistake during the shrink can leave
> JetPack unbootable, and then the way back is a [reflash](#before-you-start-a-way-to-reflash-jetpack).
> Do it only with a working reflash path, from the USB install (A), with someone at the machine.

**It is locked to the tested machine.** [`scripts/install-thor-nvme.sh`](scripts/install-thor-nvme.sh) refuses
any disk whose partition table and boot menu are not exactly the ones recorded in
[`manifests/thor-nvme-gpt-2026-09-26.sfdisk`](manifests/thor-nvme-gpt-2026-09-26.sfdisk) and
[`manifests/jetpack-extlinux-2026-09-26.conf`](manifests/jetpack-extlinux-2026-09-26.conf), down to the disk's
GPT id. That is deliberate. To use it on another Thor, treat it as porting the tool, not running it:
- record your own layout and boot menu (`sfdisk --dump /dev/nvme0n1`, your `/boot/extlinux/extlinux.conf`) and
  point [`scripts/thor_nvme.py`](scripts/thor_nvme.py) at them;
- change the values fixed at the top of `install-thor-nvme.sh`: `NVME_SIZE` (your disk's size in bytes),
  `APP_PARTUUID` (JetPack's root partition, from `blkid`; it also goes into the kernel-sync config, so a wrong
  one breaks later kernel updates) and `APP_GIB` (what JetPack keeps; it must hold what JetPack uses, with room);
- run the tests.

The partition table is checked at every step, but the boot menu only at the last one (`boot-entry`): compare
your `extlinux.conf` with the recorded one **before** `shrink-app`, or a machine with a different menu is split
first and refused only at the end.

How it works: NVIDIA's boot loader (L4TLauncher) reads `extlinux.conf` from JetPack's partition and already supports
several entries. The tool adds an Omarchy entry that loads the kernel and an initramfs from JetPack's partition
(`/boot/raytone-thor/`) and mounts Omarchy's own partition (`RAYTONE_OMARCHY`) as root. JetPack's own entry is left
byte for byte. The ESP, UEFI variables, QSPI and TPM are not touched.

Steps, run as root on the Thor **booted from the USB drive** (nothing on the NVMe may be mounted), one at a
time, checking each result before the next. Each takes
`--nvme /dev/disk/by-id/nvme-... --serial S --backup-dir DIR [--write --confirm-serial S]`:

1. Make sure the dead-man timer is retired (A, step 7). Update the drive (`omarchy-update`), rebuild its
   initramfs (`sudo mkinitcpio -P`), and log out of the desktop: the copy wants a quiet system.
2. `backup`: the partition table, JetPack's root partition as a verified tar (about 35 GB for 53 GB used), and
   `extlinux.conf`, onto the USB drive. Copy it off the Thor too if you can. `shrink-app` refuses to run without it.
3. `shrink-app`: check and shrink JetPack's filesystem, then write the new table. JetPack's partition keeps its
   start and its PARTUUID, so JetPack still finds its root.
4. `create-root`: a new ext4 `RAYTONE_OMARCHY` in the freed space.
5. `clone`: copies the running USB system there, and points its fstab at the new partition.
6. `boot-entry`: checks the copy, then adds the Omarchy entry as the default. The original is kept as
   `extlinux.conf.jetpack`.
7. Test in this order: reboot with the drive in (the USB path still works); power off, unplug the drive, power on
   (Omarchy from the NVMe); reboot and press `1` (JetPack).

**NVIDIA's boot menu** shows `0: RaytoneOS Omarchy (NVMe)` and `1: primary kernel` (JetPack) for 3 seconds.
It takes **number keys**: any other key boots the default.

**Undo**, from the USB drive:

| What went wrong | Back to |
| --- | --- |
| The shrink stopped with an error | the table is written last; JetPack's data can come back from the tar |
| The partition table | `sfdisk /dev/nvme0n1 < DIR/nvme-gpt.sfdisk`, then check JetPack's filesystem |
| The boot menu | mount JetPack's partition and copy `boot/extlinux/extlinux.conf.jetpack` over `extlinux.conf` |
| Omarchy from the NVMe does not boot | press `1` for JetPack, or plug the USB drive back in |
| JetPack does not boot | [reflash](#before-you-start-a-way-to-reflash-jetpack), then restore from the tar |

## Using it

- **Updates**: `omarchy-update`, as on any Omarchy. Upstream Omarchy and Arch Linux ARM packages come from their
  own repositories; the port's packages (kernel, drivers, CUDA, the Thor layer) come from its signed local
  repository, `[raytone-thor]`. New port builds are signed and published from JetPack with
  `scripts/publish-thor-repo.sh` (`--disk` for the USB drive, `--nvme` for the NVMe install), and the signing
  key never leaves JetPack.
- **Kernel upgrades on the NVMe install**: a pacman hook copies each new kernel and initramfs to JetPack's
  partition, only as a complete, matching pair.
- **CUDA**: `nvcc` with `-arch=sm_110`; `NVCC_PREPEND_FLAGS` is set for gcc 16. A smoke test:
  [tests/cuda-smoke.cu](tests/cuda-smoke.cu).
- **Docker with the GPU**: `sudo docker run --device nvidia.com/gpu=all ...`. `docker` needs `sudo`, as upstream
  Omarchy ships it (the docker group is root-equivalent); opt in with Setup > Security > Sudoless Docker.
- **Ollama**: runs as a service on the GPU (`ollama run qwen3:1.7b`).
- **Headphones**: the Thor's own jack and HDMI audio both work; pick the output in the audio settings.

Known issues:
- After a full power-off the clock starts at 1970 until NTP syncs, about a minute with a network: the system
  clock is not set from the right one of the Thor's two RTCs. A warm reboot keeps the time.
- On the NVMe install, a kernel package installed in JetPack (NVIDIA's `nv-update-extlinux` hook) makes JetPack the
  default entry again. Omarchy stays as `0`; set `DEFAULT omarchy` in `extlinux.conf` to restore it.
- A USB drive in a USB-C port is not detected (NVIDIA known issue 5251623): use USB-A.

## How it works

- **Packages** ([packages/](packages/)): `raytone-thor-{linux,firmware,core,graphics,cuda,ollama,omarchy}` and
  others. NVIDIA's L4T R39.2.1 `.deb`s are downloaded at build time, checked against pinned sha256s
  ([manifests/](manifests/)) and laid out for Arch's merged `/usr`. A static check fails the build on prohibited
  content: bootloader updates, capsules, `nvbootctrl`. Nothing from NVIDIA is committed here.
- **Hyprland** ([patches/](patches/)): 0.56.2 with one patch. It advertises the EGL device's render node, so
  clients render on the Thor's GPU instead of falling back to llvmpipe. The Thor has separate display and GPU DRM nodes.
- **Omarchy**: upstream, unmodified, with a thin Thor layer ([`raytone-thor-omarchy`](packages/raytone-thor-omarchy/)):
  overrides gated on the hash of the upstream file they replace, a menu extension that hides what cannot work on
  the Thor, and the NVMe boot pieces. How upstream updates are followed: [docs/UPSTREAM-SYNC.md](docs/UPSTREAM-SYNC.md).
- **Boot from USB**: UEFI → the drive's GRUB → NVIDIA's kernel, with no initramfs (the boot firmware has already
  loaded the xHCI firmware; USB storage and ext4 are built in). The root is mounted `ro` first so it can be checked.
- **Boot from NVMe**: UEFI → L4TLauncher on the NVMe's ESP (unchanged) → the `omarchy` entry in JetPack's
  `extlinux.conf` → NVIDIA's kernel with an initramfs that loads the PCIe controller, its PHY and the NVMe driver.

## Safety

Never written by any tool here: QSPI firmware, the NVMe's ESP, UEFI variables, TPM NV storage. No
`efibootmgr` writes, no capsules, no `nvbootctrl` writes.
- The USB install (A) writes the USB drive, identified by its serial, and in JetPack only its own work files (the
  package signing key in `~/raytone/signing`, signatures next to the packages it publishes).
- The NVMe install (B) writes the NVMe's partition table (one shrink, one new partition) and, on JetPack's
  partition, `/boot/raytone-thor/` and `extlinux.conf`, each file written in full and renamed into place. Every
  step checks the disk and the recorded partition table first; the shrink needs a verified backup; the boot
  menu is checked against the recorded one at `boot-entry`.
- On the running system: efivarfs is mounted read-only, and units that can write UEFI variables or TPM NV storage
  are masked (tpm2-setup, pcr\*, factory-reset, hibernate-clear, boot-random-seed and others).
- A failed boot reboots instead of hanging (`panic=10`, a bounded `rootwait`); a thermal guard reboots when fan
  control stops or the SoC reaches 95 °C.

The UEFI firmware itself rewrites its auto-created boot option for the USB drive on most boots. This is the
firmware's behaviour with any removable drive, not something these tools do.

## Development

Tests: `python3 -m unittest discover -s tests`. They use stubbed tools and run on macOS or Linux.

```
docs/        plan, decisions (with the Codex reviews), inventory, evidence of every gate and slice
manifests/   pinned L4T and CUDA package sets, recorded NVMe layout and boot menu
packages/    PKGBUILDs: raytone-thor-*, hyprland
patches/     Hyprland render-node patch
scripts/     USB drive, root, Omarchy, boot and NVMe installers; package repacking, checks and publishing
spikes/      Gate 0 probe harnesses (throwaway, kept for the record)
tests/       unit and behaviour tests for scripts/ and packages/
```

## Credits

[Omarchy](https://github.com/basecamp/omarchy) by Basecamp · [omarchy-spark](https://github.com/jdvmi00/omarchy-spark) ·
[Arch Linux ARM](https://archlinuxarm.org) · [Hyprland](https://hyprland.org) · NVIDIA Jetson Linux.
Not affiliated with or endorsed by Basecamp, NVIDIA or Leetop.

## License

MIT for the contents of this repository ([LICENSE](LICENSE)), © Raytone AI Lab and contributors. NVIDIA's
packages, vendor drivers and upstream projects keep their own licenses.
