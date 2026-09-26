"""install-thor-root.sh with stubbed tools: refusals, order, the files it writes, accounts and units."""
import hashlib
import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install-thor-root.sh"
SERIAL = "0000000000001234"
SIZE = 248145510400
HASH = "$6$saltsalt$" + "x" * 40
PKGS = ("raytone-thor-linux-6.8.12.l4t39.2.1-1-aarch64.pkg.tar.xz", "raytone-thor-firmware-39.2.1-1-aarch64.pkg.tar.xz",
        "raytone-thor-core-39.2.1-1-aarch64.pkg.tar.xz", "raytone-thor-leetop-nic-2026.09.18-1-aarch64.pkg.tar.xz")

STUB = textwrap.dedent("""\
    #!/bin/bash
    name=$(basename "$0")
    if [[ $name == setpriv ]]; then while [[ $1 != -- ]]; do shift; done; shift; exec "$@"; fi
    echo "$name $*" >> "$STATE/calls"
    case $name in
      lsblk)
        case "$*" in
          *TYPE,TRAN,SERIAL,SIZE*) cat "$STATE/disk" ;;
          *PKNAME*) echo nvme0n1 ;;
          *PARTLABEL,FSTYPE*) printf 'sdz\\nsdz1 RAYTONE_ESP vfat\\nsdz2 RAYTONE_ROOT ext4\\n' ;;
        esac ;;
      findmnt) echo /dev/nvme0n1p1 ;;
      blkid) echo ca5a56c6-4a4b-4e02-8183-ff166514ae3b ;;
      chroot)
        root=$1; shift
        if [[ $1 == /usr/bin/env ]]; then shift; [[ $1 == -i ]] && shift; while [[ $1 == *=* ]]; do shift; done; fi
        echo "in-chroot $root $*" >> "$STATE/calls"
        # the unpacked rootfs has the default "alarm" user and no one else
        if [[ $1 == getent && $2 == passwd ]]; then [[ $3 == alarm ]] && exit 0; exit 2; fi
        if [[ $1 == systemctl && $2 == is-enabled && -f $STATE/disabled-$3 ]]; then exit 1; fi
        if [[ $1 == systemctl && $2 == mask ]]; then
          mkdir -p "$TARGET/etc/systemd/system"
          for u in "${@:3}"; do [[ -f $STATE/mask-fails-$u ]] || ln -sfn /dev/null "$TARGET/etc/systemd/system/$u"; done
        fi
        if [[ $1 == systemd-machine-id-setup ]]; then
          id=0123456789abcdef0123456789abcdef
          [[ -f $STATE/machine-id-like-host ]] && id=$(cat "$STATE/host-machine-id")
          [[ -f $STATE/machine-id-uninitialized ]] && id=uninitialized
          echo "$id" > "$TARGET/etc/machine-id"
        fi
        if [[ $1 == timeout && -f $STATE/no-timeout-k ]]; then exit 125; fi
        if [[ $1 == bsdtar ]]; then mkdir -p "$TARGET/etc" "$TARGET/home/alarm"; echo "Arch Linux ARM" > "$TARGET/etc/arch-release"; fi
        if [[ $1 == pacman && $2 == -U ]]; then
          k=$TARGET/usr/lib/modules/6.8.12-1021-tegra
          mkdir -p "$TARGET/boot" "$k" "$TARGET/etc/nvpmodel" "$TARGET/etc/nvpower/nvfancontrol"
          touch "$TARGET/boot/vmlinuz-raytone-thor-linux" "$k/modules.dep" "$TARGET/etc/nvpmodel/nvpmodel_p3834_0008.conf" \
                "$TARGET/etc/nvpower/nvfancontrol/nvfancontrol_p3834_0008_p4071_0000.conf"
          ln -sf nvpmodel/nvpmodel_p3834_0008.conf "$TARGET/etc/nvpmodel.conf"
          ln -sf nvpower/nvfancontrol/nvfancontrol_p3834_0008_p4071_0000.conf "$TARGET/etc/nvfancontrol.conf"
          # a few of systemd's units, as the upgraded rootfs has them
          u=$TARGET/usr/lib/systemd/system
          mkdir -p "$u/factory-reset.target.wants"
          for n in systemd-tpm2-setup.service systemd-tpm2-clear.service systemd-pcrlogin@.service systemd-pcrextend.socket \
                   systemd-pcrlock-make-policy.service systemd-factory-reset.socket systemd-factory-reset-request.service \
                   factory-reset.target systemd-hibernate-clear.service systemd-boot-random-seed.service \
                   systemd-bless-boot.service systemd-networkd.service systemd-networkd.socket \\
                   systemd-networkd-wait-online.service sshd.service systemd-journald.service; do
            touch "$u/$n"
          done
        fi ;;
      nmcli) echo "802-11-wireless:/run/NetworkManager/system-connections/netplan-NM-1234-Home.nmconnection"
             echo "loopback:/run/NetworkManager/system-connections/lo.nmconnection"
             echo "bridge:/run/NetworkManager/system-connections/l4tbr0.nmconnection" ;;
    esac
    exit 0
    """)


class InstallThorRootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.tmp.name)
        self.state, self.bin, self.sys, self.target = t / "state", t / "bin", t / "sys", t / "target"
        self.tools, self.pkgs, self.etc, self.home = t / "tools", t / "pkgs", t / "hostetc", t / "hosthome"
        for d in (self.state, self.bin, self.sys / "block" / "sdz" / "holders", self.target, self.tools / "usr" / "bin",
                  self.pkgs, self.etc / "NetworkManager" / "system-connections", self.home / ".ssh", t / "rules"):
            d.mkdir(parents=True)
        (self.tools / "usr" / "bin" / "bsdtar").touch()
        for tool in ("lsblk", "findmnt", "swapon", "blkid", "mount", "umount", "chroot", "udevadm", "sync", "setpriv", "nmcli"):
            p = self.bin / tool
            p.write_text(STUB)
            p.chmod(0o755)
        dev = t / "dev"
        (dev / "disk" / "by-id").mkdir(parents=True)
        for n in ("sdz", "sdz1", "sdz2"):
            (dev / n).touch()
        self.link = dev / "disk" / "by-id" / f"usb-JZAO_USB3.2_Gen1_{SERIAL}-0:0"
        self.link.symlink_to("../../sdz")
        (self.state / "disk").write_text(f"disk usb {SERIAL} {SIZE}\n")
        self.tarball = t / "ArchLinuxARM-aarch64-latest.tar.gz"
        self.tarball.write_bytes(b"rootfs")
        self.sha = hashlib.sha256(b"rootfs").hexdigest()
        for p in PKGS:
            (self.pkgs / p).write_bytes(b"pkg")
        (self.etc / "shadow").write_text(f"root:*:1::::::\nnvidia:{HASH}:20000:0:99999:7:::\n")
        (self.etc / "NetworkManager" / "system-connections" / "Home.nmconnection").write_text("[wifi]\nssid=Home\n")
        (self.etc / "NetworkManager" / "system-connections" / "Cafe.nmconnection").write_text("[wifi]\nssid=Cafe\n")
        self.run = t / "hostrun" / "NetworkManager" / "system-connections"
        self.run.mkdir(parents=True)
        for n in ("netplan-NM-1234-Home.nmconnection", "lo.nmconnection", "l4tbr0.nmconnection"):
            (self.run / n).write_text("[connection]\n")
        os.symlink("/usr/share/zoneinfo/Asia/Shanghai", self.etc / "localtime")
        (self.home / ".ssh" / "authorized_keys").write_text("ssh-ed25519 AAAA test\n")
        (self.etc / "machine-id").write_text("fedcba9876543210fedcba9876543210\n")
        (self.state / "host-machine-id").write_text("fedcba9876543210fedcba9876543210\n")
        self.rules = t / "rules"

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args, sha=None):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", STATE=str(self.state), TARGET=str(self.target),
                   RAYTONE_SYS=str(self.sys), RAYTONE_SKIP_ROOT_CHECK="1", RAYTONE_NO_UNSHARE="1",
                   RAYTONE_TARGET_MOUNT=str(self.target), RAYTONE_HOST_ETC=str(self.etc),
                   RAYTONE_HOST_HOME=str(self.home), RAYTONE_UDEV_RULES=str(self.rules),
                   RAYTONE_HOST_RUN=str(self.run.parent.parent))
        return subprocess.run(["bash", str(SCRIPT), "--disk", str(self.link), "--serial", SERIAL,
                               "--tools-root", str(self.tools), "--tarball", str(self.tarball),
                               "--tarball-sha256", sha or self.sha, "--packages", str(self.pkgs),
                               "--user", "nvidia", *args], env=env, capture_output=True, text=True)

    def write(self):
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r

    def calls(self):
        f = self.state / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def chroot_calls(self):
        return [c.split(" ", 2)[2] for c in self.calls() if c.startswith("in-chroot ")]

    def test_dry_run_mounts_nothing(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry run", r.stdout)
        self.assertFalse([c for c in self.calls() if c.startswith(("mount", "chroot"))])

    def test_refuses_without_the_vendor_network_drivers(self):
        (self.pkgs / PKGS[3]).unlink()
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("raytone-thor-leetop-nic", r.stderr)

    def test_networkd_is_masked_so_networkmanager_alone_manages_the_network(self):
        self.write()
        u = self.target / "etc/systemd/system"
        for unit in ("systemd-networkd.service", "systemd-networkd.socket", "systemd-networkd-wait-online.service"):
            with self.subTest(unit=unit):
                self.assertEqual(os.readlink(u / unit), "/dev/null")

    def test_refuses_missing_packages(self):
        (self.pkgs / PKGS[2]).unlink()
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("raytone-thor-core", r.stderr)

    def test_refuses_a_rootfs_with_the_wrong_checksum(self):
        r = self.run_script(sha="0" * 64)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("sha256", r.stderr)

    def test_root_partition_is_mounted_after_the_identity_check(self):
        self.write()
        calls = self.calls()
        ident = next(i for i, c in enumerate(calls) if "TYPE,TRAN,SERIAL,SIZE" in c)
        mount = next(i for i, c in enumerate(calls) if c.startswith("mount ") and "sdz2" in c)
        self.assertLess(ident, mount)

    def test_rootfs_is_unpacked_with_the_tools_roots_bsdtar(self):
        self.write()
        self.assertTrue(any(c.startswith("bsdtar -xpf") for c in self.chroot_calls()))

    def test_packages_installed_and_nvram_tools_kept_out(self):
        self.write()
        pacman = [c for c in self.chroot_calls() if c.startswith("pacman")]
        self.assertTrue(any("-U" in c and all(p.split("-")[2] in c for p in PKGS) for c in pacman), pacman)
        self.assertTrue(any(c.startswith("pacman -Rdd --noconfirm linux-aarch64") for c in pacman))
        installs = " ".join(c for c in pacman if c.startswith("pacman -S "))
        for pkg in ("networkmanager", "openssh", "avahi", "linux-firmware-realtek"):
            self.assertIn(pkg, installs)
        for pkg in ("efibootmgr", "grub", "fwupd"):
            self.assertNotIn(f" {pkg}", f" {installs} ")

    def test_system_files(self):
        self.write()
        t = self.target
        self.assertEqual((t / "etc/hostname").read_text().strip(), "raytone-thor")
        fstab = (t / "etc/fstab").read_text()
        self.assertIn("PARTUUID=ca5a56c6-4a4b-4e02-8183-ff166514ae3b / ext4", fstab)
        # the running system cannot write UEFI variables (systemd-remount-fs applies this)
        self.assertIn("efivarfs /sys/firmware/efi/efivars efivarfs ro,nosuid,nodev,noexec 0 0", fstab)
        self.assertEqual(os.readlink(t / "etc/localtime"), "/usr/share/zoneinfo/Asia/Shanghai")
        self.assertIn("LANG=en_US.UTF-8", (t / "etc/locale.conf").read_text())
        self.assertTrue((t / "var/log/journal").is_dir())
        self.assertIn("HOOKS=(base udev modconf block filesystems fsck)", (t / "etc/mkinitcpio.conf.d/raytone-thor.conf").read_text())

    def test_unattended_safety_units(self):
        self.write()
        u = self.target / "etc/systemd/system"
        for svc in ("emergency", "rescue"):
            text = (u / f"{svc}.service.d/raytone-reboot.conf").read_text()
            self.assertIn("ExecStart=\n", text)
            self.assertIn("systemctl --no-block reboot", text)
        self.assertIn("OnBootSec=20min", (u / "raytone-deadman.timer").read_text())
        self.assertIn("/run/raytone-keep", (u / "raytone-deadman.service").read_text())
        marker = (u / "raytone-boot-marker.service").read_text()
        self.assertIn("boots.log", marker)
        self.assertIn("uname -v", marker)  # tells NVIDIA's kernel from the vendor build
        reboot = (u / "reboot.target.d/raytone-bounded.conf").read_text()
        self.assertIn("JobTimeoutSec=5min", reboot)
        self.assertIn("JobTimeoutAction=reboot-force", reboot)

    def test_network_and_ssh_come_from_the_jetpack_host(self):
        self.write()
        nm = self.target / "etc/NetworkManager/system-connections/netplan-NM-1234-Home.nmconnection"
        self.assertEqual(nm.stat().st_mode & 0o777, 0o600)
        keys = self.target / "home/nvidia/.ssh/authorized_keys"
        self.assertEqual(keys.read_text(), "ssh-ed25519 AAAA test\n")
        self.assertEqual(keys.stat().st_mode & 0o777, 0o600)

    def test_accounts(self):
        r = self.write()
        chroot = self.chroot_calls()
        self.assertTrue(any(c.startswith("userdel -r alarm") for c in chroot))
        self.assertTrue(any(c.startswith("useradd -m -u 1000") and c.endswith(" nvidia") for c in chroot))
        self.assertTrue(any(c.startswith("passwd -l root") for c in chroot))
        self.assertTrue(any(c.startswith("chpasswd -e") for c in chroot))
        self.assertNotIn(HASH, r.stdout + r.stderr)
        sudo = self.target / "etc/sudoers.d"
        self.assertIn("%wheel ALL=(ALL:ALL) ALL", (sudo / "10-wheel").read_text())
        self.assertIn("NOPASSWD", (sudo / "raytone-temp").read_text())
        self.assertEqual((sudo / "raytone-temp").stat().st_mode & 0o777, 0o440)

    def test_signature_files_are_not_taken_for_packages(self):
        for p in PKGS:
            (self.pkgs / (p + ".sig")).write_bytes(b"sig")
        self.write()
        self.assertFalse([c for c in self.chroot_calls() if c.startswith("pacman -U") and ".sig" in c])

    def test_refuses_before_any_mount_without_a_login(self):
        for broken in ("keys", "hash"):
            with self.subTest(broken=broken):
                (self.state / "calls").unlink(missing_ok=True)
                if broken == "keys":
                    (self.home / ".ssh" / "authorized_keys").unlink()
                else:
                    (self.home / ".ssh" / "authorized_keys").write_text("ssh-ed25519 AAAA test\n")
                    (self.etc / "shadow").write_text("root:*:1::::::\n")
                r = self.run_script("--write", "--confirm-serial", SERIAL)
                self.assertNotEqual(r.returncode, 0)
                self.assertFalse([c for c in self.calls() if c.startswith("mount ")])

    def test_a_partial_unpack_is_refused(self):
        (self.target / "etc").mkdir()
        (self.target / "etc" / "arch-release").write_text("Arch Linux ARM\n")
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("partial", r.stderr)

    def test_only_the_active_network_profile_is_copied(self):
        self.write()
        nm = self.target / "etc/NetworkManager/system-connections"
        self.assertEqual(sorted(p.name for p in nm.iterdir()), ["netplan-NM-1234-Home.nmconnection"])

    def test_install_is_verified_before_it_reports_success(self):
        r = self.write()
        self.assertIn("verified:", r.stdout)
        (self.target / "boot/vmlinuz-raytone-thor-linux").unlink()
        (self.target / ".raytone-unpacked").write_text("ok\n")
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertEqual(r.returncode, 0)  # the stub pacman -U lays the kernel down again

    def test_early_safety_and_thermal_guard(self):
        self.write()
        u = self.target / "etc/systemd/system"
        self.assertIn("DefaultDependencies=no", (u / "raytone-deadman.timer").read_text())
        self.assertIn("DefaultDependencies=no", (u / "raytone-boot-start.service").read_text())
        guard = (u / "raytone-thermal-guard.service").read_text()
        self.assertIn("ExecStart=/usr/lib/raytone/thermal-guard", guard)
        self.assertIn("Restart=on-failure", guard)
        # not ordered after the services it watches, so a hanging start cannot hold it back
        self.assertNotIn("After=nvfancontrol", guard)
        self.assertNotIn("Type=oneshot", guard)
        installed = self.target / "usr/lib/raytone/thermal-guard"
        self.assertEqual(installed.read_text(), (ROOT / "scripts/thor-rootfs/thermal-guard").read_text())
        self.assertTrue(os.access(installed, os.X_OK))
        enable = " ".join(c for c in self.chroot_calls() if c.startswith("systemctl enable"))
        self.assertIn("raytone-thermal-guard", enable)
        self.assertIn("raytone-boot-start", enable)

    def test_every_unit_is_checked_for_enablement(self):
        (self.state / "disabled-nvpower").touch()
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("nvpower", r.stderr)

    def test_first_boot_does_not_wait_for_a_person(self):
        self.write()
        # a machine ID means systemd does not treat the first boot as "first boot" (no prompts, no preset-all)
        self.assertTrue(any(c.startswith("systemd-machine-id-setup") for c in self.chroot_calls()))
        self.assertEqual((self.target / "etc/vconsole.conf").read_text().strip(), "KEYMAP=us")
        self.assertEqual(os.readlink(self.target / "etc/systemd/system/systemd-firstboot.service"), "/dev/null")

    def test_uefi_variable_and_tpm_writers_are_masked(self):
        self.write()
        u = self.target / "etc/systemd/system"
        # found in the target by name, whether started at boot, by a socket, by logind or by a generator
        for unit in ("systemd-tpm2-setup.service", "systemd-tpm2-clear.service", "systemd-pcrlogin@.service",
                     "systemd-pcrextend.socket", "systemd-pcrlock-make-policy.service", "systemd-factory-reset.socket",
                     "systemd-factory-reset-request.service", "factory-reset.target",
                     "systemd-hibernate-clear.service", "systemd-boot-random-seed.service", "systemd-bless-boot.service",
                     # always, present or not
                     "systemd-repart.service", "sleep.target", "suspend.target", "hibernate.target",
                     "hybrid-sleep.target", "suspend-then-hibernate.target"):
            with self.subTest(unit=unit):
                self.assertEqual(os.readlink(u / unit), "/dev/null")
        for unit in ("sshd.service", "systemd-journald.service", "factory-reset.target.wants"):
            with self.subTest(unit=unit):
                self.assertFalse((u / unit).is_symlink())

    def test_the_machine_id_must_be_new_and_valid(self):
        for flag in ("machine-id-like-host", "machine-id-uninitialized"):
            with self.subTest(flag=flag):
                (self.state / flag).touch()
                r = self.run_script("--write", "--confirm-serial", SERIAL)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("machine ID", r.stderr)
                (self.state / flag).unlink()

    def test_the_drive_needs_timeout_with_kill_after(self):
        (self.state / "no-timeout-k").touch()
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("timeout", r.stderr)

    def test_a_unit_that_did_not_mask_fails_the_install(self):
        (self.state / "mask-fails-systemd-tpm2-setup.service").touch()
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("systemd-tpm2-setup.service", r.stderr)

    def test_units_enabled(self):
        self.write()
        enable = " ".join(c for c in self.chroot_calls() if c.startswith("systemctl enable"))
        for unit in ("sshd", "NetworkManager", "avahi-daemon", "systemd-timesyncd", "raytone-deadman.timer",
                     "raytone-boot-marker", "nv-load-display-modules", "nvfancontrol", "nvpmodel", "nvpower"):
            self.assertIn(unit, enable)
        self.assertNotIn("nvcpupowerfix", enable)


if __name__ == "__main__":
    unittest.main()
