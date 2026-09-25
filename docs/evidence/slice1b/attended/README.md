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
entries when a removable device's path changes. The drive was moved to another USB-A port during the night,
and there had been no reboot since, so this boot was the first to see the new path. None of the project's tools
writes UEFI variables.

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
