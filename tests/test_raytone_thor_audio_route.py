"""raytone-thor-audio-route: the Thor's headphone jack (RT5640 codec on I2S4) plays only once the APE
routes ADMAIF1 to I2S4 and the codec's DAC-to-headphone path is switched on; NVIDIA leaves both to
the user (amixer). Verified by ear on the Thor, 2026-09-26."""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "raytone-thor-core"
SCRIPT = PKG / "raytone-thor-audio-route"
UNIT = PKG / "raytone-thor-audio-route.service"


class AudioRouteTests(unittest.TestCase):
    def run_script(self, fail=False):
        with tempfile.TemporaryDirectory() as t:
            stub = pathlib.Path(t) / "amixer"
            stub.write_text('#!/bin/bash\necho "$*" >> "$CALLS"\n' + ('exit 1\n' if fail else ''))
            stub.chmod(0o755)
            calls = pathlib.Path(t) / "calls"
            r = subprocess.run(["bash", str(SCRIPT)], env=dict(os.environ, PATH=f"{t}:{os.environ['PATH']}",
                               CALLS=str(calls)), capture_output=True, text=True)
            return r, (calls.read_text().splitlines() if calls.exists() else [])

    def test_routes_admaif1_to_the_codecs_i2s(self):
        r, calls = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("-c APE -q sset I2S4 Mux ADMAIF1", calls)

    def test_switches_on_the_codecs_headphone_path(self):
        _, calls = self.run_script()
        for ctl in ("CVB-RT DAC MIXL INF1 on", "CVB-RT DAC MIXR INF1 on", "CVB-RT Stereo DAC MIXL DAC L1 on",
                    "CVB-RT Stereo DAC MIXR DAC R1 on", "CVB-RT HPO MIX DAC1 on", "CVB-RT HP L on",
                    "CVB-RT HP R on", "CVB-RT HP Channel on"):
            with self.subTest(ctl=ctl):
                self.assertIn(f"-c APE -q sset {ctl}", calls)

    def test_a_missing_card_fails_loudly(self):
        r, _ = self.run_script(fail=True)
        self.assertNotEqual(r.returncode, 0)

    def test_runs_when_sound_is_up_and_after_alsa_restore(self):
        unit = UNIT.read_text()
        self.assertIn("ExecStart=/usr/lib/raytone/raytone-thor-audio-route", unit)
        self.assertIn("WantedBy=sound.target", unit)
        self.assertIn("After=sound.target alsa-restore.service", unit)
        text = (PKG / "PKGBUILD").read_text()
        self.assertIn("usr/lib/systemd/system/sound.target.wants/raytone-thor-audio-route.service", text)


if __name__ == "__main__":
    unittest.main()
