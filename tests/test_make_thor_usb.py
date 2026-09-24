"""make-thor-usb.sh: every refusal path, the dry run, and the write order, with stubbed tools."""
import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make-thor-usb.sh"
SERIAL = "2797824271339930"
SIZE = 248145510400
DESTRUCTIVE = ("wipefs", "sgdisk", "mkfs.vfat", "mkfs.ext4")

STUB = textwrap.dedent("""\
    #!/bin/bash
    name=$(basename "$0")
    echo "$name $*" >> "$STATE/calls"
    n=$(( $(cat "$STATE/count.$name" 2>/dev/null || echo 0) + 1 )); echo $n > "$STATE/count.$name"
    case $name in
      lsblk)
        case "$*" in
          *TYPE,TRAN,SERIAL,SIZE*)
            if [[ -f $STATE/disk-after && $n -gt $(cat "$STATE/disk-after-count") ]]; then cat "$STATE/disk-after"
            else cat "$STATE/disk"; fi ;;
          *MOUNTPOINTS*) cat "$STATE/mounts" 2>/dev/null ;;
          *PARTLABEL*) cat "$STATE/partlabels" ;;
          *PKNAME*) cat "$STATE/rootdisk" ;;
        esac ;;
      findmnt) cat "$STATE/rootsrc" ;;
      swapon) cat "$STATE/swaps" 2>/dev/null ;;
      blkid) echo "0000-uuid-$*" | tr -c 'a-z0-9-\\n' '_' ;;
    esac
    exit 0
    """)


class MakeThorUsbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.tmp.name)
        self.state, self.bin, self.sys = t / "state", t / "bin", t / "sys"
        for d in (self.state, self.bin, self.sys / "block" / "sdz" / "holders", self.sys / "block" / "sdz" / "sdz1" / "holders"):
            d.mkdir(parents=True)
        for tool in ("lsblk", "findmnt", "swapon", "blkid", "udevadm", "partprobe") + DESTRUCTIVE:
            p = self.bin / tool
            p.write_text(STUB)
            p.chmod(0o755)
        dev = t / "dev"
        (dev / "disk" / "by-id").mkdir(parents=True)
        (dev / "sdz").touch()
        self.link = dev / "disk" / "by-id" / f"usb-JZAO_USB3.2_Gen1_{SERIAL}-0:0"
        self.link.symlink_to("../../sdz")
        self.rules = t / "rules.d"
        self.rules.mkdir()
        self.write_state(disk=f"disk usb {SERIAL} {SIZE}", rootsrc="/dev/nvme0n1p1", rootdisk="nvme0n1",
                         partlabels="\nRAYTONE_ESP\nRAYTONE_ROOT\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write_state(self, **files):
        for name, text in files.items():
            (self.state / name.replace("_", "-")).write_text(text + "\n")

    def run_script(self, *args, disk=None):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", STATE=str(self.state),
                   RAYTONE_SYS=str(self.sys), RAYTONE_UDEV_RULES=str(self.rules), RAYTONE_SKIP_ROOT_CHECK="1")
        return subprocess.run(["bash", str(SCRIPT), "--disk", str(disk or self.link), "--serial", SERIAL, *args],
                              env=env, capture_output=True, text=True)

    def calls(self):
        f = self.state / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def destructive_calls(self):
        return [c for c in self.calls() if c.split()[0] in DESTRUCTIVE]

    def assertRefused(self, result, text):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(text, result.stderr)
        self.assertEqual(self.destructive_calls(), [])

    def test_dry_run_is_the_default_and_touches_nothing(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry run", r.stdout)
        self.assertEqual(self.destructive_calls(), [])

    def test_refuses_a_serial_mismatch(self):
        self.write_state(disk=f"disk usb 1111 {SIZE}")
        self.assertRefused(self.run_script(), "serial")

    def test_refuses_a_non_usb_disk(self):
        self.write_state(disk=f"disk nvme {SERIAL} {SIZE}")
        self.assertRefused(self.run_script(), "not a USB disk")

    def test_refuses_a_partition(self):
        self.write_state(disk=f"part usb {SERIAL} {SIZE}")
        self.assertRefused(self.run_script(), "not a whole disk")

    def test_refuses_a_path_outside_usb_by_id(self):
        other = pathlib.Path(self.tmp.name) / "dev" / "disk" / "by-id" / f"nvme-XG7000_{SERIAL}"
        other.symlink_to("../../sdz")
        self.assertRefused(self.run_script(disk=other), "/dev/disk/by-id/usb-")

    def test_refuses_the_disk_holding_root(self):
        self.write_state(rootdisk="sdz")
        self.assertRefused(self.run_script(), "holds /")

    def test_refuses_mounted_partitions(self):
        self.write_state(mounts="\n/media/nvidia/RAYTONE_ESP")
        self.assertRefused(self.run_script(), "mounted")

    def test_refuses_active_swap(self):
        self.write_state(swaps=f"{pathlib.Path(self.tmp.name)}/dev/sdz2")
        self.assertRefused(self.run_script(), "swap")

    def test_refuses_holders(self):
        (self.sys / "block" / "sdz" / "sdz1" / "holders" / "dm-0").touch()
        self.assertRefused(self.run_script(), "holders")

    def test_refuses_implausible_sizes(self):
        for size in (4 * 2**30, 3 * 2**40):
            with self.subTest(size=size):
                self.write_state(disk=f"disk usb {SERIAL} {size}")
                self.assertRefused(self.run_script(), "size")

    def test_write_needs_the_serial_typed_back(self):
        self.assertRefused(self.run_script("--write"), "--confirm-serial")
        self.assertRefused(self.run_script("--write", "--confirm-serial", "1111"), "--confirm-serial")

    def test_write_partitions_formats_and_labels_in_order(self):
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertEqual(r.returncode, 0, r.stderr)
        tools = [c.split()[0] for c in self.destructive_calls()]
        self.assertEqual(tools[0], "wipefs")
        self.assertIn("sgdisk", tools)
        self.assertLess(tools.index("sgdisk"), tools.index("mkfs.vfat"))
        self.assertLess(tools.index("mkfs.vfat"), tools.index("mkfs.ext4"))
        joined = "\n".join(self.calls())
        self.assertIn("-c 1:RAYTONE_ESP", joined)
        self.assertIn("-c 2:RAYTONE_ROOT", joined)
        self.assertIn("-t 1:EF00", joined)
        self.assertRegex(joined, r"mkfs.vfat .*-n RAYTONE_ESP .*sdz1")
        self.assertRegex(joined, r"mkfs.ext4 .*-L RAYTONE_ROOT .*sdz2")

    def test_identity_is_rechecked_before_every_destructive_step(self):
        self.run_script("--write", "--confirm-serial", SERIAL)
        calls = self.calls()
        for i, c in enumerate(calls):
            if c.split()[0] in DESTRUCTIVE:
                previous = [p for p in calls[:i] if p.startswith("lsblk") and "SERIAL" in p]
                self.assertTrue(previous, f"no identity check before {c}")
                last_tool = [p.split()[0] for p in calls[:i] if p.split()[0] in DESTRUCTIVE + ("lsblk",)][-1]
                self.assertEqual(last_tool, "lsblk", f"{c} not directly preceded by an identity check")

    def test_aborts_when_the_disk_changes_mid_write(self):
        self.write_state(disk_after=f"disk usb 9999 {SIZE}", disk_after_count="3")
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("serial", r.stderr)
        self.assertNotIn("mkfs.ext4", [c.split()[0] for c in self.destructive_calls()])

    def test_fails_when_partition_labels_do_not_read_back(self):
        self.write_state(partlabels="\nRAYTONE_ESP\nsomething-else\n")
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("partition labels", r.stderr)

    def test_automount_rule_is_installed_during_the_write_and_removed_after(self):
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(list(self.rules.iterdir()), [])
        self.assertTrue(any("udevadm control --reload" in c for c in self.calls()))
        self.assertIn(SERIAL, r.stdout)  # rule content is echoed for the record


if __name__ == "__main__":
    unittest.main()
