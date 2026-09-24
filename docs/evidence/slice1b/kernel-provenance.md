# Kernel provenance: JetPack runs a vendor rebuild, the USB drive has NVIDIA's (2026-09-25)

Found while preparing the Arch boot entry. Read-only queries on the Thor.

| | JetPack `/boot/Image` (running) | `raytone-thor-linux` `/boot/vmlinuz-raytone-thor-linux` |
| --- | --- | --- |
| Source | replaced after install: `dpkg --verify nvidia-l4t-kernel` reports `??5??????  /boot/Image` | `nvidia-l4t-kernel_6.8.12-tegra-39.2.1-20260806224157_arm64.deb` (NVIDIA repo, pinned sha256 in the manifest) |
| Build string | `6.8.12-1021-tegra (leetop@leetop) … #2 SMP PREEMPT Wed Aug 19 15:09:25 CST 2026` | `6.8.12-1021-tegra (buildbrain@…) … #1 SMP PREEMPT Thu Aug 6 21:56:04 PDT 2026` |
| Size | 52,484,608 bytes | 53,467,648 bytes |
| sha256 | `4eb45aad…6cf6688` | `8e3738af…f866761e` (same as the deb's `boot/Image`) |

The machine's vendor (Leetop) rebuilt the kernel from the same 6.8.12-1021-tegra tree. `dpkg --verify` over
the kernel, OOT, OpenRM and display-kernel packages shows only two other changed files besides the
regenerated `modules.*` indexes: `/boot/Image` and `updates/drivers/bluetooth/realtek/rtk_btusb.ko`. Every other
module JetPack loads is NVIDIA's stock build, so the vendor kernel and NVIDIA's modules are
ABI-compatible (they run together today).

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
- On JetPack's boot the xHCI firmware is reported at 5.82 s (`Firmware timestamp: 2025-09-08 …, Version 90.05`),
  before `Run /init` at 5.99 s, so it does not come from the initramfs. The USB drive appeared as `sda` at
  9.0 s; `rootwait=20` bounds the wait.
- `/etc/firmware` (in the command line as `firmware_class.path`) does not exist on JetPack or on the drive;
  the kernel falls back to `/usr/lib/firmware`.

Plan for the attended boot tests: the stock kernel first (`raytone-arch`); if it fails where the vendor
kernel would not, `raytone-arch-jetpack-kernel` boots the same USB root with JetPack's own `/boot/Image`,
read by GRUB from the NVMe (nothing copied or written). Bluetooth may differ with the stock `rtk_btusb`
(Slice 2).
