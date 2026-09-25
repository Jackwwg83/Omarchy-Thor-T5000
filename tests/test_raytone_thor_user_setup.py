"""raytone-thor-user-setup: the Thor layer's per-user parts (the pre-refresh-pacman hook, the menu's
hidden entries) reach users that already exist when raytone-thor-omarchy is installed or upgraded;
/etc/skel alone only reaches new users."""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "raytone-thor-omarchy"
CMD = PKG / "raytone-thor-user-setup"
HOOK = ".config/omarchy/hooks/pre-refresh-pacman.d/10-raytone-thor"
MENU = ".config/omarchy/extensions/omarchy-menu.jsonc"


class UserSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.tmp.name)
        self.homes, self.bin = t / "home", t / "bin"
        self.bin.mkdir()
        (self.homes / "nvidia" / ".config" / "omarchy").mkdir(parents=True)  # an Omarchy user
        (self.homes / "other").mkdir()                                       # not one
        (self.bin / "runuser").write_text('#!/bin/bash\necho "runuser $*" >> "$CALLS"\n'
                                          'while [[ $1 != -- ]]; do shift; done; shift; exec "$@"\n')
        (self.bin / "runuser").chmod(0o755)
        (self.bin / "raytone-thor-menu-extension").symlink_to(PKG / "raytone-thor-menu-extension")
        self.calls = t / "calls"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cmd(self):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", CALLS=str(self.calls),
                   RAYTONE_HOMES=str(self.homes), RAYTONE_SKEL=str(PKG / "skel"))
        r = subprocess.run(["bash", str(CMD)], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_existing_omarchy_users_get_the_hook_and_the_menu(self):
        self.run_cmd()
        home = self.homes / "nvidia"
        self.assertEqual((home / HOOK).read_text(), (PKG / "skel" / HOOK).read_text())
        self.assertIn("BEGIN raytone-thor", (home / MENU).read_text())

    def test_it_acts_as_the_user(self):
        self.run_cmd()
        calls = self.calls.read_text().splitlines()
        self.assertTrue(calls)
        user = subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
        for c in calls:
            self.assertTrue(c.startswith(f"runuser -u {user} -- "), c)

    def test_homes_without_omarchy_are_left_alone(self):
        self.run_cmd()
        self.assertEqual(list((self.homes / "other").iterdir()), [])

    def test_a_failing_menu_merge_does_not_fail_the_package(self):
        (self.homes / "nvidia" / ".config" / "omarchy" / "extensions").mkdir()
        (self.homes / "nvidia" / MENU).write_text("not jsonc\n")
        r = self.run_cmd()
        self.assertIn("nvidia", r.stderr)
        self.assertTrue((self.homes / "nvidia" / HOOK).exists())

    def test_the_package_runs_it_on_install_and_upgrade(self):
        text = (PKG / "raytone-thor-omarchy.install").read_text()
        for fn in ("post_install", "post_upgrade"):
            self.assertIn(fn, text)
        self.assertIn("raytone-thor-user-setup", text)
        self.assertIn("install=raytone-thor-omarchy.install", (PKG / "PKGBUILD").read_text())


if __name__ == "__main__":
    unittest.main()
