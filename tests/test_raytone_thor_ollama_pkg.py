"""raytone-thor-ollama: Ollama's official arm64 build, pinned, with only its CUDA 13 backend (the one
that runs on the Thor's sm_110), as a service like Arch's ollama package."""
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "raytone-thor-ollama"
TARBALL_SHA256 = "96f50a1192133028cf4e010d8c333f8af14b1505db6be7b2034c11487e7fd7e6"  # GitHub release digest


def pkgbuild(expr):
    return subprocess.run(["bash", "-c", f"source {PKG}/PKGBUILD; {expr}"],
                          capture_output=True, text=True, check=True).stdout


class OllamaPackageTests(unittest.TestCase):
    def test_the_official_release_is_pinned(self):
        self.assertEqual(pkgbuild("echo $pkgver").strip(), "0.34.4")
        sources = pkgbuild('printf "%s\\n" "${source[@]}"').split()
        sums = pkgbuild('printf "%s\\n" "${sha256sums[@]}"').split()
        by_url = dict(zip(sources, sums))
        url = [s for s in sources if "ollama-linux-arm64.tar.zst" in s]
        self.assertEqual(len(url), 1)
        self.assertIn("github.com/ollama/ollama/releases/download/v$pkgver/".replace("$pkgver", "0.34.4"), url[0])
        self.assertEqual(by_url[url[0]], TARBALL_SHA256)

    def test_only_the_cuda_13_backend_is_kept(self):
        # ollama#13033: on the Thor it picks cuda_v12, which has no code for sm_110
        text = (PKG / "PKGBUILD").read_text()
        self.assertIn('rm -rf "$pkgdir/usr/lib/ollama/cuda_v12"', text)
        self.assertIn('test -d "$pkgdir/usr/lib/ollama/cuda_v13"', text)

    def test_service_runs_as_its_own_user_and_is_killed_first_under_memory_pressure(self):
        unit = (PKG / "ollama.service").read_text()
        for line in ("ExecStart=/usr/bin/ollama serve", "User=ollama", "Group=ollama",
                     "Environment=HOME=/var/lib/ollama", "OOMScoreAdjust=500",
                     "Environment=CUDA_CACHE_MAXSIZE=4294967296"):
            with self.subTest(line=line):
                self.assertIn(line, unit.splitlines())
        sysusers = (PKG / "ollama.sysusers").read_text()
        self.assertIn("u ollama - \"Ollama\" /var/lib/ollama", sysusers)

    def test_not_enabled_by_the_package(self):
        # as Arch's ollama package: the user enables it (systemctl enable --now ollama)
        self.assertNotIn(".wants", (PKG / "PKGBUILD").read_text())

    def test_depends_on_the_cuda_driver(self):
        self.assertIn("raytone-thor-core", pkgbuild('printf "%s\\n" "${depends[@]}"').split())
        self.assertIn("ollama", pkgbuild('printf "%s\\n" "${provides[@]}"'))


if __name__ == "__main__":
    unittest.main()
