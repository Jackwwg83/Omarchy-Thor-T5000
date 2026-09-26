"""raytone-thor-cuda: CUDA 13.2 from NVIDIA's jetson/common r39.2 (the SBSA toolkit), repackaged as
Ubuntu installs it, for the Thor's gcc 16 host compiler."""
import json
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "raytone-thor-cuda"


def pkgbuild(expr):
    return subprocess.run(["bash", "-c", f"source {PKG}/PKGBUILD; {expr}"],
                          capture_output=True, text=True, check=True).stdout


class CudaPackageTests(unittest.TestCase):
    def test_sources_are_the_pinned_manifest(self):
        manifest = json.loads((ROOT / "manifests" / "cuda-13.2.json").read_text())
        sources = pkgbuild('printf "%s\\n" "${source[@]}"').split()
        sums = pkgbuild('printf "%s\\n" "${sha256sums[@]}"').split()
        pinned = {s.split("::")[-1]: h for s, h in zip(sources, sums)}
        self.assertEqual(len(manifest["packages"]), 16)
        for p in manifest["packages"]:
            with self.subTest(p=p["name"]):
                self.assertEqual(pinned.get(p["url"]), p["sha256"])

    def test_the_repack_tools_are_the_ones_in_scripts(self):
        for tool in ("l4t_repack.py", "l4t_manifest.py"):
            self.assertEqual((PKG / tool).read_bytes(), (ROOT / "scripts" / tool).read_bytes())

    def layout(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        out = pathlib.Path(t.name)
        subprocess.run(["bash", "-c", f"source {PKG}/PKGBUILD; pkgdir={out}; _cuda_layout"], check=True)
        return out

    def test_versionless_links_as_update_alternatives_makes_them(self):
        # the config-common debs' postinst: update-alternatives for /usr/local/cuda and cuda-13;
        # their ld.so.conf.d entries (kept) name those links
        out = self.layout()
        for link in ("cuda", "cuda-13"):
            with self.subTest(link=link):
                p = out / "usr/local" / link
                self.assertTrue(p.is_symlink())
                self.assertEqual(str(p.readlink()), "cuda-13.2")

    def test_nvcc_uses_gcc_16_in_cxx17_mode(self):
        # Verified on the Thor: gcc 16 defaults to C++20, whose libstdc++ headers nvcc's front end
        # rejects (char8_t, __builtin_is_virtual_base_of); -std=c++17 builds and runs the smoke test.
        env = (self.layout() / "etc/profile.d/raytone-cuda.sh").read_text()
        self.assertIn('NVCC_PREPEND_FLAGS="-allow-unsupported-compiler -std=c++17"', env)
        self.assertIn("/usr/local/cuda/bin", env)

    def test_cublas_static_libraries_are_left_out(self):
        import importlib.util
        import re
        spec = importlib.util.spec_from_file_location("l4t_repack", PKG / "l4t_repack.py")
        repack = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(repack)
        stub = "_stage() { :; }; _cuda_layout() { :; }; _repack() { printf '%s\\n' \"$@\"; }; test() { :; }; package"
        rx = [re.compile(x) for x in pkgbuild(stub).splitlines()]
        lib = "/usr/local/cuda-13.2/targets/sbsa-linux/lib/"
        for dropped in ("libcublas_static.a", "libcublasLt_static.a"):
            self.assertIsNotNone(repack._drop_reason(lib + dropped, rx))
        # nvcc links the CUDA runtime statically by default: those archives stay
        for kept in ("libcudart_static.a", "libcudadevrt.a", "libculibos.a", "libcublas.so.13"):
            self.assertIsNone(repack._drop_reason(lib + kept, rx))

    def test_the_packaged_loader_paths_pass_the_checker(self):
        # The loader configuration comes from NVIDIA's debs (cuda-toolkit-config-common): recorded
        # from the built package on the Thor, 2026-09-26. With the package's layout links, the checker
        # must accept it and must refuse the same package with a stubs entry.
        import importlib.util
        spec = importlib.util.spec_from_file_location("check_package", ROOT / "scripts" / "check_package.py")
        cp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cp)
        lib = "usr/local/cuda-13.2/targets/sbsa-linux/lib/"
        paths = ["etc/ld.so.conf.d/000_cuda.conf", "etc/ld.so.conf.d/987_cuda-13.conf", "usr/local/cuda",
                 "usr/local/cuda-13", lib + "libcublas.so.13", lib + "libcudart.so.13", lib + "stubs/libcuda.so"]
        links = {"usr/local/cuda": "cuda-13.2", "usr/local/cuda-13": "cuda-13.2"}
        contents = {"etc/ld.so.conf.d/000_cuda.conf": "/usr/local/cuda/targets/sbsa-linux/lib\n",
                    "etc/ld.so.conf.d/987_cuda-13.conf": "/usr/local/cuda-13/targets/sbsa-linux/lib\n"}
        self.assertEqual(cp.problems(paths, contents, links), [])
        contents["etc/ld.so.conf.d/000_cuda.conf"] += "/usr/local/cuda/targets/sbsa-linux/lib/stubs\n"
        self.assertTrue(cp.problems(paths, contents, links))

    def test_depends_on_the_driver_and_the_host_compiler(self):
        depends = pkgbuild('printf "%s\\n" "${depends[@]}"').split()
        self.assertIn("raytone-thor-core", depends)
        self.assertIn("gcc", depends)


if __name__ == "__main__":
    unittest.main()
