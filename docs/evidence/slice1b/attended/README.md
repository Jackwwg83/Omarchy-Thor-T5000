# Slice 1b attended boot tests (owner present), 2026-09-25

Procedure: end of `docs/DECISIONS.md`. The raw device trees stay on the Thor (they carry the board serial number).

## Step 1–2: publish, then reboot through the default entry (14:48)

| Check | Result | Evidence |
| --- | --- | --- |
| `publish` checks passed: ready record, prefix, `grub-script-check`, grubenv without `next_entry`, modules. Loader renamed | real data | `publish.log` |
| Owner saw the GRUB menu on HDMI | real data | owner, by eye |
| Default `jetpack-nvme` chainloaded JetPack's L4TLauncher from the NVMe ESP; SSH back 62 s after the reboot request; GDM active | real data | `BootCurrent: 0005` (the USB option) in `efibootmgr-1.txt` |
| `/proc/cmdline` identical to the direct NVMe boot, `bl_prof_*` included | real data | `before-cmdline.txt`, `after1-cmdline.txt` |
| Device tree: 10,496 lines each; the only difference is `/chosen` `linux,uefi-mmap-{start,size}`, the UEFI memory map the EFI stub records at every boot | real data | `fdt-diff-1.txt`, `*-fdt.sha256` |
| `nvbootctrl dump-slots-info`, BIOS version, `uname -v` unchanged | real data | compared on the Thor |
| UEFI boot options: the firmware replaced its own auto-created USB option `Boot0004` (device path `…/USB(5,0)/USB(2,0)`) with `Boot0005` (`…/USB(5,0)/USB(1,0)`) and put it first in BootOrder | real data | `efibootmgr-1.txt` |

The boot-option change was made by the firmware, not by any script: edk2 refreshes its `auto_created_boot_option`
entries when a removable device's path changes. None of the project's tools writes UEFI variables. (A port move
during the night was the first guess. Step 3 shows the path simply differs from boot to boot; see below.)

## Step 3: one-shot `jetpack-grub`, JetPack's kernel and initrd loaded by GRUB (14:51)

| Check | Result | Evidence |
| --- | --- | --- |
| `arm-once` set `next_entry` and read it back; owner saw GRUB preselect the Slice 1a entry | real data | `arm-jetpack-grub.log`, owner by eye |
| JetPack came up without L4TLauncher: SSH back after 66 s, GDM active, no failed units, `nvidia-smi` shows NVIDIA Thor 595.78, nvidia modules loaded | real data | checked on the Thor |
| `/proc/cmdline` is the entry's command line (GRUB adds `BOOT_IMAGE=`); `bl_prof_*` is absent, as it is injected by L4TLauncher, and nothing needs it | real data | `after2-cmdline.txt` |
| Device tree: same as the L4TLauncher boot except `/chosen` `bootargs` (the command line) and `linux,uefi-mmap-*`. The tree comes from UEFI; L4TLauncher only sets `bootargs` | real data | `fdt-diff-2.txt` |
| `next_entry` cleared in grubenv after use, so the next boot takes the default again | real data | grubenv read on the Thor |
| Slots, BIOS version, `uname -v` unchanged | real data | compared on the Thor |

The firmware gives the drive a different USB device path on each boot: `USB(5,0)/USB(2,0)`, then `USB(5,0)/USB(1,0)`,
then `USB(2,0)/USB(1,0)`. It rebuilds its auto-created boot option each time (Boot0004 → 0005 → 0004) and
keeps it first in BootOrder (`usb-boot-option-paths.txt`). This is the firmware's own variable write, made with
the drive inserted whatever OS boots next. It does not come from the project and does not affect booting.

## Step 4: first Arch boot, `raytone-arch` (NVIDIA's kernel, no initramfs, `ro` root) (14:59–15:16)

The owner watched the console and ran commands there; the drive's journal was then read from JetPack (read-only mount).

| Check | Result | Evidence |
| --- | --- | --- |
| GRUB preselected the entry; the kernel booted, mounted the USB root; login prompt on tty1 | real data | owner by eye, photos |
| Boot marker: NVIDIA's kernel build `#1 SMP PREEMPT Thu Aug 6 21:56:04 PDT 2026`, the entry's command line | real data | `/var/lib/raytone/boots.log` on the drive |
| `systemd-fsck-root`: `RAYTONE_ROOT: clean`, then remounted read-write per fstab | real data | journal |
| Hardware watchdog in use: `NVIDIA Tegra186 WDT`, 2-minute timeout | real data | journal |
| Thermal guard every 30 s: 4 zones read, max 47.2 → 45.8 °C, nvfancontrol active, fan 1672–1720 rpm, `NV Power Mode: 120W` | real data | `/var/lib/raytone/thermal.log` on the drive |
| `nv-load-display-modules`, `nvpmodel`, `raytone-boot-marker` ran; `sshd`, NetworkManager active | real data | console, journal |
| PCIe: GPU, RTL8852BE Wi-Fi, RTL8125 2.5GbE, NVMe enumerated; `pcie_tegra264` loaded | real data | `lspci` (photo) |
| **No Wi-Fi and no 2.5GbE interface**: no driver bound to either card, so no network and no SSH | **failed** | `nmcli device status`, `modprobe rtw89_8852be` → not found |
| efivarfs read-only | not verified live | — |
| Dead-man fallback | **skipped** (owner rebooted with `systemctl reboot` at ~15:16) | journal shows a clean shutdown |

