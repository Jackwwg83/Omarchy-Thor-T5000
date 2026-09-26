"""omarchy-refresh-pacman (also behind omarchy-channel-set) copies upstream's x86_64 pacman.conf and
mirrorlist, then runs the pre-refresh-pacman hook, then pacman -Syyuu. The Thor's hook puts the Thor
templates back before that sync."""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "raytone-thor-omarchy"
RESTORE = PKG / "raytone-thor-pacman-restore"
HOOK = PKG / "skel" / ".config" / "omarchy" / "hooks" / "pre-refresh-pacman.d" / "10-raytone-thor"


class PacmanRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.etc = pathlib.Path(self.tmp.name) / "etc"
        (self.etc / "pacman.d").mkdir(parents=True)
        (self.etc / "pacman.conf").write_text("[multilib]\nInclude = /etc/pacman.d/mirrorlist\n")
        (self.etc / "pacman.d" / "mirrorlist").write_text("Server = https://stable-mirror.omarchy.org/$repo/os/$arch\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_restore(self, templates=PKG / "pacman"):
        env = dict(os.environ, RAYTONE_ETC=str(self.etc), RAYTONE_PACMAN_TEMPLATES=str(templates))
        return subprocess.run(["bash", str(RESTORE)], env=env, capture_output=True, text=True)

    def test_puts_the_thor_templates_back(self):
        r = self.run_restore()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.etc / "pacman.conf").read_text(), (PKG / "pacman" / "pacman.conf").read_text())
        self.assertEqual((self.etc / "pacman.d" / "mirrorlist").read_text(),
                         (PKG / "pacman" / "mirrorlist").read_text())
        self.assertEqual((self.etc / "pacman.conf").stat().st_mode & 0o777, 0o644)

    def test_fails_loudly_without_templates(self):
        r = self.run_restore(pathlib.Path(self.tmp.name) / "missing")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("[multilib]", (self.etc / "pacman.conf").read_text())


class HookTests(unittest.TestCase):
    def test_hook_runs_the_restore_as_root(self):
        with tempfile.TemporaryDirectory() as t:
            stub = pathlib.Path(t) / "sudo"
            stub.write_text('#!/bin/bash\necho "sudo $*" >> "$CALLS"\n')
            stub.chmod(0o755)
            calls = pathlib.Path(t) / "calls"
            env = dict(os.environ, PATH=f"{t}:{os.environ['PATH']}", CALLS=str(calls))
            # omarchy-hook runs each file in the .d directory with bash
            r = subprocess.run(["bash", str(HOOK)], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(calls.read_text().split(), ["sudo", "/usr/bin/raytone-thor-pacman-restore"])

    def test_hook_is_packaged_into_skel_and_the_restore_into_usr_bin(self):
        text = (PKG / "PKGBUILD").read_text()
        self.assertIn("etc/skel/.config/omarchy/hooks/pre-refresh-pacman.d/10-raytone-thor", text)
        self.assertIn("usr/bin/raytone-thor-pacman-restore", text)


if __name__ == "__main__":
    unittest.main()
