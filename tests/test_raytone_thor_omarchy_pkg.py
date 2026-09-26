"""raytone-thor-omarchy package contents: session and greeter use the Thor's display node; watched upstream files."""
import hashlib
import json
import pathlib
import re
import subprocess
import unittest
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "raytone-thor-omarchy"
DISPLAY = "/dev/dri/by-path/platform-8808c00000.display-card"


class PackageTests(unittest.TestCase):
    def pkgbuild_sources(self):
        out = subprocess.run(["bash", "-c", f"source {PKG}/PKGBUILD; printf '%s\\n' \"${{_files[@]}}\""],
                             capture_output=True, text=True, check=True).stdout.split()
        return out

    def test_every_packaged_file_exists(self):
        for src in self.pkgbuild_sources():
            with self.subTest(src=src):
                self.assertTrue((PKG / src).exists(), src)

    def test_display_node_has_no_colon(self):
        # AQ_DRM_DEVICES separates devices with ':'
        self.assertNotIn(":", DISPLAY)

    def test_session_uses_the_display_node(self):
        env = (PKG / "uwsm-env.d-20-raytone-thor").read_text()
        self.assertIn(f"export AQ_DRM_DEVICES={DISPLAY}", env)

    def test_greeter_uses_the_display_node_and_upstream_command(self):
        conf = (PKG / "sddm-20-raytone-thor.conf").read_text()
        m = re.search(r"^CompositorCommand=env AQ_DRM_DEVICES=(\S+) (.+)$", conf, re.M)
        self.assertIsNotNone(m, conf)
        self.assertEqual(m.group(1), DISPLAY)
        self.assertEqual(m.group(2), "start-hyprland -- --config /usr/share/sddm/hyprland.lua")

    def test_watched_upstream_files_match_the_pin(self):
        """Files the Thor layer mirrors (not overrides) are watched too (needs network)."""
        commit = json.loads((ROOT / "manifests" / "upstream-lock.json").read_text())["omarchy"]["commit"]
        for line in (PKG / "WATCHED.sha256").read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            digest, rel = line.split()
            url = f"https://raw.githubusercontent.com/omacom/omarchy/{commit}/{rel}"
            try:
                data = urllib.request.urlopen(url, timeout=20).read()
            except OSError as e:
                self.skipTest(f"cannot fetch {url}: {e}")
            with self.subTest(rel=rel):
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()


class ContainerGpuTests(unittest.TestCase):
    """Slice 3.3: Docker containers get the GPU through CDI, generated in CSV mode (the Thor is an
    integrated GPU) at every boot into /run/cdi, where Docker reads it; ALARM's toolkit hook is for
    desktop nvidia-utils (it reads /usr/lib/libcuda.so) and does not apply."""

    def test_the_toolkit_is_a_dependency(self):
        depends = subprocess.run(["bash", "-c", f"source {PKG}/PKGBUILD; printf '%s\\n' \"${{depends[@]}}\""],
                                 capture_output=True, text=True, check=True).stdout.split()
        self.assertIn("nvidia-container-toolkit", depends)

    def test_cdi_spec_is_generated_at_boot_in_csv_mode(self):
        unit = (PKG / "raytone-thor-cdi.service").read_text()
        self.assertIn("ExecStart=/usr/bin/nvidia-ctk cdi generate --mode=csv --output=/run/cdi/nvidia.yaml",
                      unit.splitlines())
        self.assertIn("Before=docker.service containerd.service", unit)
        text = (PKG / "PKGBUILD").read_text()
        self.assertIn("usr/lib/systemd/system/multi-user.target.wants/raytone-thor-cdi.service", text)
