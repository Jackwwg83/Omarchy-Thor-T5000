"""raytone-thor-nft-modules: nf_tables expressions NVIDIA's kernel lacks, built for exactly that kernel."""
import json
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "raytone-thor-nft-modules"


def pkgbuild(expr, pkg=PKG):
    return subprocess.run(["bash", "-c", f"source {pkg}/PKGBUILD; {expr}"],
                          capture_output=True, text=True, check=True).stdout.split()


class NftModulesPackageTests(unittest.TestCase):
    def test_builds_nft_limit_which_ufw_needs(self):
        # iptables-nft turns ufw's `-m limit` into the nf_tables limit expression; without nft_limit
        # every rule after the first limit line fails and UFW drops all inbound traffic.
        self.assertIn("nft_limit", pkgbuild('printf "%s\\n" "${_modules[@]}"'))

    def test_targets_the_kernel_raytone_thor_linux_ships(self):
        kver = pkgbuild('echo $_kver')
        self.assertEqual(kver, pkgbuild('echo $_kver', ROOT / "packages" / "raytone-thor-linux"))
        self.assertIn("raytone-thor-linux", " ".join(pkgbuild('printf "%s\\n" "${depends[@]}"')))

    def test_headers_are_the_pinned_l4t_deb(self):
        l4t = json.loads((ROOT / "manifests" / "l4t-r39.2.1.json").read_text())
        pins = {}

        def walk(o):
            if isinstance(o, dict):
                if o.get("name") == "nvidia-l4t-kernel-headers":
                    pins[o["url"]] = o["sha256"]
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(l4t)
        sources = pkgbuild('printf "%s\\n" "${source[@]}"')
        sums = pkgbuild('printf "%s\\n" "${sha256sums[@]}"')
        self.assertEqual(len(sources), len(sums))
        by_url = {s.split("::")[-1]: h for s, h in zip(sources, sums)}
        self.assertEqual(len(pins), 1)
        for url, digest in pins.items():
            self.assertEqual(by_url.get(url), digest)

    def test_every_source_is_pinned(self):
        self.assertNotIn("SKIP", pkgbuild('printf "%s\\n" "${sha256sums[@]}"'))

    def test_modules_go_where_depmod_prefers_them(self):
        text = (PKG / "PKGBUILD").read_text()
        self.assertIn("/usr/lib/modules/$_kver/updates/", text)

    def test_the_thor_omarchy_layer_depends_on_it(self):
        depends = pkgbuild('printf "%s\\n" "${depends[@]}"', ROOT / "packages" / "raytone-thor-omarchy")
        self.assertIn("raytone-thor-nft-modules", depends)


if __name__ == "__main__":
    unittest.main()
