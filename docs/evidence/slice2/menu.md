# Omarchy menu on the Thor: what is hidden and why

Read-only audit on the Thor, 2026-09-26, of all 333 ids in Omarchy 4.0.4's
`default/omarchy/omarchy-menu.jsonc`. Every `when:` was evaluated as the desktop user. Package
availability was checked with `pacman -Sp` against the configured repositories (no sync), and AUR
packages through the AUR RPC and their PKGBUILDs. `omarchy-pkg-add` runs `pacman -S` only, so a
package missing from core/extra/alarm/aur or Omarchy's `edge/aarch64` fails even when the AUR has
an aarch64 build.

## Hidden by `raytone-thor-menu-extension` (24)

| id | Why it cannot work on the Thor | Evidence |
|---|---|---|
| system.suspend | sleep is masked on this board | `systemctl is-enabled suspend.target sleep.target`: masked, masked |
| install.service.dropbox | no aarch64 package | `pacman -Sp dropbox`: target not found; AUR dropbox, nautilus-dropbox: `arch=(x86_64)` |
| install.service.spotify | x86_64 only | not found; AUR `arch=('x86_64')`, amd64 .deb source |
| install.service.bitwarden | desktop app x86_64 only | `bitwarden` not found (bitwarden-cli exists) |
| install.browser.edge | x86_64 only | AUR microsoft-edge-stable-bin `arch=('x86_64')` |
| install.terminal.ghostty | not built for aarch64 | `pacman -Sp ghostty`: target not found |
| install.ai.ollama | no package (`ollama`, `ollama-cuda`) | `pacman -Ssq ollama`: nothing. Slice 3 brings Ollama with CUDA |
| install.ai.lm-studio | x86_64 only | lmstudio-bin not found; AUR `arch=('x86_64')` |
| install.ai.grok-bot | x86_64 only | not found; AUR `arch=('x86_64')` |
| install.ai.t3-code | x86_64 only | t3code-bin not found; AUR `arch=('x86_64')` |
| install.ai.hermes | no package | hermes-desktop in no sync database |
| install.gaming.steam | needs multilib and lib32 | steam, lib32-nvidia-utils not found; omarchy-steam-fex: could not satisfy dependencies |
| install.gaming.minecraft | x86_64 only | minecraft-launcher not found; AUR `arch=('x86_64')` |
| install.gaming.heroic | x86_64 only | heroic-games-launcher-bin not found; AUR `arch=('x86_64')` |
| install.gaming.lutris | Wine stack missing | umu-launcher, wine-staging, wine-mono, wine-gecko not found |
| install.gaming.battlenet | Wine stack and lib32 missing | umu-launcher not found; runs a Windows x86 installer |
| install.gaming.geforce-now | x86-64 installer | GeForceNOWSetup.bin ELF `e_machine` 0x3e; no FEX |
| install.gaming.retroarch | one transaction with missing cores fails whole | libretro-ppsspp, libretro-uae-git not found |
| install.gaming.xbox-controllers | DKMS needs kernel headers | `/usr/lib/modules/6.8.12-1021-tegra/build` absent; no L4T headers package in the repositories |
| setup.direct-boot | UKI and EFI boot entries | no efibootmgr, no `/boot/EFI/Linux`, efivarfs read-only; UEFI variables are off limits on this board |
| update.password.drive | no LUKS | `lsblk -o FSTYPE`: no crypto_LUKS |
| style.unlock | Plymouth is not in this boot | no `splash` on the kernel command line, no plymouth hook; it would also rebuild the Thor's initramfs (`mkinitcpio -P`) |
| update.config.plymouth | as style.unlock | as style.unlock |
| update.firmware | firmware capsules are off limits on this board | fwupd exists with one ESRT entry; the project never writes QSPI or capsules |

## Already hidden by upstream's own `when:` on the Thor

system.hibernate (no swap), setup.reset (root is not btrfs), setup.security.fingerprint (no
reader), the webcam capture entry (no `/dev/video*`), laptop, hybrid-GPU, touchpad, haptics and
touchscreen entries, and `remove.*` for packages that are not installed.

## Shown, to test with the owner at the Thor

- trigger.capture.screenrecord.* : `gpu-screen-recorder --info` offers only the portal capture and
  software H.264 (no libcuda for it); the default script path uses KMS capture.
- install.windows: `/dev/kvm` exists and the image has an arm64 tag; Windows on ARM under L4T KVM
  is untested.
- update.hardware.trackpad: no i2c HID touchpad drivers; does nothing.
- install.gaming.retro-launcher: needs libretro cores, which only a manual RetroArch install brings.

Cleared as working on aarch64 (sampled): Chrome, Brave, Zen, 1Password, NordVPN, VSCode, Cursor,
Sublime, Zed, ChatGPT/Codex desktop, Perplexity, Dictation (voxtype), emacs, fonts, mise, rustup,
opam, Docker.
