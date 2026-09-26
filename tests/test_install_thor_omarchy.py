"""install-thor-omarchy.sh with stubbed tools: refusals, order, repository, Omarchy setup, firewall, checks."""
import os
import pathlib
import re
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install-thor-omarchy.sh"
SERIAL = "2797824271339930"
SIZE = 248145510400
OMARCHY_KEY = "40DFB630FF42BCFFB047046CF0134EE680CAC571"
PKGS = ("omarchy-4.0.4-1-aarch64.pkg.tar.xz", "omarchy-settings-4.0.4-1-aarch64.pkg.tar.xz",
        "raytone-thor-omarchy-0.1.0-1-any.pkg.tar.xz", "raytone-thor-graphics-39.2.1-1-aarch64.pkg.tar.xz",
        "hyprland-0.56.2-3.1-aarch64.pkg.tar.xz", "raytone-thor-nft-modules-6.8.12.l4t39.2.1-1-aarch64.pkg.tar.xz")
BASE = "chromium\nnvim\nvi\nobs-studio\nomarchy-nvim\n# comment\n\nsddm\n"

STUB = textwrap.dedent("""\
    #!/bin/bash
    name=$(basename "$0")
    if [[ $name == setpriv ]]; then echo "setpriv $*" >> "$STATE/calls"; while [[ $1 != -- ]]; do shift; done; shift; exec "$@"; fi
    echo "$name $*" >> "$STATE/calls"
    case $name in
      lsblk)
        case "$*" in
          *TYPE,TRAN,SERIAL,SIZE*) cat "$STATE/disk" ;;
          *PKNAME*) echo nvme0n1 ;;
          *PARTLABEL,FSTYPE*) printf 'sdz\\nsdz1 RAYTONE_ESP vfat\\nsdz2 RAYTONE_ROOT ext4\\n' ;;
        esac ;;
      findmnt) echo /dev/nvme0n1p1 ;;
      gpg)
        case "$*" in
          *--list-secret-keys*) [[ -f $STATE/no-key ]] || echo "fpr:::::::::ABCDEF0123456789ABCDEF0123456789ABCDEF01:" ;;
          *--detach-sign*) for a in "$@"; do f=$a; done; touch "$f.sig" ;;
          *--export*) echo PUBKEY ;;
        esac ;;
      chroot)
        user=root
        if [[ $1 == --userspec=* ]]; then user=${1#--userspec=}; user=${user%%:*}; shift; fi
        shift  # the root
        if [[ $1 == /usr/bin/env ]]; then shift; [[ $1 == -i ]] && shift; while [[ $1 == *=* ]]; do echo "env $1" >> "$STATE/calls"; shift; done; fi
        echo "in-chroot[$user] $*" >> "$STATE/calls"
        if [[ $1 == pacman && " $* " == *" omarchy "* ]]; then
          mkdir -p "$TARGET/usr/share/omarchy/install"; printf '%s' "$BASE" > "$TARGET/usr/share/omarchy/install/omarchy-base.packages"
        fi
        if [[ $1 == systemctl && $2 == is-enabled && -f $STATE/disabled-$3 ]]; then exit 1; fi
        if [[ $1 == repo-add ]]; then touch "$TARGET/var/lib/raytone/repo/raytone-thor.db.tar.gz"; fi
        if [[ $1 == raytone-omarchy-apply-system ]]; then
          [[ -f $STATE/apply-fails ]] && exit 3
          # what the Thor firewall override leaves behind
          mkdir -p "$TARGET/etc/ufw"
          [[ -f $STATE/no-ssh-rule ]] || echo "### tuple ### allow tcp 22 0.0.0.0/0 any 0.0.0.0/0 in comment=raytone-ssh" >> "$TARGET/etc/ufw/user.rules"
          echo "### tuple ### allow udp 5353 0.0.0.0/0 any 0.0.0.0/0 in comment=raytone-mdns" >> "$TARGET/etc/ufw/user.rules"
          echo "ENABLED=yes" > "$TARGET/etc/ufw/ufw.conf"
        fi
        ;;
    esac
    exit 0
    """)


class InstallThorOmarchyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.tmp.name)
        self.state, self.bin, self.sys, self.target = t / "state", t / "bin", t / "sys", t / "target"
        self.pkgs, self.etc, self.gnupg = t / "pkgs", t / "hostetc", t / "gnupg"
        for d in (self.state, self.bin, self.sys / "block" / "sdz" / "holders", self.target / "etc",
                  self.pkgs, self.etc, self.gnupg, t / "rules"):
            d.mkdir(parents=True)
        (self.target / ".raytone-unpacked").write_text("ArchLinuxARM-aarch64-latest.tar.gz x\n")
        (self.target / "etc" / "arch-release").write_text("")
        for tool in ("lsblk", "findmnt", "swapon", "blkid", "mount", "umount", "chroot", "udevadm", "sync",
                     "setpriv", "gpg"):
            (self.bin / tool).write_text(STUB)
            (self.bin / tool).chmod(0o755)
        dev = t / "dev"
        (dev / "disk" / "by-id").mkdir(parents=True)
        for n in ("sdz", "sdz1", "sdz2"):
            (dev / n).touch()
        self.link = dev / "disk" / "by-id" / f"usb-JZAO_USB3.2_Gen1_{SERIAL}-0:0"
        self.link.symlink_to("../../sdz")
        (self.state / "disk").write_text(f"disk usb {SERIAL} {SIZE}\n")
        for p in PKGS:
            (self.pkgs / p).write_bytes(b"pkg")
        (self.etc / "resolv.conf").write_text("nameserver 1.1.1.1\n")
        self.rules = t / "rules"

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", STATE=str(self.state), TARGET=str(self.target),
                   BASE=BASE, RAYTONE_SYS=str(self.sys), RAYTONE_SKIP_ROOT_CHECK="1", RAYTONE_NO_UNSHARE="1",
                   RAYTONE_TARGET_MOUNT=str(self.target), RAYTONE_HOST_ETC=str(self.etc),
                   RAYTONE_UDEV_RULES=str(self.rules), RAYTONE_SIGNING_HOME=str(self.gnupg))
        return subprocess.run(["bash", str(SCRIPT), "--disk", str(self.link), "--serial", SERIAL,
                               "--packages", str(self.pkgs), "--user", "nvidia", *args],
                              env=env, capture_output=True, text=True)

    def write(self):
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r

    def calls(self):
        f = self.state / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def chroot(self, user="root"):
        prefix = f"in-chroot[{user}] "
        return [c[len(prefix):] for c in self.calls() if c.startswith(prefix)]

    def index(self, prefix, user="root"):
        return next(i for i, c in enumerate(self.chroot(user)) if c.startswith(prefix))

    def test_dry_run_mounts_nothing(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry run", r.stdout)
        self.assertFalse([c for c in self.calls() if c.startswith(("mount", "chroot"))])

    def test_refuses_missing_packages(self):
        for p in PKGS:
            with self.subTest(p=p):
                (self.pkgs / p).rename(self.pkgs / (p + ".away"))
                r = self.run_script()
                self.assertNotEqual(r.returncode, 0)
                self.assertIn(f"package {re.sub(r'-[0-9].*', '', p)} not found", r.stderr)
                (self.pkgs / (p + ".away")).rename(self.pkgs / p)

    def test_refuses_a_drive_without_the_raytone_root(self):
        (self.target / ".raytone-unpacked").unlink()
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("install-thor-root.sh", r.stderr)
        self.assertFalse(self.chroot())

    def test_packages_are_signed_and_served_from_the_drives_repository(self):
        self.write()
        repo = self.target / "var" / "lib" / "raytone" / "repo"
        for p in PKGS:
            with self.subTest(p=p):
                self.assertTrue((repo / p).exists())
                self.assertTrue((repo / (p + ".sig")).exists())
        adds = [c for c in self.chroot() if c.startswith("repo-add -q /var/lib/raytone/repo/raytone-thor.db.tar.gz ")]
        self.assertEqual(len(adds), 1, self.chroot())
        for p in PKGS:
            self.assertIn(f"/var/lib/raytone/repo/{p}", adds[0].split())
        self.assertEqual((self.target / "etc" / "pacman.conf").read_text(),
                         (ROOT / "packages" / "raytone-thor-omarchy" / "pacman" / "pacman.conf").read_text())
        self.assertTrue(any(c.startswith("pacman-key --lsign-key ABCDEF0123456789ABCDEF0123456789ABCDEF01")
                            for c in self.chroot()))

    def test_the_newest_build_is_added_last(self):
        # repo-add keeps the entry it adds last; name order would put -10 before -9
        for rel in ("9", "10"):
            (self.pkgs / f"leetop-nic-1.0-{rel}-aarch64.pkg.tar.xz").write_bytes(b"pkg")
        self.write()
        add = next(c for c in self.chroot() if c.startswith("repo-add ")).split()
        self.assertLess(add.index("/var/lib/raytone/repo/leetop-nic-1.0-9-aarch64.pkg.tar.xz"),
                        add.index("/var/lib/raytone/repo/leetop-nic-1.0-10-aarch64.pkg.tar.xz"))

    def test_a_signing_key_is_created_when_missing(self):
        (self.state / "no-key").touch()
        self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertTrue(any(c.startswith("gpg") and "--quick-generate-key" in c for c in self.calls()))

    def test_omarchy_key_before_the_first_sync(self):
        self.write()
        self.assertLess(self.index(f"pacman-key --lsign-key {OMARCHY_KEY}"), self.index("pacman -Syu"))

    def test_base_list_comes_from_the_omarchy_package_with_arm_substitutions(self):
        self.write()
        base = next(c for c in self.chroot() if c.startswith("pacman -S ") and "omarchy-nvim" in c).split()
        for pkg in ("chromium", "neovim", "omarchy-nvim", "sddm"):
            self.assertIn(pkg, base)
        for pkg in ("nvim", "vi", "obs-studio", "#"):
            self.assertNotIn(pkg, base)

    def test_what_omarchys_iso_adds_is_installed_too(self):
        # Omarchy's base list has wireplumber but not PipeWire's ALSA plugin: without the ISO's
        # audio packages WirePlumber finds no sound card
        self.write()
        iso = [c for c in self.chroot() if c.startswith("pacman -S ") and "pipewire-alsa" in c]
        self.assertEqual(len(iso), 1, self.chroot())
        for pkg in ("base-devel", "pipewire-pulse", "pipewire-jack", "gst-plugin-pipewire", "libpulse"):
            self.assertIn(pkg, iso[0].split())
        for pkg in ("limine", "efibootmgr", "zram-generator", "#"):
            self.assertNotIn(pkg, iso[0].split())
        # the ISO's order: audio before Omarchy and its base list, so a `jack` dependency (ffmpeg,
        # mpv) resolves to pipewire-jack, not jack2, which conflicts with it
        self.assertLess(self.chroot().index(iso[0]), self.index("pacman -S --noconfirm --needed raytone-thor-graphics"))

    def test_the_user_gets_pipewire_pulse_as_archinstall_links_it(self):
        self.write()
        for unit in ("pipewire-pulse.service", "pipewire-pulse.socket"):
            with self.subTest(unit=unit):
                self.assertIn(f"ln -sf /usr/lib/systemd/user/{unit} /home/nvidia/.config/systemd/user/default.target.wants/{unit}",
                              self.chroot("nvidia"))

    def test_upstream_pacman_guard_is_allowed_for_the_installer(self):
        self.write()
        self.assertIn("env OMARCHY_ALLOW_DIRECT_PACMAN=1", self.calls())

    def test_omarchy_setup_order(self):
        self.write()
        apply = self.index("raytone-omarchy-apply-system --install-user nvidia --first-install")
        self.assertLess(self.index("pacman -S --noconfirm --needed raytone-thor-graphics"), apply)
        user = self.chroot("nvidia")
        skel = next(i for i, c in enumerate(user) if c.startswith("cp -af --backup=numbered /etc/skel/. /home/nvidia/"))
        provision = next(i for i, c in enumerate(user) if c.startswith("omarchy-provision-user --force --first-install"))
        self.assertLess(skel, provision)

    def test_the_menu_hides_what_cannot_work_on_the_thor(self):
        self.write()
        user = self.chroot("nvidia")
        provision = next(i for i, c in enumerate(user) if c.startswith("omarchy-provision-user"))
        menu = next(i for i, c in enumerate(user) if c == "raytone-thor-menu-extension")
        self.assertLess(provision, menu)

    def test_provisioning_uses_omarchys_first_boot_context_not_the_iso(self):
        # --first-install in the default context means "ISO chroot": an offline x86_64 Node tarball.
        self.write()
        self.assertIn("env OMARCHY_SETUP_CONTEXT=provision-owner", self.calls())

    def test_the_firewall_must_allow_ssh_before_the_install_counts(self):
        (self.state / "no-ssh-rule").touch()
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("22", r.stderr)

    def test_the_chroot_cannot_touch_the_hosts_network_or_sysctls(self):
        self.write()
        caps = [c for c in self.calls() if c.startswith("setpriv ")]
        self.assertTrue(caps)
        for c in caps:
            self.assertIn("-net_admin", c)
            self.assertIn("-net_raw", c)
        mounts = [c for c in self.calls() if c.startswith("mount ")]
        for path in ("/proc/sys", "/proc/sysrq-trigger"):
            with self.subTest(path=path):
                self.assertTrue(any("remount,bind,ro" in m and m.endswith(path) for m in mounts), mounts)

    def test_a_failed_omarchy_setup_fails_the_install(self):
        (self.state / "apply-fails").touch()
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(any(c.startswith("omarchy-provision-user") for c in self.chroot("nvidia")))

    def test_the_greeter_knows_the_user(self):
        # Omarchy's greeter is password-only: it logs in userModel.lastUser, which the ISO seeds
        # (omarchy-iso configure_login). Without it SDDM authenticates the user "" and fails.
        self.write()
        login = (self.target / "etc" / "sddm.conf.d" / "99-omarchy-login.conf").read_text()
        self.assertIn("RememberLastUser=true", login)
        self.assertIn("RememberLastSession=true", login)
        state = (self.target / "var" / "lib" / "sddm" / "state.conf").read_text()
        self.assertEqual(state, "[Last]\nSession=omarchy.desktop\nUser=nvidia\n")
        self.assertIn("chown sddm:sddm /var/lib/sddm /var/lib/sddm/state.conf", self.chroot())
        self.assertFalse((self.target / "etc" / "sddm.conf.d" / "autologin.conf").exists())

    def test_wifi_profiles_follow_the_device_whatever_its_name(self):
        # Omarchy's aarch64 dependency iwd ships 80-iwd.link (NamePolicy=keep kernel), so the Wi-Fi
        # device is wlan0 on Omarchy, not wlP1p1s0 as on the profiles copied from JetPack.
        nm = self.target / "etc" / "NetworkManager" / "system-connections"
        nm.mkdir(parents=True)
        wifi = "[connection]\nid=home\ntype=wifi\ninterface-name=wlP1p1s0\n\n[wifi]\nssid=home\n"
        wired = "[connection]\nid=lan\ntype=ethernet\ninterface-name=enP2p1s0\n"
        (nm / "home.nmconnection").write_text(wifi)
        (nm / "lan.nmconnection").write_text(wired)
        (nm / "home.nmconnection").chmod(0o600)
        self.write()
        self.assertEqual((nm / "home.nmconnection").read_text(),
                         "[connection]\nid=home\ntype=wifi\n\n[wifi]\nssid=home\n")
        self.assertEqual((nm / "home.nmconnection").stat().st_mode & 0o777, 0o600)
        self.assertEqual((nm / "lan.nmconnection").read_text(), wired)

    # The installer writes into the drive's root as the host's root: a link on the drive must not
    # send a write to the host (Codex merge review).
    def assert_refused_and_host_untouched(self, host_files):
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("link", r.stderr)
        for f, text in host_files.items():
            self.assertEqual(f.read_text(), text)

    def test_a_linked_etc_on_the_drive_is_refused(self):
        host = pathlib.Path(self.tmp.name) / "host-etc"
        host.mkdir()
        (host / "resolv.conf").write_text("host resolver\n")
        (host / "pacman.conf").write_text("host pacman\n")
        (self.target / "etc" / "arch-release").unlink()
        (self.target / "etc").rmdir()
        (self.target / "etc").symlink_to(host)
        (host / "arch-release").write_text("")
        self.assert_refused_and_host_untouched({host / "resolv.conf": "host resolver\n",
                                                host / "pacman.conf": "host pacman\n"})

    def test_a_linked_file_the_installer_writes_is_refused(self):
        victim = pathlib.Path(self.tmp.name) / "host-state"
        victim.write_text("host\n")
        (self.target / "var" / "lib" / "sddm").mkdir(parents=True)
        (self.target / "var" / "lib" / "sddm" / "state.conf").symlink_to(victim)
        self.assert_refused_and_host_untouched({victim: "host\n"})

    def test_a_wifi_profile_that_cannot_be_read_is_left_alone(self):
        # a failed rewrite (unreadable file, full disk) must not replace the profile with nothing
        nm = self.target / "etc" / "NetworkManager" / "system-connections"
        nm.mkdir(parents=True)
        f = nm / "home.nmconnection"
        f.write_text("[connection]\nid=home\ntype=wifi\ninterface-name=wlP1p1s0\n")
        f.chmod(0o200)  # unreadable: the installer cannot tell whether, or how, to rewrite it
        try:
            r = self.run_script("--write", "--confirm-serial", SERIAL)
        finally:
            f.chmod(0o600)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("home.nmconnection", r.stderr)
        self.assertEqual(f.read_text(), "[connection]\nid=home\ntype=wifi\ninterface-name=wlP1p1s0\n")

    def test_install_is_verified(self):
        for unit in ("sddm", "raytone-deadman.timer"):
            with self.subTest(unit=unit):
                (self.state / f"disabled-{unit}").touch()
                r = self.run_script("--write", "--confirm-serial", SERIAL)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn(unit, r.stderr)
                (self.state / f"disabled-{unit}").unlink()


if __name__ == "__main__":
    unittest.main()
