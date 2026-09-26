"""raytone-thor-nvme-kernel-sync: on the NVMe install, L4TLauncher loads Omarchy's kernel from
JetPack's APP partition (/boot/raytone-thor/Image), so a raytone-thor-linux upgrade copies the new
kernel there; on the USB drive (no /etc/raytone/nvme-boot.conf) it does nothing."""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "raytone-thor-omarchy"
SCRIPT = PKG / "raytone-thor-nvme-kernel-sync"
STUB = '#!/bin/bash\necho "$(basename "$0") $*" >> "$CALLS"\n'


class KernelSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.tmp.name)
        self.bin, self.app, self.mods, self.conf = t / "bin", t / "app", t / "modules", t / "nvme-boot.conf"
        self.bin.mkdir()
        for tool in ("mount", "umount", "sync"):
            (self.bin / tool).write_text(STUB)
            (self.bin / tool).chmod(0o755)
        (self.mods / "6.8.12-1021-tegra").mkdir(parents=True)
        (self.mods / "6.8.12-1021-tegra" / "vmlinuz").write_bytes(b"new kernel")
        (self.mods / "6.8.12-1021-tegra" / "pkgbase").write_text("raytone-thor-linux\n")
        (self.app / "boot" / "raytone-thor").mkdir(parents=True)
        (self.app / "boot" / "raytone-thor" / "Image").write_bytes(b"old kernel")
        self.calls = t / "calls"

    def tearDown(self):
        self.tmp.cleanup()

    def run_sync(self):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", CALLS=str(self.calls),
                   RAYTONE_NVME_BOOT_CONF=str(self.conf), RAYTONE_MODULES=str(self.mods), RAYTONE_APP_MOUNT=str(self.app))
        return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)

    def test_nothing_on_the_usb_drive(self):
        r = self.run_sync()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.calls.exists())
        self.assertEqual((self.app / "boot/raytone-thor/Image").read_bytes(), b"old kernel")

    def test_the_new_kernel_goes_to_app(self):
        self.conf.write_text("APP_PARTUUID=1b3479b0-b4c2-4a1b-8b81-86d864b3944e\nKERNEL=/boot/raytone-thor/Image\n")
        r = self.run_sync()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.app / "boot/raytone-thor/Image").read_bytes(), b"new kernel")
        self.assertIn(f"mount -o noatime /dev/disk/by-partuuid/1b3479b0-b4c2-4a1b-8b81-86d864b3944e {self.app}",
                      self.calls.read_text())
        self.assertIn(f"umount {self.app}", self.calls.read_text())

    def test_refuses_an_app_without_the_port_s_kernel_directory(self):
        self.conf.write_text("APP_PARTUUID=1b3479b0-b4c2-4a1b-8b81-86d864b3944e\nKERNEL=/boot/raytone-thor/Image\n")
        (self.app / "boot" / "raytone-thor" / "Image").unlink()
        (self.app / "boot" / "raytone-thor").rmdir()
        r = self.run_sync()
        self.assertNotEqual(r.returncode, 0)

    def test_the_hook_runs_it_after_kernel_upgrades(self):
        hook = (PKG / "90-raytone-thor-nvme-kernel.hook").read_text()
        for line in ("Target = raytone-thor-linux", "Operation = Upgrade", "When = PostTransaction",
                     "Exec = /usr/lib/raytone/raytone-thor-nvme-kernel-sync"):
            self.assertIn(line, hook.splitlines())


if __name__ == "__main__":
    unittest.main()
