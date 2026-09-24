# Jetson AGX Thor inventory (baseline JetPack install)

Read-only survey of the test machine on 2026-09-24, before any port work.
Serial numbers, MAC addresses, partition UUIDs and network addresses are omitted.

## Software

| Item | Value |
| --- | --- |
| Board | NVIDIA Jetson AGX Thor Developer Kit, `nvidia,p4071-0000+p3834-0008`, `nvidia,tegra264` |
| JetPack | 7.2.1-b49 (`nvidia-jetpack`) |
| L4T | R39.2.1, GCID 46758480, `KERNEL_VARIANT: oot`, userspace lib dir `usr/lib/aarch64-linux-gnu/nvidia` |
| OS | Ubuntu 24.04.4 LTS |
| Kernel | `6.8.12-1021-tegra`, 4 KiB pages, `CONFIG_MODULE_COMPRESS_NONE` |
| GPU driver | OpenRM `nvidia.ko` 595.78 from `updates/opensource-gpu-disp/`, Dual MIT/GPL |
| CUDA | 13.2.2 (`cuda-toolkit-13-2`), nvcc 13.2.86 |
| TensorRT | 10.16.2.10 |
| Container toolkit | nvidia-container-toolkit / libnvidia-container1 1.19.1, mode `auto` (CSV), CDI spec in `/var/run/cdi/nvidia.yaml`; Docker not installed |
| Desktop | GDM, GNOME on Xorg |
| Power | nvpmodel `120W`, nvfancontrol active |

70 `nvidia-l4t-*` packages are installed from `repo.download.nvidia.com/jetson/{common,som,ffmpeg}` suite `r39.2`.
Largest: 3d-core (345 MB), bootloader (238 MB), cuda-openrm and cuda-nvgpu (174 MB each), kernel-partitions (126 MB), kernel (124 MB).

## Boot

- UEFI firmware in QSPI. Device tree only, no ACPI tables.
- ESP on NVMe holds only `EFI/BOOT/BOOTAA64.efi` (L4TLauncher), which reads `/boot/extlinux/extlinux.conf`.
- The extlinux entry has no `FDT` line; the kernel uses the device tree handed over by the firmware.
- UEFI BootOrder: USB (auto-created) first, then NVMe, then Enter Setup, BootManagerMenuApp, UEFI Shell.
- Kernel command line as booted:

```
root=PARTUUID=<nvme-root> rw rootwait rootfstype=ext4 mminit_loglevel=4
earlycon=tegra_utc,mmio32,0xc5a0000 console=ttyUTC0,115200
firmware_class.path=/etc/firmware fbcon=map:0 efi=runtime audit=1
audit_backlog_limit=8192 swiotlb=2048 video=efifb:off console=tty0
bl_prof_dataptr=<addr> bl_prof_ro_ptr=<addr>
```

  The extlinux `APPEND` line starts with `${cbootargs}`; the `bl_prof_*` arguments are the part the boot loader adds.
- Built in: `USB_XHCI_TEGRA`, `USB_STORAGE`, `EXT4_FS`, `DRM`, `EFI_STUB`. Modules: `BLK_DEV_NVME`, `USB_UAS`, `DRM_TEGRA`, `BTRFS_FS`.

NVMe layout (JetPack default): `APP` root (ext4, whole disk less ~3 GB), `recovery`, `recovery-dtb`, `esp`,
`A_reserved_on_user`, `recovery_alt`, `recovery-dtb_alt`, `esp_alt`, `B_reserved_on_user`, `UDA`, `reserved`.

## Graphics

| DRM node | Driver | Role |
| --- | --- | --- |
| `card1` / `renderD128` | `drm` on `nvidia,tegra264-host1x` | host1x |
| `card2` / `renderD129` | `nvidia` | GPU, PCI `10de:2b00` "NVIDIA Thor" |
| `card3` / `renderD130` | `nv_platform` on `nvidia,tegra264-display` | display; connectors DP-1..3, HDMI-A-1 |

- HDMI-A-1 connected, preferred mode 2560×1440 on the test monitor.
- Loaded modules include `nvidia_drm`, `nvidia_modeset`, `nvidia_uvm`, `nvidia`, `tegra_drm`, `host1x`, `tegra_dce`, `nvhwpm`.
- GBM backends: `dri_gbm.so`, `nvidia-drm_gbm.so`, `tegra_gbm.so`.
- EGL external platforms: `nvidia_gbm`, `nvidia_wayland`, `nvidia_xcb`, `nvidia_xlib`; glvnd vendors `10_nvidia`, `50_mesa`.
- Vendor libraries: `libnvidia-eglcore.so.595.78`, `libnvidia-egl-gbm.so.1.1.0`, `libnvidia-egl-wayland.so.1.1.11`,
  `libGLX_nvidia.so.0`, `libnvidia-ml.so.1`, Vulkan loader 1.4.321, Vulkan SC.
- `nvidia-smi` reports driver 595.78, CUDA 13.2, one GPU "NVIDIA Thor", MIG disabled.

## Devices

| Function | Hardware / driver |
| --- | --- |
| CPU | 14 Arm cores, one cluster |
| Memory | 122 GiB visible, unified with the GPU |
| Storage | 2 TB NVMe (INNOGRIT IG5236 controller) |
| Wi-Fi | Realtek RTL8852BE, `rtw89_8852be` |
| Ethernet | Realtek RTL8125 2.5GbE `r8125`; four MGBE interfaces `nvethernet` (out-of-tree) |
| Bluetooth | Realtek, `rtk_btusb` |
| Audio | `tegra-hda` (HDMI/DP), `tegra-ape` |
| CAN | four `mttcan` interfaces |
| USB device mode | `usb0` / `usb1` configfs gadget (`l4tbr0` bridge) |
| Debug serial | on-board quad USB-UART bridge (`cdc_acm`) |

USB: two xHCI root hubs (`tegra-xusb`); a USB 3.2 Gen1 stick in a Type-A port links at 5000 Mb/s on the 10 Gb/s bus.
Only partly inserted, the same stick fell back to 480 Mb/s. In the Type-C port tried, it was not detected at all.

## NVIDIA services enabled on JetPack

`nv-graphics`, `nv-load-display-modules`, `nv-load-gpu-libs`, `nvfancontrol`, `nvpmodel`, `nvpower`,
`nvcpupowerfix`, `nv_hugetlbfs_init`, `nv_nvsciipc_init`, `nv_nvsciipc_preinit`, `nvidia-cdi-refresh.{path,service}`,
`nvidia-pva-allowd`, `nvargus-daemon`, `nvweston`, `nv-tee-supplicant`, `nv-ftpm-device-provision`, `nv-kdump`,
`nv-l4t-bootloader-config`, `nv-l4t-usb-device-mode`, `nv-oobe`, `nv-power-adapter-check`,
`nv-rootfs-validation-config`, `nvfb-ping-config`, `nvfb-ssh-keygen`, `nvfb-swapfile`, `nvfb-tegra-hda`,
`nvfb-udev`, `nvmemwarning`, `nvmefc-boot-connections`, `nvmf-autoconnect`.

The port must not carry `nv-l4t-bootloader-config`, `nv-rootfs-validation-config`, `nv-oobe` or the `nvfb-*`
first-boot units; see the prohibited list in [PLAN.md](PLAN.md).
