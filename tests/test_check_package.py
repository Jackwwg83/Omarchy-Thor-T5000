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


NV = "usr/lib/aarch64-linux-gnu/nvidia"
ICD = '{"file_format_version": "1.0.0", "ICD": {"library_path": "%s"}}'


class RegistrationTests(unittest.TestCase):
    """glvnd vendor, EGL external platform and Vulkan ICD files must name a library the package ships."""

    # Loader paths (Codex, Slice 3 review): what a package's ld.so.conf.d entries put on the path.
    CUDA = ["etc/ld.so.conf.d/000_cuda.conf", "usr/local/cuda", "usr/local/cuda-13.2/targets/sbsa-linux/lib/libcublas.so.13",
            "usr/local/cuda-13.2/targets/sbsa-linux/lib/stubs/libcuda.so"]
    CUDA_LINKS = {"usr/local/cuda": "cuda-13.2"}

    def test_cuda_loader_path_through_its_link_passes(self):
        self.assertEqual(cp.problems(self.CUDA, contents={"etc/ld.so.conf.d/000_cuda.conf":
                                                          "/usr/local/cuda/targets/sbsa-linux/lib\n"}, links=self.CUDA_LINKS), [])

    def test_a_stub_directory_on_the_loader_path_fails(self):
        found = cp.problems(self.CUDA, contents={"etc/ld.so.conf.d/000_cuda.conf":
                                                 "# comment\n/usr/local/cuda/targets/sbsa-linux/lib/stubs\n"}, links=self.CUDA_LINKS)
        self.assertTrue(any("stub" in f for f in found), found)

    def test_a_link_to_a_stub_directory_on_the_loader_path_fails(self):
        found = cp.problems(["etc/ld.so.conf.d/x.conf", "opt/x/lib", "opt/x/stubs/libcuda.so"],
                            contents={"etc/ld.so.conf.d/x.conf": "/opt/x/lib\n"}, links={"opt/x/lib": "stubs"})
        self.assertTrue(any("stub" in f for f in found), found)

    def test_an_arch_library_name_as_a_link_in_a_loader_directory_fails(self):
        found = cp.problems(["etc/ld.so.conf.d/x.conf", "opt/x/lib/libstdc++.so.6", "opt/x/lib/real.so"],
                            contents={"etc/ld.so.conf.d/x.conf": "/opt/x/lib\n"},
                            links={"opt/x/lib/libstdc++.so.6": "real.so"})
        self.assertTrue(any("shadow" in f for f in found), found)

    def test_a_system_directory_on_the_loader_path_fails(self):
        for d in ("/usr/lib", "/lib", "/usr/lib/"):
            with self.subTest(d=d):
                self.assertTrue(cp.problems(["etc/ld.so.conf.d/x.conf"], contents={"etc/ld.so.conf.d/x.conf": d + "\n"}))

    def test_a_loader_directory_with_arch_libraries_fails(self):
        for lib in ("libstdc++.so.6", "libc.so.6", "libgcc_s.so.1", "libz.so.1", "libOpenCL.so.1", "libEGL.so.1"):
            with self.subTest(lib=lib):
                found = cp.problems(["etc/ld.so.conf.d/x.conf", f"opt/x/lib/{lib}"],
                                    contents={"etc/ld.so.conf.d/x.conf": "/opt/x/lib\n"})
                self.assertTrue(any("shadow" in f for f in found), found)

    def test_bare_soname_resolves_through_the_loader_directory(self):
        paths = [f"{NV}/libGLX_nvidia.so.0", "usr/lib/raytone-l4t/libGLX_nvidia.so.0", "etc/vulkan/icd.d/nvidia_icd.json"]
        links = {"usr/lib/raytone-l4t/libGLX_nvidia.so.0": f"/{NV}/libGLX_nvidia.so.0"}
        contents = {"etc/vulkan/icd.d/nvidia_icd.json": ICD % "libGLX_nvidia.so.0"}
        self.assertEqual(cp.problems(paths, contents, links), [])

    def test_bare_soname_outside_the_loader_directory_fails(self):
        paths = [f"{NV}/libGLX_nvidia.so.0", "etc/vulkan/icd.d/nvidia_icd.json"]
        contents = {"etc/vulkan/icd.d/nvidia_icd.json": ICD % "libGLX_nvidia.so.0"}
        self.assertTrue(cp.problems(paths, contents, {}))

    def test_absolute_path_through_relative_links(self):
        paths = [f"{NV}/libnvidia-egl-gbm.so.1.1.0", f"{NV}/libnvidia-egl-gbm.so.1",
                 "usr/share/egl/egl_external_platform.d/15_nvidia_gbm.json"]
        links = {f"{NV}/libnvidia-egl-gbm.so.1": "libnvidia-egl-gbm.so.1.1.0"}
        contents = {"usr/share/egl/egl_external_platform.d/15_nvidia_gbm.json": ICD % f"/{NV}/libnvidia-egl-gbm.so.1"}
        self.assertEqual(cp.problems(paths, contents, links), [])

    def test_dangling_library_fails(self):
        paths = [f"{NV}/libnvidia-egl-gbm.so.1", "usr/share/egl/egl_external_platform.d/15_nvidia_gbm.json"]
        links = {f"{NV}/libnvidia-egl-gbm.so.1": "libnvidia-egl-gbm.so.1.1.0"}
        contents = {"usr/share/egl/egl_external_platform.d/15_nvidia_gbm.json": ICD % f"/{NV}/libnvidia-egl-gbm.so.1"}
        self.assertTrue(cp.problems(paths, contents, links))

    def test_unreadable_registration_fails(self):
        for text in (None, "not json", '{"ICD": {}}'):
            with self.subTest(text=text):
                contents = {} if text is None else {"usr/share/glvnd/egl_vendor.d/10_nvidia.json": text}
                self.assertTrue(cp.problems(["usr/share/glvnd/egl_vendor.d/10_nvidia.json"], contents, {}))

    def test_resolve_follows_absolute_and_relative_links(self):
        links = {"etc/vulkan/icd.d/nvidia_icd.json": f"/{NV}/nvidia_icd.json",
                 "usr/share/glvnd/egl_vendor.d/10_nvidia.json": "../../../lib/aarch64-linux-gnu/tegra-egl/nvidia.json"}
        self.assertEqual(cp.resolve("etc/vulkan/icd.d/nvidia_icd.json", links), f"{NV}/nvidia_icd.json")
        self.assertEqual(cp.resolve("usr/share/glvnd/egl_vendor.d/10_nvidia.json", links),
                         "usr/lib/aarch64-linux-gnu/tegra-egl/nvidia.json")
        self.assertIsNone(cp.resolve("a", {"a": "b", "b": "a"}))


if __name__ == "__main__":
    unittest.main()