Why there is no network: of JetPack's 1,471 module files, exactly three belong to no package. All three
were added by the vendor: `updates/drivers/net/wireless/realtek/8852be.ko` (the Wi-Fi driver in use,
Realtek's out-of-tree driver), `updates/drivers/net/ethernet/realtek/r8125/r8125.ko` (the 2.5GbE driver in
use, Realtek 9.014.01-NAPI), and a second `rtk_btusb.ko` under `kernel/`. NVIDIA's kernel has neither
`CONFIG_RTW89` nor `CONFIG_R8169`. The vendor also installed uncompressed `rtw89/rtw8852b_fw*.bin` firmware.
The two drivers' `__versions` tables, 178 and 159 symbols, match NVIDIA's `Module.symvers`
(`nvidia-l4t-kernel-headers`, `nvidia-l4t-kernel-oot-headers`) exactly: no CRC mismatch, no missing symbol.

Other findings:
- ALARM's image enables `systemd-networkd` next to NetworkManager (`Failed to start Wait for Network to be Online`). To fix: disable networkd.
- The clock started at 2026-09-11 and jumped to the right time during boot; without network, timesyncd could not sync. To look at before pacman needs signatures.
- `nvethernet … failed to connect PHY` for eth1–3 also happens on JetPack (board wiring), so it is not a regression.
- `archlinux-keyring` refresh failed three times (no network), as expected.

## Step 4, second Arch boot: with `raytone-thor-leetop-nic` (15:36)

After step 4 the drive got the vendor NIC package (Codex: go) and networkd was masked, so the root
installer ran once more (`install-root-3.log`). Checks over SSH: `arch-boot-2-checks.txt`.

| Check | Result |
| --- | --- |
| SSH over Wi-Fi 28 s after boot (192.168.1.35, `wlP1p1s0`); internet reachable | real data |
| `8852be` and `r8125` loaded on NVIDIA's kernel; Wi-Fi firmware from `/etc/firmware`, version 0.29.29.5, as on JetPack; `enP2p1s0` present (no cable) | real data |
| Root `/dev/sda2` rw,noatime after the `ro` boot; no swap; nothing from the NVMe mounted | real data |
| **efivarfs mounted `ro`** | real data |
| `nvidia-smi`: NVIDIA Thor 595.78, 45 °C; `nvidia`/`nvidia-drm` from `updates/opensource-gpu-disp` (OpenRM), as on JetPack | real data |
| 120 W mode; nvfancontrol and the thermal guard active; fan 1718 rpm | real data |
| Hardware watchdog 2 min (runtime and reboot); `kernel.sysrq=1`; NTP synchronized | real data |
| No failed units; 52 units masked, among them tpm2-setup, pcrlogin@, networkd, firstboot | real data |
| Dead-man timer armed for 15:57:24 | real data |

To fix later:
- NVIDIA's `99-tegra-devices.rules` references a `debug` group that the drive lacks. Add it to raytone-thor-core's sysusers.
- `rtk_btusb` finds no `rtl8852bu_fw` or `rtl8852bu_config`. The Bluetooth firmware, like the drivers, is presumably vendor-installed on JetPack (Slice 2, Bluetooth).
- `ina238 2-0044: error configuring the device: -121` and `tegra-soc-hwpm … Invalid IP`: compare with JetPack.
- The early-boot clock starts at the last saved time until NTP syncs.

## Step 5: dead-man fallback (15:57)

Nobody created `/run/raytone-keep` on the second Arch boot. Twenty minutes after that boot, `raytone-deadman.service`
requested the reboot (`reboot requested from client … ('systemctl') (unit raytone-deadman.service)`). The system
synced and rebooted, GRUB took its default, and JetPack came back (vendor kernel `#2`, SSH at 88 s); `next_entry`
was empty. The owner saw the machine restart on its own. Evidence: `deadman-journal.txt`, the drive's journal read
from JetPack. (The journal's timestamps come from the early-boot clock, which lags until NTP syncs.)

Slice 1b still needs a cold boot (power off, power on) and the unplug test: without the drive, the Thor boots JetPack.
