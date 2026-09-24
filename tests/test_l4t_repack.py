import importlib.util
import json
import os
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("l4t_repack", ROOT / "scripts" / "l4t_repack.py")
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)


class MapPathTests(unittest.TestCase):
    def test_merged_usr_layout(self):
        cases = {
            "/lib/modules/6.8.12-1021-tegra/kernel/a.ko": "/usr/lib/modules/6.8.12-1021-tegra/kernel/a.ko",
            "/lib/firmware/nvidia/595.78/gsp_ga10x.bin": "/usr/lib/firmware/nvidia/595.78/gsp_ga10x.bin",
            "/lib/udev/rules.d/99-tegra.rules": "/usr/lib/udev/rules.d/99-tegra.rules",
            "/etc/udev/rules.d/99-nv.rules": "/usr/lib/udev/rules.d/99-nv.rules",
            "/lib/systemd/system/nvfancontrol.service": "/usr/lib/systemd/system/nvfancontrol.service",
            "/etc/systemd/system/nvpmodel.service": "/usr/lib/systemd/system/nvpmodel.service",
            "/usr/sbin/nvpmodel": "/usr/bin/nvpmodel",
            "/sbin/tool": "/usr/bin/tool",
            "/bin/tool2": "/usr/bin/tool2",
            "/lib/libx.so": "/usr/lib/libx.so",
            "/usr/lib/aarch64-linux-gnu/nvidia/libcuda.so": "/usr/lib/aarch64-linux-gnu/nvidia/libcuda.so",
            "/etc/nvpmodel/nvpmodel_p3834_0008.conf": "/etc/nvpmodel/nvpmodel_p3834_0008.conf",
            "/opt/nvidia/l4t-gpu-libs/openrm/libcuda.so.1": "/opt/nvidia/l4t-gpu-libs/openrm/libcuda.so.1",
        }
        for src, want in cases.items():
            with self.subTest(src=src):
                self.assertEqual(rp.map_path(src), want)

    def test_enablement_links_and_debian_metadata_are_dropped(self):
        for src in ("/etc/systemd/system/multi-user.target.wants/nvpmodel.service",
                    "/etc/systemd/system/sysinit.target.wants/x.service",
                    "/usr/share/lintian/overrides/nvidia-l4t-core", "/usr/share/doc/nvidia-l4t-core/changelog.Debian.gz"):
            with self.subTest(src=src):
                self.assertIsNone(rp.map_path(src))

    def test_copyright_becomes_a_license_file(self):
        self.assertEqual(rp.map_path("/usr/share/doc/nvidia-l4t-core/copyright", pkgname="raytone-thor-core"),
                         "/usr/share/licenses/raytone-thor-core/nvidia-l4t-core.copyright")

    def test_license_files_in_doc_become_license_files(self):
        for name in ("LICENSE.libEGL_nvidia", "LICENSE.libnvidia-rtcore.gz", "LICENSE"):
            with self.subTest(name=name):
                self.assertEqual(rp.map_path(f"/usr/share/doc/nvidia-l4t-3d-core/{name}", pkgname="raytone-thor-graphics"),
                                 f"/usr/share/licenses/raytone-thor-graphics/nvidia-l4t-3d-core.{name}")
        self.assertIsNone(rp.map_path("/usr/share/doc/nvidia-l4t-3d-core/README.LICENSES.txt.gz"))

    def test_prohibited_items_are_dropped(self):
        for src in ("/usr/sbin/nv_update_engine", "/usr/sbin/nv_part_update", "/opt/ota/TEGRA_BL.Cap",
                    "/etc/systemd/system/nv-l4t-bootloader-config.service"):
            with self.subTest(src=src):
                self.assertIsNone(rp.map_path(src))

    def test_extra_excludes(self):
        self.assertIsNone(rp.map_path("/etc/skel/Desktop/nv_forums.desktop", exclude=[r"^/etc/skel/"]))


class RepackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = pathlib.Path(self.tmp.name)
        self.out = self.t / "pkg"

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self, name, files, links=()):
        root = self.t / name
        for path, mode in files:
            p = root / path.lstrip("/")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(path)
            p.chmod(mode)
        for path, target in links:
            p = root / path.lstrip("/")
            p.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, p)
        return root

    def test_files_land_at_mapped_paths_with_modes(self):
        s = self.stage("a", [("/usr/sbin/nvpmodel", 0o755), ("/etc/nvpmodel/x.conf", 0o644)])
        report = rp.repack([s], self.out, pkgname="raytone-thor-core")
        self.assertEqual((self.out / "usr/bin/nvpmodel").stat().st_mode & 0o777, 0o755)
        self.assertTrue((self.out / "etc/nvpmodel/x.conf").is_file())
        self.assertIn("/usr/bin/nvpmodel", report["kept"])

    def test_absolute_symlinks_are_retargeted(self):
        s = self.stage("a", [("/lib/firmware/a.bin", 0o644)], links=[("/lib/firmware/b.bin", "/lib/firmware/a.bin"),
                                                                        ("/usr/lib/rel.so", "rel.so.1")])
        rp.repack([s], self.out, pkgname="p")
        self.assertEqual(os.readlink(self.out / "usr/lib/firmware/b.bin"), "/usr/lib/firmware/a.bin")
        self.assertEqual(os.readlink(self.out / "usr/lib/rel.so"), "rel.so.1")

    def test_two_debs_writing_the_same_path_is_an_error(self):
        a = self.stage("a", [("/usr/bin/x", 0o755)])
        b = self.stage("b", [("/bin/x", 0o755)])
        with self.assertRaises(rp.RepackError):
            rp.repack([a, b], self.out, pkgname="p")

    def test_nothing_is_written_under_merged_usr_symlink_directories(self):
        s = self.stage("a", [("/lib/modules/k/a.ko", 0o644), ("/sbin/t", 0o755), ("/bin/u", 0o755)])
        rp.repack([s], self.out, pkgname="p")
        for top in ("lib", "sbin", "bin", "usr/sbin"):
            self.assertFalse((self.out / top).exists(), top)

    def test_report_lists_dropped_items_with_reasons(self):
        s = self.stage("a", [("/usr/sbin/nv_update_engine", 0o755), ("/usr/share/doc/p/changelog.gz", 0o644)])
        report = rp.repack([s], self.out, pkgname="p")
        self.assertEqual(report["dropped"]["/usr/sbin/nv_update_engine"], "prohibited")
        self.assertEqual(report["dropped"]["/usr/share/doc/p/changelog.gz"], "debian metadata")
        json.dumps(report)


if __name__ == "__main__":
    unittest.main()
