"""raytone-thor-leetop-nic: the vendor network and Bluetooth files the Thor's JetPack install uses."""
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "raytone-thor-leetop-nic"

# sha256 of the files on the Thor's JetPack (vendor-installed, owned by no deb), 2026-09-26
BT_FIRMWARE = {"rtl8852bu_fw": "491eff44dc00b164d13bc9ff3f6bcda8c9d39039284c42292ef059b38771bc63",
               "rtl8852bu_config": "2f9968b88d3f434fd67ffa00387fb7eaf0f04e2f9d04e6c5e22f39d359a53c4a"}


def arrays():
    out = subprocess.run(["bash", "-c", f"source {PKG}/PKGBUILD; paste -d' ' <(printf '%s\\n' \"${{source[@]}}\") "
                          "<(printf '%s\\n' \"${sha256sums[@]}\")"], capture_output=True, text=True, check=True).stdout
    return dict(line.split() for line in out.splitlines())


class LeetopNicTests(unittest.TestCase):
    def test_bluetooth_firmware_is_jetpacks_pinned(self):
        # rtk_btusb (bda:b85b, RTL8852BU) asks for rtl8852bu_fw and rtl8852bu_config; without them:
        # "Direct firmware load for rtl8852bu_fw failed with error -2"
        pins = arrays()
        for name, digest in BT_FIRMWARE.items():
            self.assertEqual(pins.get(name), digest)

    def test_bluetooth_firmware_goes_where_the_kernel_looks_first(self):
        # firmware_class.path=/etc/firmware on the Thor's command line, as for the Wi-Fi firmware
        text = (PKG / "PKGBUILD").read_text()
        for name in BT_FIRMWARE:
            self.assertIn(f'"$pkgdir/etc/firmware/{name}"', text)

    def test_no_vendor_file_is_committed(self):
        for name in list(BT_FIRMWARE) + ["8852be.ko", "r8125.ko", "rtw8852b_fw-1.bin", "rtw8852b_fw.bin"]:
            self.assertFalse((PKG / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
