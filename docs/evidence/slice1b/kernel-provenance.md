# Kernel provenance: JetPack runs a vendor rebuild, the USB drive has NVIDIA's (2026-09-25)

Found while preparing the Arch boot entry. Read-only queries on the Thor.

| | JetPack `/boot/Image` (running) | `raytone-thor-linux` `/boot/vmlinuz-raytone-thor-linux` |
| --- | --- | --- |
| Source | replaced after install: `dpkg --verify nvidia-l4t-kernel` reports `??5??????  /boot/Image` | `nvidia-l4t-kernel_6.8.12-tegra-39.2.1-20260806224157_arm64.deb` (NVIDIA repo, pinned sha256 in the manifest) |
| Build string | `6.8.12-1021-tegra (leetop@leetop) … #2 SMP PREEMPT Wed Aug 19 15:09:25 CST 2026` | `6.8.12-1021-tegra (buildbrain@…) … #1 SMP PREEMPT Thu Aug 6 21:56:04 PDT 2026` |
| Size | 52,484,608 bytes | 53,467,648 bytes |
| sha256 | `4eb45aad…6cf6688` | `8e3738af…f866761e` (same as the deb's `boot/Image`) |

The machine's vendor (Leetop) rebuilt the kernel from the same 6.8.12-1021-tegra tree. Across the
kernel, OOT, OpenRM and display-kernel packages, `dpkg --verify` finds two changed files besides the
regenerated `modules.*` indexes: `/boot/Image` and `updates/drivers/bluetooth/realtek/rtk_btusb.ko`. So the
module files on disk are NVIDIA's, and the vendor kernel loads the ones JetPack uses today. That is
practical evidence for those modules only. It does not show that every module works with either kernel,
and `dpkg --verify` checks files on disk, not what is loaded. Both kernels report the same `uname -r`, so
the boot marker on the drive records `uname -v` to tell them apart.

Embedded configs (`IKCFG_ST`) differ in three lines only:

| Option | NVIDIA | Leetop |
| --- | --- | --- |
| `CONFIG_DMA_NUMA_CMA` | y | not set |
| `CONFIG_USB_NET_CDC_MBIM` | not set | m |
| `CONFIG_USB_WDM` | not set | m |

Boot-relevant options are the same in both: `USB_XHCI_TEGRA=y`, `PHY_TEGRA_XUSB=y`, `USB_STORAGE=y`,
`USB_UAS=m`, `SCSI=y`, `BLK_DEV_SD=y`, `EXT4_FS=y`, `I2C_TEGRA=y`, `TYPEC_UCSI=m`. The 1 MB size difference
is not explained by the config; source patches cannot be ruled out.

Other facts for the no-initramfs entry:
- The JZAO drive binds to `usb-storage` (bulk-only), not `uas`, even with `uas` loaded, on the A port
  (5000M). The kernel finds it without modules.
- The xHCI controller's firmware is not read from a file by the kernel. (An earlier version of this note
  argued this from the log order, `Firmware timestamp` at 5.82 s before `Run /init` at 5.99 s. Codex pointed
  out that this proves nothing: the kernel unpacks the initramfs before `/init`, and the firmware loader
  waits for it.) The evidence instead:
  - JetPack's initrd (`nvidia-l4t-initrd`) does carry `usr/lib/firmware/nvidia/tegra186/xusb.bin` (and a
    `tegra18x_xusb_firmware` link to it). Its header says it was built on 2020-07-06. The same file,
    sha256 `42b66946…71f3ac`, is in Arch's `linux-firmware-nvidia` on the drive.
  - The kernel names four firmware files in its strings: `nvidia/tegra{124,186,194,210}/xusb.bin`. None of
    them is for Tegra264. The only copies on JetPack's disk are the 2020 builds; `tegra194` is from
    2020-09-11.
  - The running controller reports `Firmware timestamp: 2025-09-08 05:45:00 UTC, Version: 90.05 release`.
    No file on disk or in the initrd has that build. The inference is that the boot firmware loaded the
    controller's firmware and the kernel read the header of the running copy. This is an inference, not
    a proof: another vendor mechanism is not ruled out, and it does not show that NVIDIA's kernel takes
    the controller over the same way on a cold boot through GRUB. The attended boot tests that.
  - `CONFIG_EXTRA_FIRMWARE=""` (nothing is built in), `CONFIG_DEVTMPFS_MOUNT=y` (needed without an initramfs).
- The USB drive appeared as `sda` at 9.0 s. `rootwait=20` bounds only the wait for the root device, not
  driver probing before it.
- UEFI variable writes by the kernel: `CONFIG_EFI_VARS_PSTORE` is not set in either config (the three-line
  diff above covers everything else), so panic logs cannot go to UEFI variables.
  `CONFIG_EFI_CAPSULE_LOADER=y` provides `/dev/efi_capsule_loader`; nothing on the drive uses it (capsule
  tools and fwupd are prohibited), and the drive's own fstab mounts efivarfs read-only.
- `/etc/firmware` (in the command line as `firmware_class.path`) does not exist on JetPack or on the drive;
  the kernel falls back to `/usr/lib/firmware`.

Plan for the attended boot tests: the stock kernel first (`raytone-arch`); if it fails where the vendor
kernel would not, `raytone-arch-jetpack-kernel` boots the same USB root with JetPack's own `/boot/Image`,
read by GRUB from the NVMe (nothing copied or written). Bluetooth may differ with the stock `rtk_btusb`
(Slice 2).
