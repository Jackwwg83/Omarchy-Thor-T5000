import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_package", ROOT / "scripts" / "check_package.py")
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)


class CheckTests(unittest.TestCase):
    def test_clean_package_passes(self):
        self.assertEqual(cp.problems(["usr/bin/nvpmodel", "etc/nvpmodel/x.conf", "usr/lib/raytone-l4t/libnvos.so",
                                      ".PKGINFO", ".MTREE"]), [])

    def test_files_under_merged_usr_symlinks_fail(self):
        for path in ("lib/modules/k/a.ko", "bin/x", "sbin/y", "usr/sbin/z"):
            with self.subTest(path=path):
                self.assertTrue(cp.problems([path]))

    def test_prohibited_paths_fail(self):
        self.assertTrue(cp.problems(["usr/bin/nv_update_engine"]))
        self.assertTrue(cp.problems(["usr/lib/systemd/system/nv-l4t-bootloader-config.service"]))

    def test_generic_libraries_in_the_loader_directory_fail(self):
        for lib in ("libvulkan.so.1", "libgbm.so.1", "libEGL.so.1", "libwayland-client.so.0", "libdrm.so.2", "libv4l2.so.0"):
            with self.subTest(lib=lib):
                self.assertTrue(cp.problems([f"usr/lib/raytone-l4t/{lib}"]))

    def test_whole_nvidia_directory_on_the_loader_path_fails(self):
        self.assertTrue(cp.problems(["etc/ld.so.conf.d/nvidia-tegra.conf"], contents={
            "etc/ld.so.conf.d/nvidia-tegra.conf": "/usr/lib/aarch64-linux-gnu/nvidia\n"}))
        self.assertEqual(cp.problems(["etc/ld.so.conf.d/raytone-l4t.conf"], contents={
            "etc/ld.so.conf.d/raytone-l4t.conf": "/usr/lib/raytone-l4t\n"}), [])


if __name__ == "__main__":
    unittest.main()
