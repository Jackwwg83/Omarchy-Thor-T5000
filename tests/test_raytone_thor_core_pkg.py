"""raytone-thor-core: the groups NVIDIA's udev rules (99-tegra-devices.rules) name must exist."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKGBUILD = (ROOT / "packages" / "raytone-thor-core" / "PKGBUILD").read_text()


class CoreGroupsTests(unittest.TestCase):
    def sysusers(self):
        m = re.search(r"sysusers\.d/raytone-thor\.conf\" <<'EOF'\n(.*?)\nEOF", PKGBUILD, re.S)
        self.assertIsNotNone(m)
        return [line.split()[1] for line in m.group(1).splitlines() if line.startswith("g ")]

    def test_groups_the_tegra_udev_rules_use(self):
        # udevd on the Thor: "99-tegra-devices.rules:51 Failed to resolve group 'debug'" (11 rules,
        # the GPU debugger and profiler nodes); trusty and crypto as on JetPack
        for group in ("trusty", "crypto", "debug"):
            self.assertIn(group, self.sysusers())


if __name__ == "__main__":
    unittest.main()


class CudaDriverTests(unittest.TestCase):
    """Slice 3.0: libcuda from L4T's cuda-openrm, wired as JetPack's nv-load-gpu-libs.sh does for
    the OpenRM variant (the service stays disabled; its outcome is static package content)."""

    def test_cuda_debs_are_repackaged(self):
        import subprocess
        debs = subprocess.run(["bash", "-c", f"source {ROOT}/packages/raytone-thor-core/PKGBUILD; "
                               "printf '%s\\n' \"${_l4t_debs[@]}\""], capture_output=True, text=True,
                              check=True).stdout.split()
        for deb in ("nvidia-l4t-cuda", "nvidia-l4t-cuda-openrm", "nvidia-l4t-cuda-utils"):
            self.assertIn(deb, debs)

    def wiring(self):
        import pathlib
        import subprocess
        import tempfile
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        out = pathlib.Path(t.name)
        subprocess.run(["bash", "-c", f"source {ROOT}/packages/raytone-thor-core/PKGBUILD; "
                        f"pkgdir={out}; _gpu_libs_wiring"], check=True)
        return out

    def test_loader_finds_libcuda_in_the_openrm_directory(self):
        out = self.wiring()
        self.assertEqual((out / "etc/ld.so.conf.d/000-nvidia-gpu-libs.conf").read_text(),
                         "/opt/nvidia/l4t-gpu-libs/openrm\n")
        for link in ("libcuda.so", "libcuda.so.1"):
            with self.subTest(link=link):
                p = out / "usr/lib/aarch64-linux-gnu" / link
                self.assertTrue(p.is_symlink())
                self.assertEqual(str(p.readlink()), f"/opt/nvidia/l4t-gpu-libs/openrm/{link}")

    def test_containers_get_libcuda_through_the_l4t_csv(self):
        out = self.wiring()
        self.assertEqual((out / "etc/nvidia-container-runtime/host-files-for-container.d/l4t.csv").read_text(),
                         "lib, /opt/nvidia/l4t-gpu-libs/openrm/libcuda.so.1.1\n"
                         "lib, /opt/nvidia/l4t-gpu-libs/openrm/libcuda_instrumentation.so\n")

    def test_no_cuda_stub_on_the_loader_path(self):
        text = (ROOT / "packages/raytone-thor-core/PKGBUILD").read_text()
        self.assertNotIn("stubs", text)
