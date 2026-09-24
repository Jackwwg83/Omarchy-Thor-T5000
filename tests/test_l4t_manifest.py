import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("l4t_manifest", ROOT / "scripts" / "l4t_manifest.py")
l4t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(l4t)

PACKAGES = """\
Package: nvidia-l4t-core
Architecture: arm64
Version: 39.2.1-20260806224157
Filename: pool/main/n/nvidia-l4t-core/nvidia-l4t-core_39.2.1-20260806224157_arm64.deb
Size: 1234
SHA256: aaaa
Description: NVIDIA Core Package
 A continuation line that is part of the description.

Package: nvidia-l4t-core
Architecture: arm64
Version: 39.2.0-20260601000000
Filename: pool/main/n/nvidia-l4t-core/nvidia-l4t-core_39.2.0-20260601000000_arm64.deb
Size: 1200
SHA256: bbbb

Package: nvidia-l4t-bootloader
Architecture: arm64
Version: 39.2.1-20260806224157
Filename: pool/main/n/nvidia-l4t-bootloader/nvidia-l4t-bootloader_39.2.1-20260806224157_arm64.deb
Size: 99
SHA256: cccc
"""


class ParseTests(unittest.TestCase):
    def test_parses_stanzas_and_ignores_continuation_lines(self):
        stanzas = l4t.parse_packages(PACKAGES)
        self.assertEqual(len(stanzas), 3)
        self.assertEqual(stanzas[0]["Package"], "nvidia-l4t-core")
        self.assertEqual(stanzas[0]["SHA256"], "aaaa")
        self.assertTrue(stanzas[0]["Description"].startswith("NVIDIA Core Package"))

    def test_selects_the_exact_version(self):
        entry = l4t.select(l4t.parse_packages(PACKAGES), "nvidia-l4t-core", "39.2.1-20260806224157",
                           base="https://repo.example/jetson/common")
        self.assertEqual(entry["sha256"], "aaaa")
        self.assertEqual(entry["size"], 1234)
        self.assertEqual(entry["url"], "https://repo.example/jetson/common/pool/main/n/nvidia-l4t-core/"
                                       "nvidia-l4t-core_39.2.1-20260806224157_arm64.deb")

    def test_missing_version_is_an_error(self):
        with self.assertRaises(l4t.ManifestError):
            l4t.select(l4t.parse_packages(PACKAGES), "nvidia-l4t-core", "1.0", base="https://x")

    def test_duplicate_stanza_is_an_error(self):
        doubled = l4t.parse_packages(PACKAGES + "\n" + PACKAGES.split("\n\n")[0])
        with self.assertRaises(l4t.ManifestError):
            l4t.select(doubled, "nvidia-l4t-core", "39.2.1-20260806224157", base="https://x")


class ProhibitedTests(unittest.TestCase):
    def test_prohibited_packages_are_refused(self):
        for name in ("nvidia-l4t-bootloader", "nvidia-l4t-bootloader-utils", "nvidia-l4t-kernel-partitions",
                     "nvidia-l4t-firstboot", "nvidia-l4t-oobe"):
            with self.subTest(name=name), self.assertRaises(l4t.ManifestError):
                l4t.select(l4t.parse_packages(PACKAGES.replace("nvidia-l4t-bootloader", name)), name,
                           "39.2.1-20260806224157", base="https://x")

    def test_prohibited_file_paths(self):
        for path in ("/usr/sbin/nv_update_engine", "/usr/sbin/nv_part_update", "/usr/sbin/nvbootctrl",
                     "/usr/sbin/gen_luks.sh", "/usr/sbin/nv_create_usbkey.sh", "/opt/ota_package/x.Cap",
                     "/boot/efi/EFI/UpdateCapsule/TEGRA_BL.Cap", "/etc/systemd/system/nv-l4t-bootloader-config.service",
                     "/etc/systemd/system/nvfb-udev.service", "/usr/sbin/nv-oobe", "/usr/lib/nvidia/nv_update_verifier",
                     "/usr/lib/fwupd/plugins/x.so"):
            with self.subTest(path=path):
                self.assertTrue(l4t.prohibited_path(path))

    def test_ordinary_paths_are_allowed(self):
        for path in ("/usr/bin/tegrastats", "/usr/bin/jetson_clocks", "/usr/lib/aarch64-linux-gnu/nvidia/libcuda.so",
                     "/lib/modules/6.8.12-1021-tegra/updates/opensource-gpu-disp/nvidia.ko", "/etc/nvpmodel.conf"):
            with self.subTest(path=path):
                self.assertFalse(l4t.prohibited_path(path))


class BuildTests(unittest.TestCase):
    def test_build_writes_sorted_manifest_with_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            idx = pathlib.Path(d) / "Packages"
            idx.write_text(PACKAGES)
            wanted = {"nvidia-l4t-core": "39.2.1-20260806224157"}
            manifest = l4t.build([("https://repo.example/jetson/common", idx)], wanted, release="r39.2")
            self.assertEqual(manifest["release"], "r39.2")
            self.assertEqual([p["name"] for p in manifest["packages"]], ["nvidia-l4t-core"])
            json.dumps(manifest)  # serialisable

    def test_build_refuses_an_empty_wanted_list(self):
        with tempfile.TemporaryDirectory() as d:
            idx = pathlib.Path(d) / "Packages"
            idx.write_text(PACKAGES)
            with self.assertRaises(l4t.ManifestError):
                l4t.build([("https://x", idx)], {}, release="r39.2")

    def test_build_fails_when_a_wanted_package_is_absent_from_every_index(self):
        with tempfile.TemporaryDirectory() as d:
            idx = pathlib.Path(d) / "Packages"
            idx.write_text(PACKAGES)
            with self.assertRaises(l4t.ManifestError):
                l4t.build([("https://x", idx)], {"nvidia-l4t-cuda-openrm": "39.2.1-20260806224157"}, release="r39.2")


if __name__ == "__main__":
    unittest.main()
