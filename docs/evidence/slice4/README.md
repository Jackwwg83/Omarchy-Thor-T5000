# Slice 4: Omarchy on the Thor's NVMe, dual boot with JetPack

Plan: APP (JetPack, p1) shrinks from 1905 GiB to 950 GiB, keeping its start, PARTUUID, type, name and
attributes; the rest becomes `RAYTONE_OMARCHY` (p12, about 955 GiB), a copy of the USB drive's root.
L4TLauncher's `extlinux.conf` on APP gets an `omarchy` entry, first and default, and JetPack's
`primary` entry stays byte for byte. QSPI, the ESP, UEFI variables and TPM NV are not touched.

Tools: `scripts/install-thor-nvme.sh` (steps `backup`, `shrink-app`, `create-root`, `clone`,
`boot-entry`; dry run unless `--write --confirm-serial`), `scripts/thor_nvme.py` (the table split,
the boot entry, the fstab; checked against `manifests/thor-nvme-gpt-2026-09-26.sfdisk` and
`manifests/jetpack-extlinux-2026-09-26.conf`), and in raytone-thor-omarchy 0.1.0-9 the initramfs
drop-in (`pcie_tegra264 phy_tegra194_p2u nvme`) and the pacman hook that copies later kernels and
initramfs images to APP.

## Before the run (2026-09-26/27, no NVMe write, no reboot)

| Component | State | Evidence |
|---|---|---|
| thor_nvme.py, install-thor-nvme.sh | **code**, tested with stubs | 330 tests OK (branch `feature/slice4-nvme`, 5467f97) |
| Codex review | GO | five rounds: NO-GO (initramfs, backup gate, atomic extlinux, GPT attributes, partx, resumable clone, backup exclusion) → NO-GO (SIGPIPE on the initramfs list, PHY module, quiet source) → NO-GO (clone not checked before the boot entry, loginctl failure) → NO-GO (journal recovery, exact kernel-sync config) → GO |
| Dry run on the Thor | **real data** | script sha256 `96701f64…c166c`, same as the repo. `backup`: would back up; `shrink-app`: refused, no backup; `create-root`, `clone`, `boot-entry`: refused, the NVMe has the original table. Nothing mounted, no backup directory |
| Initramfs with the drop-in | **real data** (test image in /tmp) | lists `pcie-tegra264.ko`, `phy-tegra194-p2u.ko`, `nvme.ko`, `nvme-core.ko` |
| raytone-thor-omarchy 0.1.0-9 | **code**, built on the drive | `~/raytone-build/s4/raytone-thor-omarchy/raytone-thor-omarchy-0.1.0-9-any.pkg.tar.xz`, `check_package.py`: 24 entries, 0 problems. Not published, not installed |
| Real `loginctl` and `dumpe2fs` formats | **real data** | `loginctl list-sessions --no-legend`: desktop `7 1000 nvidia seat0 5328 user tty2 no -` (refused), SSH `… - 22312 user - …` (allowed). `dumpe2fs -h`: `Filesystem state:         clean`; a mounted root lists `needs_recovery` |

Notes:
- `mkinitcpio` reports `module not found: crypto_lz4` from the systemd hook (NVIDIA's kernel has no
  `CONFIG_CRYPTO_LZ4`); it was already there before the drop-in, and the image is built.
- JetPack's apt: only `nvidia-l4t-bootloader`'s postinst rewrites `extlinux.conf`, and it is held,
  like the kernel packages, since Gate 0b. The holds stay until the project ends.

## Attended run (owner at the Thor, about 1 hour)

