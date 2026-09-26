# Slice 2.1 evidence: upstream Omarchy 4.0.4 on the Jetson AGX Thor (USB drive)

Attended, 2026-09-25/26. The owner was at the Thor; checks ran over SSH from the laptop (LAN).
Every row is **real data** from the Thor unless marked otherwise.

## Install

`install-thor-omarchy.sh --write` from JetPack (commit 56b9b43), 907 packages, exit 0:
`installed: Omarchy 4.0.4-1 with the Thor layer on /dev/sda2`. Log on the Thor's NVMe:
`~/raytone/evidence/slice2-install.log`. Backup of the drive's root before the install:
`~/raytone/backups/usb-root-before-omarchy.tar.gz`.

## First boot (2026-09-25 22:56): three faults

| Symptom | Root cause | Fix |
|---|---|---|
| SDDM rejects the correct password (tty2 login with it works) | Omarchy's greeter is password-only and logs in `userModel.lastUser`; SDDM's journal shows `Authentication for user "" failed`. The Omarchy ISO seeds `/var/lib/sddm/state.conf` (omarchy-iso `configure_login`); a non-ISO install has none | a639251: the installer seeds the last user and session and `RememberLastUser`, as the ISO does for unencrypted installs (no autologin) |
| Wi-Fi not connected | Omarchy's aarch64 dependency `iwd` ships `80-iwd.link` (`NamePolicy=keep kernel`): the card is `wlan0`, the profile copied from JetPack was bound to `wlP1p1s0` | a639251: `interface-name` is dropped from Wi-Fi profiles |
| No ping or SSH although `ufw status` lists 22/tcp | NVIDIA's kernel has `# CONFIG_NFT_LIMIT is not set`. iptables-nft turns ufw's `-m limit` into the nf_tables limit expression, `iptables-restore` fails (`RULE_APPEND failed (No such file or directory)`), `ufw.service` fails and only the default DROP policy is left. Reproduced by hand: `iptables -A t -m limit ...` fails, `-j LOG`, `-m conntrack`, `-m comment` work | 4866d23: `raytone-thor-nft-modules` builds `nft_limit` from NVIDIA's R39.2.1 kernel source against the pinned headers deb; vermagic `6.8.12-1021-tegra SMP preempt mod_unload modversions aarch64`, the same as NVIDIA's modules |

The mouse was fine (it had gone to sleep). The screensaver exits on a key press, not a click: that is
upstream's `omarchy-screensaver` (it exits on keyboard input or loss of focus), left as is.

## Reboot acceptance (2026-09-26 00:05, `raytone-arch` chosen at the GRUB menu)

