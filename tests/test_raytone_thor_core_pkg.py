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