`D=/dev/disk/by-id/nvme-XG7000-2TB_2280_9C51015000022`, `S=9C51015000022`,
`B=/var/lib/raytone/nvme-backup` (on the USB drive; APP's 53 GB tar fits in its 173 GB free).

1. **Boot JetPack**: pick "JetPack on the internal NVMe" in GRUB.
2. **Publish 0.1.0-9** from JetPack: copy the package to `~/raytone/pkgs`, then
   `sudo RAYTONE_SIGNING_HOME=/home/nvidia/raytone/signing scripts/publish-thor-repo.sh --disk <JZAO by-id> --serial 2797824271339930 --write --confirm-serial 2797824271339930 ~/raytone/pkgs/raytone-thor-omarchy-0.1.0-9-any.pkg.tar.xz`.
3. **Reboot to Omarchy on the drive**: `omarchy-update -y`, then `sudo mkinitcpio -P` (a drop-in
   change does not trigger the kernel hook); `lsinitcpio /boot/initramfs-raytone-thor-linux.img`
   lists the four modules.
4. **Quiet source**: log out of the desktop and the text consoles (the greeter may stay); work
   over SSH. The script stops Ollama, Docker and containerd for the clone and starts them after.
5. In order, each `sudo scripts/install-thor-nvme.sh <step> --nvme $D --serial $S --backup-dir $B --write --confirm-serial $S`,
   checking the output before the next:
   1. `backup`: GPT dump, APP tar (gzip -t, sha256), extlinux.conf; copy `$B` to the Mac if time allows.
   2. `shrink-app`: e2fsck, resize2fs to 249037048 blocks, new table, kernel sees p1 and p12, e2fsck -n.
   3. `create-root`: ext4 `RAYTONE_OMARCHY` on p12.
   4. `clone`: two rsync passes, fstab to p12, `/etc/raytone/nvme-boot.conf`.
   5. `boot-entry`: checks the clone read-only, copies the kernel and initramfs to APP, then the new
      `extlinux.conf` (original kept as `extlinux.conf.jetpack`).
6. **Reboots**:
   1. Drive in: GRUB as before (the old path is intact).
   2. Drive out: the L4TLauncher menu, Omarchy by default; `findmnt /` is `nvme0n1p12`.
   3. Pick JetPack in the menu: it boots as before.
7. **On NVMe Omarchy**: desktop, Wi-Fi, audio, `cuda-smoke`, Ollama on the GPU, a Docker CDI
   container, `omarchy-update`, and a kernel sync check (`/boot/raytone-thor/` on APP matches).

## Rollback

| Where it fails | Back to |
|---|---|
| e2fsck or resize2fs | stop; the table is unchanged; APP from the tar if needed |
| partition table | `sfdisk $D < $B/nvme-gpt.sfdisk`, then e2fsck APP |
| NVMe boot menu or Omarchy entry | plug the drive in (the firmware boots it first), copy `extlinux.conf.jetpack` back over `extlinux.conf` on APP |
| Omarchy from the NVMe does not boot | pick JetPack in the L4TLauncher menu, or plug the drive in |
| JetPack broken | recovery-mode reflash from another computer (QSPI never touched), then APP from the tar |

## Results

| Step | State | Evidence |
|---|---|---|
| 2. publish 0.1.0-9 (from JetPack, 2026-09-27 00:1x) | **real data** | `published: raytone-thor-omarchy-0.1.0-9`; sha256 `b42daaee…29217` on the Mac, JetPack and the drive |
| 3. `omarchy-update -y`, `mkinitcpio -P` | **real data** | rc=0, `raytone-thor-omarchy 0.1.0-9`, `pacman -Qem` empty; over SSH it needs the session's `OMARCHY_PATH`, `PATH`, `XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS` (without them: `OMARCHY_PATH: unbound variable` in `omarchy-update-dev`, nothing installed). Initramfs 541 entries, all four modules listed (`lsinitcpio` needs root: the image is 0600) |
| 4. quiet source | **real data** | greeter only (`c1 sddm seat0 greeter tty1`), SSH sessions |
| 5.1 `backup` (00:18:48–00:51:38) | **real data** | rc=0; `jetpack-app.tar.gz` 35 848 626 527 bytes (gzip -t, `sha256sum -c` in the script); `extlinux.conf` and `nvme-gpt.sfdisk` hash the same as the manifests and as the live table; APP mounted `ro,norecovery` and unmounted after. Drive: 140 GB free |
| 5.2 onwards | pending | owner present, 2026-09-27 morning |
