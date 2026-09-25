"""raytone-thor-menu-extension: hides Omarchy menu entries that cannot work on the Thor, through the
user's menu extension file (the only one Omarchy's shell reads besides its defaults)."""
import json
import os
import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CMD = ROOT / "packages" / "raytone-thor-omarchy" / "raytone-thor-menu-extension"

# Omarchy's skel file (omarchy-settings 4.0.4), shortened: comment lines only
SKEL = """{
  // Extend the Quickshell Omarchy menu with JSONC.
  //
  // "personal": {"icon":"","label":"Personal"},
}
"""


def parse(text):
    # MenuModel.stripJsonc in Omarchy's shell: whole-line comments, then trailing commas
    text = re.sub(r"^\s*//[^\n]*(\n|$)", "", text, flags=re.M)
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", text))


class MenuExtensionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.tmp.name)
        self.file = self.home / ".config" / "omarchy" / "extensions" / "omarchy-menu.jsonc"
        self.file.parent.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cmd(self):
        r = subprocess.run(["bash", str(CMD)], env=dict(os.environ, HOME=str(self.home)), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return parse(self.file.read_text())

    def test_hides_what_cannot_work_on_the_thor(self):
        self.file.write_text(SKEL)
        menu = self.run_cmd()
        for id_ in ("system.suspend", "install.gaming.steam", "install.terminal.ghostty", "install.ai.ollama",
                    "setup.direct-boot", "update.firmware", "style.unlock", "update.config.plymouth"):
            with self.subTest(id=id_):
                self.assertEqual(menu[id_], {"when": "false"})
        self.assertEqual(len(menu), 24)

    def test_keeps_the_users_own_entries_and_lets_them_win(self):
        self.file.write_text('{\n  "personal": {"label":"Personal"},\n  "system.suspend": {"when":"true"}\n}\n')
        menu = self.run_cmd()
        self.assertEqual(menu["personal"], {"label": "Personal"})
        self.assertEqual(menu["system.suspend"], {"when": "true"})  # later key wins in JSON.parse

    def test_runs_again_without_duplicating(self):
        self.file.write_text(SKEL)
        self.run_cmd()
        once = self.file.read_text()
        self.run_cmd()
        self.assertEqual(self.file.read_text(), once)
        self.assertEqual(once.count("BEGIN raytone-thor"), 1)

    def test_an_unmatched_marker_leaves_the_file_alone(self):
        # a BEGIN without its exact END line would otherwise skip the user's entries to the end
        self.file.write_text(SKEL)
        self.run_cmd()
        broken = self.file.read_text().replace("  // END raytone-thor", "    // END raytone-thor (edited)")
        broken = broken.replace("}\n", '  "personal": {"label":"Personal"},\n}\n')
        self.file.write_text(broken)
        r = subprocess.run(["bash", str(CMD)], env=dict(os.environ, HOME=str(self.home)), capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("marker", r.stderr)
        self.assertEqual(self.file.read_text(), broken)

    def test_creates_the_file_when_missing(self):
        self.assertEqual(len(self.run_cmd()), 24)

    def test_only_whole_line_comments(self):
        # Omarchy's JSONC reader strips // comments only when they fill the line
        self.file.write_text(SKEL)
        self.run_cmd()
        for line in self.file.read_text().splitlines():
            if "//" in line:
                self.assertTrue(line.lstrip().startswith("//"), line)


if __name__ == "__main__":
    unittest.main()
