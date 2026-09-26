"""install-thor-nvme.sh with stubbed tools: identity and state refusals, the order of the shrink,
the boot entry, and that a dry run writes nothing."""
import importlib.util
import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install-thor-nvme.sh"
DUMP = (ROOT / "manifests" / "thor-nvme-gpt-2026-09-26.sfdisk").read_text()
EXTLINUX = (ROOT / "manifests" / "jetpack-extlinux-2026-09-26.conf").read_text()
SERIAL = "0000FAKE0001"
SIZE = 2048408248320
UUID = "0E5A0B4C-1D2E-4F30-8A11-5B6C7D8E9F00"
spec = importlib.util.spec_from_file_location("thor_nvme", ROOT / "scripts" / "thor_nvme.py")
nv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nv)
SPLIT = nv.render_dump(nv.split(nv.parse_dump(DUMP), 950, UUID))

STUB = textwrap.dedent("""\
    #!/bin/bash
    name=$(basename "$0")
    echo "$name $*" >> "$STATE/calls"
    case $name in
      lsblk)
        case "$*" in
          *TYPE,TRAN,SERIAL,SIZE*) cat "$STATE/disk" ;;
          *MOUNTPOINTS*) cat "$STATE/mounts" 2>/dev/null ;;
        esac ;;
      findmnt) cat "$STATE/root" ;;
      sfdisk)
        if [[ " $* " == *" --dump "* ]]; then cat "$STATE/table"; else cat > "$STATE/table"; fi ;;
      dumpe2fs) printf 'Block count:              499400777\\nFree blocks:              477712108\\n' ;;
      blkid) cat "$STATE/blkid" 2>/dev/null ;;
      mkfs.ext4) echo ext4 > "$STATE/blkid" ;;
      uuidgen) echo "$UUIDGEN" ;;
      tar) for a in "$@"; do [[ $prev == -czpf ]] && out=$a; prev=$a; done; echo app | gzip > "$out" ;;
      sha256sum) for f in "$@"; do echo "0000  $f"; done ;;
      rsync) for a in "$@"; do dst=$a; done; mkdir -p "$dst/etc"; cp "$SRC/etc/fstab" "$dst/etc/fstab" ;;
    esac
    exit 0
    """)


class InstallThorNvmeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.tmp.name)
        self.state, self.bin, self.mnt, self.src, self.backup = t / "state", t / "bin", t / "mnt", t / "src", t / "backup"
        for d in (self.state, self.bin, self.mnt, self.src / "etc", self.src / "boot"):
            d.mkdir(parents=True)
        for tool in ("lsblk", "findmnt", "sfdisk", "e2fsck", "resize2fs", "dumpe2fs", "blkid", "mkfs.ext4", "mount",
                     "umount", "partx", "uuidgen", "tar", "sha256sum", "rsync"):
            (self.bin / tool).write_text(STUB)
            (self.bin / tool).chmod(0o755)
        dev = t / "dev"
        (dev / "disk" / "by-id").mkdir(parents=True)
        (dev / "nvme0n1").touch()
        self.link = dev / "disk" / "by-id" / "nvme-XG7000-2TB_2280_FAKE"
        self.link.symlink_to("../../nvme0n1")
        self.devpath = os.path.realpath(dev / "nvme0n1")
        (self.state / "disk").write_text(f"disk nvme {SERIAL} {SIZE}\n")
        (self.state / "root").write_text("/dev/sda2\n")
        (self.state / "table").write_text(DUMP)
        (self.src / "etc" / "fstab").write_text("PARTUUID=ca5a56c6-4a4b-4e02-8183-ff166514ae3b / ext4 defaults,noatime 0 1\n")
        (self.src / "boot" / "vmlinuz-raytone-thor-linux").write_bytes(b"kernel")

    def tearDown(self):
        self.tmp.cleanup()

    def run_step(self, step, *args, write=True):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", STATE=str(self.state), SRC=str(self.src),
                   UUIDGEN=UUID, RAYTONE_SKIP_ROOT_CHECK="1", RAYTONE_NVME_MOUNT=str(self.mnt),
                   RAYTONE_SOURCE_ROOT=str(self.src), RAYTONE_KERNEL_SRC=str(self.src / "boot" / "vmlinuz-raytone-thor-linux"))
        extra = ["--write", "--confirm-serial", SERIAL] if write else []
        return subprocess.run(["bash", str(SCRIPT), step, "--nvme", str(self.link), "--serial", SERIAL,
                               "--backup-dir", str(self.backup), *extra, *args], env=env, capture_output=True, text=True)

    def ok(self, step, **kw):
        r = self.run_step(step, **kw)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r

    def calls(self):
        f = self.state / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def writing_calls(self):
        return [c for c in self.calls() if c.split()[0] in ("e2fsck", "resize2fs", "mkfs.ext4", "rsync", "mount")
                or (c.startswith("sfdisk") and "--dump" not in c)]

    def make_backup(self):
        (self.mnt / "boot" / "extlinux").mkdir(parents=True)
        (self.mnt / "boot" / "extlinux" / "extlinux.conf").write_text(EXTLINUX)
        self.ok("backup")

    def split_disk(self):
        self.make_backup()
        self.ok("shrink-app")

    # identity and use
    def test_refusals_before_anything(self):
        cases = {
            "serial": lambda: (self.state / "disk").write_text(f"disk nvme OTHER {SIZE}\n"),
            "size": lambda: (self.state / "disk").write_text(f"disk nvme {SERIAL} 1000204886016\n"),
            "transport": lambda: (self.state / "disk").write_text(f"disk usb {SERIAL} {SIZE}\n"),
            "root on nvme": lambda: (self.state / "root").write_text(self.devpath + "p12\n"),
            "mounted": lambda: (self.state / "mounts").write_text("/mnt/x\n"),
        }
        for name, break_it in cases.items():
            with self.subTest(name=name):
                self.setUp()
                break_it()
                r = self.run_step("backup")
                self.assertNotEqual(r.returncode, 0)
                self.assertFalse(self.writing_calls())

    def test_confirm_serial_is_required(self):
        r = self.run_step("backup", "--confirm-serial", "nope", write=False)
        env_r = subprocess.run(["bash", str(SCRIPT), "backup", "--nvme", str(self.link), "--serial", SERIAL,
                                "--backup-dir", str(self.backup), "--write"],
                               env=dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", STATE=str(self.state),
                                        RAYTONE_SKIP_ROOT_CHECK="1", RAYTONE_NVME_MOUNT=str(self.mnt)),
                               capture_output=True, text=True)
        self.assertNotEqual(env_r.returncode, 0)
        self.assertIn("confirm-serial", env_r.stderr)

    def test_an_unknown_table_stops_every_step(self):
        (self.state / "table").write_text(DUMP.replace('name="UDA"', 'name="UDB"'))
        for step in ("backup", "shrink-app", "create-root", "clone", "boot-entry"):
            with self.subTest(step=step):
                r = self.run_step(step)
                self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.writing_calls())

    def test_dry_runs_write_nothing(self):
        self.make_backup()
        calls_before = len(self.calls())
        for step in ("shrink-app",):
            self.ok(step, write=False)
        self.assertFalse([c for c in self.calls()[calls_before:] if c.split()[0] in ("e2fsck", "resize2fs")
                          or (c.startswith("sfdisk") and "--dump" not in c)])
        self.assertEqual((self.state / "table").read_text(), DUMP)

    # backup
    def test_backup_keeps_table_app_and_extlinux(self):
        self.make_backup()
        self.assertEqual((self.backup / "nvme-gpt.sfdisk").read_text(), DUMP)
        self.assertEqual((self.backup / "extlinux.conf").read_text(), EXTLINUX)
        self.assertTrue((self.backup / "jetpack-app.tar.gz.sha256").exists())
        self.assertIn(f"mount -o ro,noload {self.devpath}p1", "\n".join(self.calls()))

    # shrink
    def test_shrink_needs_a_backup(self):
        r = self.run_step("shrink-app")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("backup", r.stderr)

    def test_shrink_checks_resizes_then_rewrites_the_table(self):
        self.split_disk()
        calls = self.calls()
        fsck = next(i for i, c in enumerate(calls) if c.startswith(f"e2fsck -f -p {self.devpath}p1"))
        resize = next(i for i, c in enumerate(calls) if c.startswith("resize2fs"))
        table = next(i for i, c in enumerate(calls) if c.startswith("sfdisk --no-reread"))
        self.assertLess(fsck, resize)
        self.assertLess(resize, table)
        blocks = nv.app_blocks(nv.parse_dump(SPLIT).part(1))
        self.assertIn(f"resize2fs {self.devpath}p1 {blocks}", calls)
        self.assertEqual(nv.parse_dump((self.state / "table").read_text()), nv.parse_dump(SPLIT))
        self.assertTrue(any(c.startswith(f"e2fsck -f -n {self.devpath}p1") for c in calls[table:]))

    def test_shrink_refuses_a_table_changed_since_the_backup(self):
        self.make_backup()
        (self.backup / "nvme-gpt.sfdisk").write_text(DUMP.replace("label-id", "label-id-x"))
        r = self.run_step("shrink-app")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse([c for c in self.calls() if c.startswith("resize2fs")])

    # create-root, clone
    def test_create_root_needs_the_split_table_and_an_empty_partition(self):
        r = self.run_step("create-root")
        self.assertNotEqual(r.returncode, 0)
        self.split_disk()
        self.ok("create-root")
        self.assertIn(f"mkfs.ext4 -q -L RAYTONE_OMARCHY {self.devpath}p12", self.calls())
        r = self.run_step("create-root")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already holds a filesystem", r.stderr)

    def test_clone_moves_fstab_to_the_new_partition(self):
        self.split_disk()
        self.ok("create-root")
        for f in self.mnt.rglob("*"):
            pass
        # the clone mounts RAYTONE_OMARCHY at the same mount point: start from an empty one
        import shutil
        shutil.rmtree(self.mnt)
        self.mnt.mkdir()
        self.ok("clone")
        self.assertIn(f"PARTUUID={UUID.lower()} / ext4", (self.mnt / "etc" / "fstab").read_text())
        self.assertIn("APP_PARTUUID=1b3479b0-b4c2-4a1b-8b81-86d864b3944e", (self.mnt / "etc/raytone/nvme-boot.conf").read_text())
        self.assertTrue(any(c.startswith("rsync -aHAXS") and "--one-file-system" in c for c in self.calls()))

    # boot entry
    def test_boot_entry_adds_omarchy_and_keeps_jetpacks_file(self):
        self.split_disk()
        self.ok("boot-entry")
        ext = self.mnt / "boot" / "extlinux"
        self.assertEqual((ext / "extlinux.conf.jetpack").read_text(), EXTLINUX)
        self.assertEqual((ext / "extlinux.conf").read_text(),
                         nv.add_omarchy_entry(EXTLINUX, UUID.lower(), "/boot/raytone-thor/Image"))
        self.assertEqual((self.mnt / "boot" / "raytone-thor" / "Image").read_bytes(), b"kernel")

    def test_boot_entry_refuses_an_unrecorded_extlinux(self):
        self.split_disk()
        (self.mnt / "boot" / "extlinux" / "extlinux.conf").write_text(EXTLINUX.replace("TIMEOUT 30", "TIMEOUT 50"))
        r = self.run_step("boot-entry")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.mnt / "boot" / "raytone-thor" / "Image").exists())


if __name__ == "__main__":
    unittest.main()
