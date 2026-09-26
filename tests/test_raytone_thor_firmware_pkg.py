"""raytone-thor-firmware: what the repack drops from NVIDIA's firmware debs."""
import importlib.util
import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "raytone-thor-firmware"
spec = importlib.util.spec_from_file_location("l4t_repack", PKG / "l4t_repack.py")
repack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repack)


def excludes():
    # run package() with _stage/_repack stubbed: _repack prints the regexes it is given
    out = subprocess.run(["bash", "-c", f"source {PKG}/PKGBUILD; _stage() {{ :; }}; "
                          "_repack() { printf '%s\\n' \"$@\"; }; test() { :; }; pkgdir=/nonexistent; package"],
                         capture_output=True, text=True, check=True).stdout.splitlines()
    return [re.compile(x) for x in out]


class FirmwareRepackTests(unittest.TestCase):
    def dropped(self, path):
        return repack._drop_reason(path, excludes()) is not None

    def test_nvidias_bluetooth_drop_in_is_dropped(self):
        # It runs /usr/libexec/bluetooth/bluetoothd (Ubuntu's path: status=203/EXEC on Arch) and
        # disables BlueZ's audio plugins, which Omarchy's Bluetooth audio needs.
        for p in ("/lib/systemd/system/bluetooth.service.d/nv-bluetooth-service.conf",
                  "/usr/lib/systemd/system/bluetooth.service.d/nv-bluetooth-service.conf"):
            with self.subTest(p=p):
                self.assertTrue(self.dropped(p))

    def test_thor_firmware_is_kept(self):
        self.assertFalse(self.dropped("/lib/firmware/nvidia/595.78/gsp_ga10x.bin"))


if __name__ == "__main__":
    unittest.main()
