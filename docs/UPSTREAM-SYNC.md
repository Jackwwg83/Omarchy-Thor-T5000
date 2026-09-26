# Following upstream Omarchy

The port runs upstream Omarchy unmodified: `packages/omarchy` and `packages/omarchy-settings` are
verbatim copies of [omarchy-pkgs](https://github.com/omacom/omarchy-pkgs) recipes, pinned in
`manifests/upstream-lock.json`. The Thor's changes live in `packages/raytone-thor-omarchy`, and
every upstream file it overrides or mirrors is pinned by hash, so a new release cannot slip past a
Thor file that was written against the old one. Upstream ships about one patch release a week.

## 1. Check

```sh
python3 scripts/upstream-bump.py            # report only; GITHUB_TOKEN=$(gh auth token) avoids rate limits
```

It refuses pre-releases (only `vX.Y.Z` tags are followed) and recipes whose `omarchy` and
`omarchy-settings` name different releases. The report has two parts:

- **GATE**: overridden (`overrides/UPSTREAM.sha256`) or mirrored (`WATCHED.sha256`) files that
  changed upstream.
- **REVIEW**: other upstream changes that can affect the port: new migrations, the install tree,
  `install/omarchy-base.packages`, the pacman, update, channel and hook scripts, the menu, SDDM.

## 2. Bump on a branch

```sh
git switch -c chore/omarchy-vX.Y.Z
python3 scripts/upstream-bump.py --write    # recipes + lock file; exit 2 if the gate changed
```

For each GATE file: read the upstream diff (the report links it), carry the change into the Thor
file where it applies (the override replaces the whole upstream file), then put the new upstream
hash in the `.sha256` file. The pinned-upstream tests (`tests/test_raytone_omarchy_apply.py`,
`tests/test_raytone_thor_omarchy_pkg.py`) stay red until every line matches the new release.

For each REVIEW item, in particular:

| Upstream change | What to check |
|---|---|
| `migrations/*.sh` added | Runs on every machine at `omarchy-update`. Anything x86_64-only, touching `pacman.conf`, the boot loader (Limine), Snapper, or NVIDIA desktop drivers needs a guard on the Thor |
| `install/**` added or changed | `raytone-omarchy-apply-system` runs upstream's whole install tree on a fresh install |
| `install/omarchy-base.packages` | Every new package must exist for aarch64 (ALARM, Omarchy's `edge/aarch64`), or get a line in `manifests/omarchy-arm-substitutions` |
| `bin/omarchy-refresh-pacman`, `omarchy-channel-set` | The Thor's pacman.conf comes back through the `pre-refresh-pacman` hook: check the hook still runs before the sync |
| `bin/omarchy-update*` | `omarchy-update` must still only sync against the configured repositories |
| `default/omarchy/omarchy-menu.jsonc` | New entries that cannot work on the Thor join the menu extension's hide list; renamed ids must be renamed there too |
| `default/sddm/`, `etc/sddm*` | The Thor greeter runs upstream's command (mirrored in `sddm-20-raytone-thor.conf`) and needs SDDM's last user (the installer seeds it) |

Then run the whole suite: `python3 -m unittest discover -s tests`.

When any Thor file changed (an override, a `.sha256` line, the menu list, the SDDM mirror), bump
`pkgrel` in `packages/raytone-thor-omarchy/PKGBUILD`: the new Omarchy needs the Thor layer that was
reviewed against it, and both are built and published together (steps 3 and 4).

Once every REVIEW item is checked and the GATE is closed:
`python3 scripts/upstream-bump.py --mark-reviewed` moves the review baseline to the new release
(until then, reruns keep listing the same REVIEW items).

Watch for upstream's pacman platform guard (omarchy-pkgs added it to omarchy-settings in
2026-09 as `default/libalpm/hooks/00-omarchy-platform-guard.hook`, conditional until the Omarchy
source carries it): it refuses packages tagged for another hardware platform, and how it classifies
the Thor decides whether the port's packages still install.

## 3. Build on the Thor (JetPack)

Sync the tree to the Thor (`~/raytone-src`), then build in the probe root:

```sh
NODEPS=1 spikes/gate0/build-pkg.sh packages/omarchy
NODEPS=1 spikes/gate0/build-pkg.sh packages/omarchy-settings
NODEPS=1 spikes/gate0/build-pkg.sh packages/raytone-thor-omarchy   # when its pkgrel moved
python3 scripts/check_package.py ~/raytone/pkgs/omarchy-X.Y.Z-1-aarch64.pkg.tar.xz ...
```

## 4. Publish and update

1. Back up the drive's root from JetPack first (the drive not mounted; a read-only mount and a
   tar to `~/raytone/backups/` on the NVMe).
2. Publish:
   `sudo RAYTONE_SIGNING_HOME=/home/nvidia/raytone/signing scripts/publish-thor-repo.sh --disk /dev/disk/by-id/usb-... --serial S --write --confirm-serial S ~/raytone/pkgs/omarchy-X.Y.Z-1-*.pkg.tar.xz ~/raytone/pkgs/omarchy-settings-X.Y.Z-1-*.pkg.tar.xz`
   plus the rebuilt `raytone-thor-omarchy` when it changed
   It signs with the key the drive already trusts, adds exactly those files to `[raytone-thor]`
   and checks the database lists them. It installs nothing.
3. Boot the drive and run `omarchy-update`. Answer **no** to removing orphaned packages and to
   the reboot offer (over SSH, `omarchy-update -y` does both), then check
   `pacman -Q omarchy omarchy-settings raytone-thor-omarchy`, `omarchy-version`,
   `systemctl --failed`, and `cmp /etc/pacman.conf /usr/share/raytone-thor/pacman/pacman.conf`.
4. Merge the branch with a PR, the evidence in the description.

## Other packages that follow upstream

- **Hyprland** (`packages/hyprland`): the port's build of Arch Linux ARM's recipe with
  `egl-render-node.patch`. `[raytone-thor]` comes first, so the port's build wins even when ALARM
  moves on; when ALARM ships a new Hyprland, rebuild from its recipe with the patch, and check the
  patch upstream (once Hyprland accepts it, the port can drop its build).
- **nf_tables modules** (`packages/raytone-thor-nft-modules`) and the **vendor NIC modules**
  (`packages/raytone-thor-leetop-nic`): built for exactly `raytone-thor-linux`'s kernel; rebuild
  whenever that kernel changes. `linux-aarch64` is in `IgnorePkg`, so ALARM's kernel never replaces it.