| Check | Result |
|---|---|
| SSH through the firewall | 2 min after the reboot command |
| Wi-Fi | `wlan0:wifi:connected:<home Wi-Fi>`, 192.168.1.35/24, no manual step |
| UFW | `ufw.service` active, 0 failures in its journal; `nft_limit` autoloaded from `/lib/modules/6.8.12-1021-tegra/updates/net/netfilter/nft_limit.ko` (15 users); `ufw-user-input` has `--dport 22 -j ACCEPT` and `--dport 5353 -j ACCEPT` |
| SDDM | greeter on tty1 remembers `nvidia`; the owner logged in with the password |
| Session | `Type=wayland`, `Class=user`, `State=active`; Quickshell (`quickshell -n -p /usr/share/omarchy/shell`) running |
| Display | `HDMI-A-1 2560x1440@74.97100`, scale 1 |
| Renderer | Hyprland 0.56.2 (the port's build 0.56.2-3.1), `Vendor: NVIDIA Corporation`, `Renderer: NVIDIA Thor/PCIe`, display device `/dev/dri/card3` |
| Packages | omarchy 4.0.4-1, omarchy-settings 4.0.4-1, raytone-thor-omarchy 0.1.0-1, raytone-thor-nft-modules 6.8.12.l4t39.2.1-1 |
| Failed units | `bluetooth.service` only (vendor Bluetooth firmware and driver: Slice 2.2) |

![Omarchy desktop at first login](desktop-first-login.jpg)

## State

- The fixes for the three faults were applied to the running drive by hand first (SDDM state,
  `nmcli connection modify ... connection.interface-name ""`, `pacman -U raytone-thor-nft-modules`),
  then the reboot checked them. A fresh `install-thor-omarchy.sh` run has them in code (tests pass) but
  has **not** been rerun on the drive: code, not deployed-path, for a clean install.
- raytone-thor-omarchy 0.1.0-2 (which only adds the nft dependency) is committed, not yet built.
- Do not click the "Update System" notification until Slice 2.2 gates `omarchy-update` and
  `omarchy-refresh-pacman` (Codex review, round 2).

## Slice 2.2, first night (2026-09-26, owner away; no reboot)

| Item | State | Evidence |
|---|---|---|
| `omarchy-refresh-pacman` / channel switch keep the Thor's pacman.conf | **real data** | upstream x86_64 template copied over `/etc/pacman.conf`, then `omarchy-hook pre-refresh-pacman`: `cmp` with the Thor template passes, multilib 1 → 0 (sync step not run) |
| `omarchy-update` | not run (Codex: no-go until a fresh backup and a real update to install) | `checkupdates`: 0 pending; 106/106 migrations done; post-update hooks only send invitations; `pacman -Qtdq` empty; `pacman -Qem` lists raytone-thor-nft-modules (installed with `pacman -U`, not yet in `[raytone-thor]`) |
| Publishing to `[raytone-thor]` from JetPack | code (tests) | `scripts/publish-thor-repo.sh` |
| Following upstream | code (tests) + real check | `scripts/upstream-bump.py` against GitHub: `up to date: Omarchy v4.0.4` |
| Menu: 24 entries hidden | **real data** (file); look not yet checked | [menu.md](menu.md); the live file parses with Omarchy's JSONC rules to 24 overrides |
| PipeWire audio | **real data** for devices; no sound test yet | WirePlumber had no ALSA plugin (`api.alsa.enum.udev could not be loaded`): the ISO layer's `pipewire-alsa`, `pipewire-pulse`, `pipewire-jack` (replacing jack2) etc. installed; now 2 devices, HDA and APE |
| HDMI audio | **empty** | HDA's four HDMI outputs "not available": ELD `monitor_present 0`, `eld_valid 0`, although the monitor's EDID has a CEA audio data block (LPCM). The display driver does not hand the ELD to the HDA codec; compare on JetPack. The default sink is APE's analog stereo, which likely goes nowhere |
| Bluetooth | bluetoothd **real data**; adapter **empty** | `bluetooth.service` failed with 203/EXEC: NVIDIA's drop-in runs `/usr/libexec/bluetooth/bluetoothd` (fixed in raytone-thor-firmware 39.2.1-3; masked on the drive meanwhile by an empty `/etc/systemd/system/bluetooth.service.d/nv-bluetooth-service.conf`, to remove after the update). `rtk_btusb` (bda:b85b, RTL8852BU) fails: `Direct firmware load for rtl8852bu_fw failed with error -2`; the vendor files are on JetPack |
| `debug` group | code (tests) | raytone-thor-core 39.2.1-3 |

## Slice 2.2, attended (2026-09-26 11:36–12:40, owner at the Thor)

| Item | State | Evidence |
|---|---|---|
| Menu look | **real data** | owner: no Suspend under System, no Steam/Lutris, no Ghostty |
| Screen recording | **real data** | full-screen recording 2560x1440 with content (software libx264, no hardware encoder). The owner's first try recorded 76x74: `omarchy-capture-region smart` takes a drag over 20 px² as a region, upstream behaviour |
| Fresh backup | **real data** | JetPack, drive mounted `ro,noload`: `~/raytone/backups/usb-root-omarchy-2026-09-26.tar.gz` (7.9 GB) and `usb-esp-2026-09-26.tar.gz`; `gzip -t` both OK; only socket files skipped |
| Builds on JetPack | **real data** | raytone-thor-firmware 39.2.1-3 (no bluetooth drop-in), raytone-thor-core 39.2.1-3 (`g debug`), raytone-thor-leetop-nic 2026.09.26-1 (`etc/firmware/rtl8852bu_{fw,config}`); `check_package.py` 0 problems on all five published packages |
| Publishing | **real data** | `publish-thor-repo.sh --write`: key validity in the drive's keyring checked, all five verified from staging, database lists them |
| **First `omarchy-update`** | **real data** | `omarchy-update -y` over SSH (no TTY: orphans kept, reboot declined), rc=0: 15 packages (the three port builds, systemd 262, omarchy-nvim, …); after: `pacman -Qem` empty, `/etc/pacman.conf` equals the Thor template, `omarchy-version` 4.0.4-1, no failed units, udev "Failed to resolve group" 11 → 0. Two post-update invitation hooks failed only for want of a notification daemon in the SSH environment. `sudo -v` in `omarchy-update-stay-awake` asks for a password under `verifypw=all`; the bring-up sudoers file got `Defaults:nvidia verifypw=any` (removed with it at the end) |
| Bluetooth | **real data** | NVIDIA's `rtk_btusb` with the vendor firmware: `load_firmware done`, `download_data done`, controller `Powered: yes`; the owner's phone paired, bonded, trusted, connected (A2DP source offered). Bluetooth audio output not tested (no Bluetooth headset) |
| HDMI audio | **real data** | this boot the ELD is valid (`monitor_present 1`); `HDMI1` sink available; a test tone heard through the monitor's headphone jack (the monitor has no speakers). The earlier empty ELD looked like a boot-order race; watch it |
| Headphone jack on the Thor | **real data** by hand; boot service **code** | RT5640 on I2S4 (device tree `audio-codec@1c` → `i2s@92b0000`, prefix I2S4); `I2S4 Mux` was None and the codec's HP channel off. With `I2S4 Mux=ADMAIF1` and the HP path switched on, the test tone was heard. `raytone-thor-audio-route.service` (raytone-thor-core 39.2.1-4) does that at boot; run by hand on the Thor it switched `HP Channel` off→on; not yet built or published |

## Slice 2.3 (2026-09-26 16:18–16:25, owner at the Thor)

| Item | State | Evidence |
|---|---|---|
| raytone-thor-core 39.2.1-4 (headphone routing at boot) | **real data** | built on JetPack (`check_package.py` 0 problems), published, installed by the second `omarchy-update -y` (rc=0; `pacman -Qem` empty; pacman.conf the Thor template) |
| Boot menu | **real data** | `install-thor-boot.sh install --entries docs/evidence/slice2/entries-2.json --default raytone-arch` then `publish`, both rc=0; menu: "RaytoneOS Omarchy (USB drive)" (default), "JetPack on the internal NVMe", retry, UEFI menu |
| Omarchy by default | **real data** | reboot with no key pressed: Omarchy up, SSH 66 s after the reboot command; twice |
| Dead-man retired | **real data** | `/run/raytone-keep` first, then `systemctl disable --now raytone-deadman.timer`: disabled / inactive; the next boot ran with no keep file and was not rebooted. The thermal guard stays enabled and active. Recovery is by hand: JetPack in GRUB's 3 s menu, or unplug the drive |
| Headphone routing at boot | **real data**, heard by the owner (19:03, no manual mixer change since the 16:23 boot) | `raytone-thor-audio-route.service` started by udev with the APE card, `Finished`; after boot `I2S4 Mux` = ADMAIF1, `CVB-RT HP Channel Switch` = on,on |
