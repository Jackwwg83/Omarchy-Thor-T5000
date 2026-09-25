"""publish-thor-repo.sh with stubbed tools: adds new builds to the drive's signed [raytone-thor]
repository from JetPack, so omarchy-update on the drive picks them up. It installs nothing."""
import os
import pathlib
import subprocess
import tarfile
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publish-thor-repo.sh"
SERIAL = "2797824271339930"
SIZE = 248145510400
FPR = "ABCDEF0123456789ABCDEF0123456789ABCDEF01"
DB = "var/lib/raytone/repo/raytone-thor.db.tar.gz"

STUB = textwrap.dedent("""\
    #!/bin/bash
    name=$(basename "$0")
    if [[ $name == setpriv ]]; then echo "setpriv $*" >> "$STATE/calls"; while [[ $1 != -- ]]; do shift; done; shift; exec "$@"; fi
    echo "$name $*" >> "$STATE/calls"
    case $name in
      lsblk)
        case "$*" in
          *TYPE,TRAN,SERIAL,SIZE*) echo "disk usb $SERIAL $SIZE" ;;
          *PKNAME*) echo nvme0n1 ;;
          *PARTLABEL,FSTYPE*) printf 'sdz\\nsdz1 RAYTONE_ESP vfat\\nsdz2 RAYTONE_ROOT ext4\\n' ;;
        esac ;;
      findmnt) echo /dev/nvme0n1p1 ;;
      gpg)
        case "$*" in
          *--list-secret-keys*) [[ -f $STATE/no-key ]] || echo "fpr:::::::::$FPR:" ;;
          *--detach-sign*) for a in "$@"; do f=$a; done; echo "sig-by-$FPR" > "$f.sig" ;;
          *--export*) echo PUBKEY ;;
          *--verify*) for a in "$@"; do [[ $a == *.sig ]] && s=$a; done; grep -q "sig-by-$FPR" "$s" || exit 1
                      echo "[GNUPG:] VALIDSIG $FPR" ;;
        esac ;;
      chroot)
        shift  # the root
        if [[ $1 == /usr/bin/env ]]; then shift; [[ $1 == -i ]] && shift; while [[ $1 == *=* ]]; do shift; done; fi
        echo "in-chroot $*" >> "$STATE/calls"
        if [[ $1 == pacman-key && $2 == --verify && -f $STATE/untrusted ]]; then exit 1; fi
        if [[ $1 == pacman-key && $2 == --list-keys && -f $STATE/untrusted ]]; then exit 1; fi
        if [[ $1 == repo-add && ! -f $STATE/repo-add-noop ]]; then
          # model repo-add: one directory per package (name-version-release) in a gzip tar
          shift 2; db=$TARGET$1; shift
          work=$(mktemp -d); tar -xzf "$db" -C "$work"
          for f in "$@"; do e=${f##*/}; e=${e%.pkg.tar.*}; e=${e%-*}; n=${e%-*-*}
            rm -rf "$work/$n"-[0-9]*; mkdir -p "$work/$e"; echo "%NAME%" > "$work/$e/desc"; done
          COPYFILE_DISABLE=1 tar -czf "$db" -C "$work" .
        fi
        ;;
    esac
    exit 0
    """)


class PublishThorRepoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.tmp.name)
        self.state, self.bin, self.sys, self.target = t / "state", t / "bin", t / "sys", t / "target"
        self.pkgs, self.gnupg = t / "pkgs", t / "gnupg"
        for d in (self.state, self.bin, self.sys / "block" / "sdz" / "holders", self.target / "etc",
                  self.target / "var" / "lib" / "raytone" / "repo", self.pkgs, self.gnupg, t / "rules", t / "hostetc"):
            d.mkdir(parents=True)
        (self.target / ".raytone-unpacked").write_text("x\n")
        (self.target / "etc" / "arch-release").write_text("")
        # the repository install-thor-omarchy.sh left: omarchy 4.0.4-1 and the nft modules absent
        work = t / "db"
        (work / "omarchy-4.0.4-1").mkdir(parents=True)
        with tarfile.open(self.target / DB, "w:gz") as tf:
            tf.add(work / "omarchy-4.0.4-1", arcname="omarchy-4.0.4-1")
        for tool in ("lsblk", "findmnt", "swapon", "mount", "umount", "chroot", "udevadm", "sync", "setpriv", "gpg"):
            (self.bin / tool).write_text(STUB)
            (self.bin / tool).chmod(0o755)
        dev = t / "dev"
        (dev / "disk" / "by-id").mkdir(parents=True)
        for n in ("sdz", "sdz1", "sdz2"):
            (dev / n).touch()
        self.link = dev / "disk" / "by-id" / f"usb-JZAO_USB3.2_Gen1_{SERIAL}-0:0"
        self.link.symlink_to("../../sdz")
        self.new = [self.pkgs / "omarchy-4.0.4-2-aarch64.pkg.tar.xz",
                    self.pkgs / "raytone-thor-nft-modules-6.8.12.l4t39.2.1-1-aarch64.pkg.tar.xz"]
        for p in self.new:
            p.write_bytes(b"pkg")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args, files=None):
        t = pathlib.Path(self.tmp.name)
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", STATE=str(self.state), TARGET=str(self.target),
                   SERIAL=SERIAL, SIZE=str(SIZE), FPR=FPR, RAYTONE_SYS=str(self.sys), RAYTONE_SKIP_ROOT_CHECK="1",
                   RAYTONE_NO_UNSHARE="1", RAYTONE_TARGET_MOUNT=str(self.target), RAYTONE_HOST_ETC=str(t / "hostetc"),
                   RAYTONE_UDEV_RULES=str(t / "rules"), RAYTONE_SIGNING_HOME=str(self.gnupg))
        files = [str(f) for f in (self.new if files is None else files)]
        return subprocess.run(["bash", str(SCRIPT), "--disk", str(self.link), "--serial", SERIAL, *args, *files],
                              env=env, capture_output=True, text=True)

    def write(self, **kw):
        r = self.run_script("--write", "--confirm-serial", SERIAL, **kw)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r

    def calls(self):
        f = self.state / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def chroot(self):
        return [c[len("in-chroot "):] for c in self.calls() if c.startswith("in-chroot ")]

    def entries(self):
        with tarfile.open(self.target / DB) as tf:
            return sorted({m.name.lstrip("./").split("/")[0] for m in tf.getmembers() if m.name.strip("./")})

    def test_dry_run_mounts_nothing(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry run", r.stdout)
        self.assertIn("omarchy-4.0.4-2-aarch64.pkg.tar.xz", r.stdout)
        self.assertFalse([c for c in self.calls() if c.startswith(("mount", "chroot"))])

    def test_needs_packages(self):
        r = self.run_script(files=[])
        self.assertNotEqual(r.returncode, 0)
        r = self.run_script(files=[self.pkgs / "missing-1-1-any.pkg.tar.xz"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("missing-1-1-any.pkg.tar.xz", r.stderr)

    def test_confirm_serial_is_required_to_write(self):
        r = self.run_script("--write")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse([c for c in self.calls() if c.startswith("mount")])

    def test_refuses_a_drive_without_the_repository(self):
        (self.target / DB).unlink()
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("install-thor-omarchy.sh", r.stderr)
        self.assertFalse(self.chroot())

    def test_never_creates_a_signing_key(self):
        # the drive trusts one key (pacman-key --lsign-key at install); a new key would not verify
        (self.state / "no-key").touch()
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(any("--quick-generate-key" in c for c in self.calls()))

    def test_publishes_exactly_the_named_builds(self):
        self.write()
        repo = self.target / "var" / "lib" / "raytone" / "repo"
        for p in self.new:
            with self.subTest(p=p.name):
                self.assertTrue((repo / p.name).exists())
                self.assertTrue((repo / (p.name + ".sig")).exists())
        adds = [c for c in self.chroot() if c.startswith("repo-add")]
        self.assertEqual(adds, ["repo-add -q /var/lib/raytone/repo/raytone-thor.db.tar.gz "
                                + " ".join(f"/var/lib/raytone/repo/{p.name}" for p in self.new)])
        self.assertEqual(self.entries(), ["omarchy-4.0.4-2", "raytone-thor-nft-modules-6.8.12.l4t39.2.1-1"])

    def test_installs_nothing_on_the_drive(self):
        self.write()
        # read-only key checks (--list-keys, --verify) are expected; nothing installs or changes keys
        self.assertFalse([c for c in self.chroot() if c.startswith("pacman ")
                          or (c.startswith("pacman-key") and c.split()[1] not in ("--list-keys", "--verify"))])

    def test_a_stale_signature_is_replaced(self):
        # a rebuilt package keeps its file name; the old .sig next to it does not match
        stale = self.new[0].with_name(self.new[0].name + ".sig")
        stale.write_text("old")
        self.write()
        self.assertIn(f"sig-by-{FPR}", stale.read_text())

    def test_the_drive_must_trust_the_signing_key(self):
        (self.state / "untrusted").touch()
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("trust", r.stderr)
        self.assertFalse([c for c in self.chroot() if c.startswith("repo-add")])

    def test_each_published_package_verifies_with_the_drives_keyring(self):
        self.write()
        for p in self.new:
            self.assertIn(f"pacman-key --verify /var/lib/raytone/repo/{p.name}.sig /var/lib/raytone/repo/{p.name}",
                          self.chroot())

    def test_links_on_the_drive_cannot_redirect_host_writes(self):
        # the host (JetPack, root) copies into the drive's repository: a link there must not reach it
        victim = pathlib.Path(self.tmp.name) / "host-file"
        victim.write_text("host")
        repo = self.target / "var" / "lib" / "raytone" / "repo"
        for link in ("raytone-thor.gpg", self.new[0].name, self.new[0].name + ".sig"):
            with self.subTest(link=link):
                (repo / link).symlink_to(victim)
                r = self.run_script("--write", "--confirm-serial", SERIAL)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("link", r.stderr)
                self.assertEqual(victim.read_text(), "host")
                (repo / link).unlink()

    def test_a_linked_repository_directory_is_refused(self):
        elsewhere = pathlib.Path(self.tmp.name) / "elsewhere"
        elsewhere.mkdir()
        raytone = self.target / "var" / "lib" / "raytone"
        (raytone / "repo").rename(elsewhere / "repo")
        raytone.rmdir()
        raytone.symlink_to(elsewhere)
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("link", r.stderr)

    def test_the_database_must_list_every_build(self):
        (self.state / "repo-add-noop").touch()
        r = self.run_script("--write", "--confirm-serial", SERIAL)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("omarchy-4.0.4-2", r.stderr)


if __name__ == "__main__":
    unittest.main()
