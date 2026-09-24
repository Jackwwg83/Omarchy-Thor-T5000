"""install-thor-boot.sh with stubbed tools: refusals, GRUB flags, no efivars, files written, one-shot."""
import json
import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install-thor-boot.sh"
SERIAL = "2797824271339930"
SIZE = 248145510400

STUB = textwrap.dedent("""\
    #!/bin/bash
    name=$(basename "$0")
    echo "$name $*" >> "$STATE/calls"
    case $name in
      lsblk)
        case "$*" in
          *TYPE,TRAN,SERIAL,SIZE*) cat "$STATE/disk" ;;
          *MOUNTPOINTS*) cat "$STATE/mounts" 2>/dev/null ;;
          *PKNAME*) echo nvme0n1 ;;
          *PARTLABEL,FSTYPE*) cat "$STATE/parts" ;;
        esac ;;
      findmnt) echo /dev/nvme0n1p1 ;;
      swapon) ;;
      blkid) echo 1234-ABCD ;;
      mount)
        # the last argument is the mount point; make the ESP look installed after grub-install
        : ;;
      chroot)
        shift  # tools root
        if [[ $1 == /usr/bin/env ]]; then shift; [[ $1 == -i ]] && shift; while [[ $1 == *=* ]]; do shift; done; fi
        echo "in-chroot $*" >> "$STATE/calls"
        if [[ $1 == grub-install ]]; then
          esp=$(printf '%s\\n' "$@" | sed -n 's/^--efi-directory=//p')
          mkdir -p "$ESP_REAL/EFI/BOOT" "$ESP_REAL/boot/grub/arm64-efi"
          touch "$ESP_REAL/EFI/BOOT/BOOTAA64.EFI" "$ESP_REAL/boot/grub/arm64-efi/normal.mod"
        elif [[ $1 == grub-editenv ]]; then
          f=$2; f=${f/\\/mnt\\/raytone-esp/$ESP_REAL}
          case $3 in
            create) head -c 1024 /dev/zero > "$f" ;;
            set) echo "$4" > "$f" ;;
            list) cat "$f" ;;
          esac
        fi ;;
    esac
    exit 0
    """)


class InstallThorBootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.tmp.name)
        self.state, self.bin, self.sys, self.esp = t / "state", t / "bin", t / "sys", t / "esp"
        self.tools = t / "tools"
        for d in (self.state, self.bin, self.sys / "block" / "sdz" / "holders", self.esp,
                  self.tools / "usr" / "bin", self.tools / "mnt" / "raytone-esp"):
            d.mkdir(parents=True)
        (self.tools / "usr" / "bin" / "grub-install").touch()
        for tool in ("lsblk", "findmnt", "swapon", "blkid", "mount", "umount", "chroot", "udevadm"):
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
        (self.state / "parts").write_text("sdz1 RAYTONE_ESP vfat\nsdz2 RAYTONE_ROOT ext4\n")
        self.entries = t / "entries.json"
        self.entries.write_text(json.dumps([{"id": "jetpack-grub", "title": "JetPack kernel via GRUB",
                                             "fs_uuid": "1111-aaaa", "kernel": "/boot/Image",
                                             "initrd": "/boot/initrd", "cmdline": "root=PARTUUID=x rw"}]))

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", STATE=str(self.state),
                   RAYTONE_SYS=str(self.sys), RAYTONE_SKIP_ROOT_CHECK="1", RAYTONE_NO_UNSHARE="1",
                   RAYTONE_ESP_MOUNT=str(self.esp), ESP_REAL=str(self.esp))
        return subprocess.run(["bash", str(SCRIPT), *args, "--disk", str(self.link), "--serial", SERIAL,
                               "--tools-root", str(self.tools)], env=env, capture_output=True, text=True)

    def calls(self):
        f = self.state / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def test_dry_run_prints_the_menu_and_writes_nothing(self):
        r = self.run_script("install", "--entries", str(self.entries))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry run", r.stdout)
        self.assertIn("--id jetpack-grub", r.stdout)
        self.assertFalse([c for c in self.calls() if c.startswith(("mount", "chroot"))])

    def test_refuses_wrong_partition_layout(self):
        (self.state / "parts").write_text("sdz1 EFI vfat\nsdz2 RAYTONE_ROOT ext4\n")
        r = self.run_script("install", "--entries", str(self.entries))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("RAYTONE_ESP", r.stderr)

    def test_refuses_a_serial_mismatch(self):
        (self.state / "disk").write_text(f"disk usb 1111 {SIZE}\n")
        r = self.run_script("install", "--entries", str(self.entries), "--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse([c for c in self.calls() if c.startswith("chroot")])

    def test_write_installs_grub_without_nvram_and_without_efivars(self):
        r = self.run_script("install", "--entries", str(self.entries), "--write", "--confirm-serial", SERIAL)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        grub = [c for c in self.calls() if c.startswith("in-chroot grub-install")]
        self.assertEqual(len(grub), 1)
        for flag in ("--target=arm64-efi", "--removable", "--no-nvram", "--efi-directory=/mnt/raytone-esp"):
            self.assertIn(flag, grub[0])
        mounts = [c for c in self.calls() if c.startswith("mount ")]
        self.assertFalse([m for m in mounts if "efivarfs" in m])
        self.assertTrue([m for m in mounts if "sysfs" in m and "ro" in m], mounts)

    def test_write_leaves_grub_cfg_and_an_empty_one_shot_on_the_esp(self):
        self.run_script("install", "--entries", str(self.entries), "--write", "--confirm-serial", SERIAL)
        cfg = (self.esp / "boot" / "grub" / "grub.cfg").read_text()
        self.assertIn('set default="firmware-next"', cfg)
        self.assertIn("--id jetpack-grub", cfg)
        self.assertEqual((self.esp / "boot" / "grub" / "grubenv").stat().st_size, 1024)

    def test_arm_once_sets_next_entry_and_reads_it_back(self):
        self.run_script("install", "--entries", str(self.entries), "--write", "--confirm-serial", SERIAL)
        r = self.run_script("arm-once", "--entry", "jetpack-grub", "--write", "--confirm-serial", SERIAL)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("next_entry=jetpack-grub", (self.esp / "boot" / "grub" / "grubenv").read_text())

    def test_arm_once_refuses_an_entry_not_in_the_menu(self):
        self.run_script("install", "--entries", str(self.entries), "--write", "--confirm-serial", SERIAL)
        r = self.run_script("arm-once", "--entry", "arch", "--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not in grub.cfg", r.stderr)


if __name__ == "__main__":
    unittest.main()
