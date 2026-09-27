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

    def test_cdi_spec_waits_for_the_nvidia_display_stack(self):
        # At boot the spec was generated at 21:15:21, before nv-load-display-modules (done 21:15:27)
        # had loaded the stack: it named a transient /dev/dri/card0 and missed /dev/nvidia0 and
        # nvidia-uvm, and docker failed "failed to stat CDI host device /dev/dri/card0".
        unit = (PKG / "raytone-thor-cdi.service").read_text()
        self.assertIn("After=local-fs.target nv-load-display-modules.service", unit.splitlines())
        text = (PKG / "PKGBUILD").read_text()
        self.assertIn("usr/lib/systemd/system/multi-user.target.wants/raytone-thor-cdi.service", text)


class FanTests(unittest.TestCase):
    """Seen on the Thor (2026-09-28): a 768p video held the SoC at 85-89 C with the fan at about
    2800 of 5371 rpm (JetPack's "cool" profile), then peaked at 96 C and the thermal guard (95 C)
    rebooted it. Our own fan configuration reaches full speed earlier. nvfancontrol drives the fan
    from the 25/25/25/25 average of four zones as a margin to 115 C, while the guard reads the
    hottest zone, so full speed comes at an average of 83 C."""

    CONF = PKG / "nvfancontrol-raytone-thor.conf"

    def profile(self, name):
        text = self.CONF.read_text()
        m = re.search(r"FAN_PROFILE %s \{(.*?)\}" % name, text, re.S)
        self.assertIsNotNone(m, name)
        return [tuple(int(x) for x in l.split()) for l in m.group(1).splitlines() if l.strip() and not l.strip().startswith("#")]

    def test_the_raytone_profile_is_the_default(self):
        self.assertRegex(self.CONF.read_text(), r"(?m)^\s*FAN_DEFAULT_PROFILE raytone$")
        self.assertRegex(self.CONF.read_text(), r"(?m)^\s*TMARGIN ENABLED$")

    def test_full_speed_from_an_average_of_83_c(self):
        rows = self.profile("raytone")
        margins = [r[0] for r in rows]
        self.assertEqual(margins, sorted(margins))
        self.assertEqual(rows[0][0], 0)
        self.assertEqual(rows[-1][0], 115)
        for margin, hyst, pwm, rpm in rows:
            self.assertTrue(0 <= pwm <= 255 and hyst == 0)
            if margin <= 32:
                self.assertEqual((pwm, rpm), (255, 5371), margin)
        # never slower than JetPack's "cool" curve (margin, pwm) at any of its points
        for margin, pwm in ((0, 255), (15, 255), (24, 192), (29, 140), (35, 102), (45, 77), (115, 77)):
            mine = max((r for r in rows if r[0] <= margin), key=lambda r: r[0])[2]
            self.assertGreaterEqual(mine, pwm, margin)

    def test_the_package_points_nvfancontrol_at_it(self):
        pkgbuild = (PKG / "PKGBUILD").read_text()
        self.assertIn("nvfancontrol-raytone-thor.conf", pkgbuild)
        install = (PKG / "raytone-thor-omarchy.install").read_text()
        self.assertIn("/etc/nvpower/nvfancontrol/nvfancontrol_p3834_0008_p4071_0000.conf", install)
        self.assertIn("/var/lib/nvfancontrol/status", install)

    def test_relinks_only_jetpacks_own_link(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t)
            etc = t / "etc"
            (etc / "nvpower/nvfancontrol").mkdir(parents=True)
            vendor, ours = etc / "nvpower/nvfancontrol/nvfancontrol_p3834_0008_p4071_0000.conf", etc / "nvpower/nvfancontrol/raytone-thor.conf"
            vendor.write_text("v")
            ours.write_text("o")
            link = etc / "nvfancontrol.conf"
            script = f"""source {PKG}/raytone-thor-omarchy.install
_fan_link {vendor} {ours} {link} /bin/true /nonexistent"""
            for start, expected in ((vendor, ours), (etc / "mine.conf", etc / "mine.conf")):
                link.unlink(missing_ok=True)
                os.symlink(start, link)
                subprocess.run(["bash", "-c", script], check=True)
                self.assertEqual(pathlib.Path(os.readlink(link)), expected)


class UsernsTests(unittest.TestCase):
    def test_unprivileged_user_namespaces_are_allowed(self):
        # The L4T kernel restricts them through AppArmor (an Ubuntu default) and Arch ships no
        # AppArmor profiles, so every one was refused: Codex's bwrap sandbox could not start.
        conf = (PKG / "sysctl-60-raytone-thor-userns.conf").read_text()
        self.assertIn("kernel.apparmor_restrict_unprivileged_userns = 0", conf.splitlines())
        self.assertIn("usr/lib/sysctl.d/60-raytone-thor-userns.conf", (PKG / "PKGBUILD").read_text())
