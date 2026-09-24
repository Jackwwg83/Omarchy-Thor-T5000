"""thor-rootfs/thermal-guard against a fake sysfs and stubbed systemctl/nvpmodel."""
import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "thor-rootfs" / "thermal-guard"

STUB = textwrap.dedent("""\
    #!/bin/sh
    echo "$(basename "$0") $*" >> "$STATE/calls"
    case "$(basename "$0") $*" in
      "systemctl is-active nvfancontrol")
        # the SoC heats up while the guard keeps running
        if [ -f "$STATE/heat-after-first-check" ]; then
          rm "$STATE/heat-after-first-check"; echo 97000 > "$RAYTONE_SYS/class/thermal/thermal_zone1/temp"
        fi
        cat "$STATE/fan-state" ;;
      "nvpmodel -q")
        [ -f "$STATE/nvpmodel-ignores-term" ] && trap '' TERM
        [ -f "$STATE/nvpmodel-hangs" ] && sleep 30
        echo "NV Power Mode: MAXN" ;;
      "systemctl reboot") [ -f "$STATE/reboot-refused" ] && exit 1 ;;
      "systemctl reboot --force") [ -f "$STATE/force-refused" ] && exit 1 ;;
      "systemctl reboot --force --force")
        [ -f "$STATE/immediate-hangs" ] && sleep 20
        [ -f "$STATE/immediate-refused" ] && exit 1 ;;
    esac
    exit 0
    """)


class ThermalGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.tmp.name)
        self.state, self.bin, self.sys, self.log = t / "state", t / "bin", t / "sys", t / "log"
        for d in (self.state, self.bin, self.log, self.sys / "class" / "hwmon" / "hwmon5"):
            d.mkdir(parents=True)
        for tool in ("systemctl", "nvpmodel"):
            (self.bin / tool).write_text(STUB)
            (self.bin / tool).chmod(0o755)
        (self.sys / "class" / "hwmon" / "hwmon5" / "name").write_text("pwm_tach\n")
        (self.sys / "class" / "hwmon" / "hwmon5" / "rpm").write_text("1781\n")
        (self.state / "fan-state").write_text("active\n")
        self.zones(52000, 61000)

    def tearDown(self):
        self.tmp.cleanup()

    def zones(self, *temps):
        for i, t in enumerate(temps):
            z = self.sys / "class" / "thermal" / f"thermal_zone{i}"
            z.mkdir(parents=True, exist_ok=True)
            (z / "temp").write_text(f"{t}\n")

    def run_guard(self, checks=1, timeout=20):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", STATE=str(self.state),
                   RAYTONE_SYS=str(self.sys), RAYTONE_GUARD_LOG=str(self.log / "thermal.log"),
                   RAYTONE_GUARD_GRACE="0", RAYTONE_GUARD_INTERVAL="0", RAYTONE_GUARD_CHECKS=str(checks),
                   RAYTONE_SYSRQ=str(self.state / "sysrq-trigger"), RAYTONE_GUARD_LAST_WAIT="1")
        return subprocess.run(["sh", str(GUARD)], env=env, capture_output=True, text=True, timeout=timeout)

    def calls(self):
        f = self.state / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def test_normal_readings_are_logged_and_nothing_reboots(self):
        r = self.run_guard(checks=3)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("systemctl reboot", self.calls())
        log = (self.log / "thermal.log").read_text()
        self.assertIn("max_mC=61000", log)
        self.assertIn("fan_rpm=1781", log)
        self.assertEqual(self.calls().count("systemctl is-active nvfancontrol"), 3)

    def test_hot_zone_reboots_before_any_diagnostic_query(self):
        self.zones(52000, 95000)
        self.run_guard(checks=1)
        calls = self.calls()
        self.assertIn("systemctl reboot", calls)
        self.assertNotIn("nvpmodel -q", calls[:calls.index("systemctl reboot")])

    def test_later_overheating_is_caught_by_the_same_process(self):
        (self.state / "heat-after-first-check").touch()
        r = self.run_guard(checks=2)
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.calls()
        self.assertEqual(calls.count("systemctl is-active nvfancontrol"), 1)  # hot: no query needed
        self.assertIn("systemctl reboot", calls)

    def test_a_refused_reboot_is_forced(self):
        self.zones(52000, 96000)
        (self.state / "reboot-refused").touch()
        self.run_guard(checks=1)
        calls = self.calls()
        self.assertLess(calls.index("systemctl reboot"), calls.index("systemctl reboot --force"))
        self.assertNotIn("systemctl reboot --force --force", calls)

    def test_a_refused_forced_reboot_reboots_immediately(self):
        self.zones(52000, 96000)
        (self.state / "reboot-refused").touch()
        (self.state / "force-refused").touch()
        self.run_guard(checks=1)
        self.assertIn("systemctl reboot --force --force", self.calls())

    def sysrq(self):
        f = self.state / "sysrq-trigger"
        return f.read_text() if f.exists() else ""

    def test_a_refused_immediate_reboot_falls_back_to_sysrq(self):
        self.zones(52000, 96000)
        for flag in ("reboot-refused", "force-refused", "immediate-refused"):
            (self.state / flag).touch()
        self.run_guard(checks=1)
        self.assertEqual(self.sysrq(), "b\n")

    def test_a_hanging_immediate_reboot_does_not_block_the_guard(self):
        self.zones(52000, 96000)
        for flag in ("reboot-refused", "force-refused", "immediate-hangs"):
            (self.state / flag).touch()
        r = self.run_guard(checks=2, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        # the second check ran although the first immediate reboot never returned
        self.assertEqual(self.calls().count("systemctl reboot --force --force"), 2)
        self.assertEqual(self.sysrq(), "b\n")

    def test_sysrq_is_not_touched_when_a_reboot_request_is_accepted(self):
        self.zones(52000, 96000)
        self.run_guard(checks=1)
        self.assertEqual(self.sysrq(), "")

    def test_the_guard_keeps_watching_after_requesting_a_reboot(self):
        self.zones(52000, 96000)
        r = self.run_guard(checks=3)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls().count("systemctl reboot"), 3)

    def test_fan_control_not_running_reboots(self):
        (self.state / "fan-state").write_text("failed\n")
        self.run_guard(checks=1)
        self.assertIn("systemctl reboot", self.calls())

    def test_no_readable_zone_reboots(self):
        for z in (self.sys / "class" / "thermal").iterdir():
            (z / "temp").unlink()
        self.run_guard(checks=1)
        self.assertIn("systemctl reboot", self.calls())

    def test_a_hanging_diagnostic_does_not_stall_the_guard(self):
        (self.state / "nvpmodel-hangs").touch()
        r = self.run_guard(checks=2, timeout=25)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls().count("systemctl is-active nvfancontrol"), 2)

    def test_a_diagnostic_that_ignores_term_is_killed(self):
        (self.state / "nvpmodel-hangs").touch()
        (self.state / "nvpmodel-ignores-term").touch()
        r = self.run_guard(checks=2, timeout=25)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls().count("systemctl is-active nvfancontrol"), 2)


if __name__ == "__main__":
    unittest.main()
