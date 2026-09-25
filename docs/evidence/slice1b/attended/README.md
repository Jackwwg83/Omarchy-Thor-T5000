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
