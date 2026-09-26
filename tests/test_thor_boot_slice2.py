"""The Slice 2.3 boot menu (docs/evidence/slice2/entries-2.json): Omarchy by default, JetPack one
key press away, the Slice 1 test entries gone; ids kept so arm-once and the docs still apply."""
import importlib.util
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("thor_boot", ROOT / "scripts" / "thor_boot.py")
thor_boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(thor_boot)
ENTRIES = ROOT / "docs" / "evidence" / "slice2" / "entries-2.json"
OLD = ROOT / "docs" / "evidence" / "slice1b" / "entries-1b.json"


def load(path):
    return [thor_boot.Entry(**e) for e in json.loads(path.read_text())]


class Slice2MenuTests(unittest.TestCase):
    def cfg(self):
        return thor_boot.grub_cfg(load(ENTRIES), "raytone-arch")

    def test_omarchy_is_the_default_and_first(self):
        cfg = self.cfg()
        self.assertIn('set default="raytone-arch"', cfg)
        entries = [l for l in cfg.splitlines() if l.startswith("menuentry")]
        self.assertTrue(entries[0].startswith('menuentry "RaytoneOS Omarchy (USB drive)" --id raytone-arch'))
        self.assertTrue(entries[1].startswith('menuentry "JetPack on the internal NVMe" --id jetpack-nvme'))

    def test_only_omarchy_and_jetpack_besides_the_reserved_entries(self):
        ids = [e.id for e in load(ENTRIES)]
        self.assertEqual(ids, ["raytone-arch", "jetpack-nvme"])

    def test_boot_targets_are_unchanged_from_slice_1b(self):
        old = {e.id: e for e in load(OLD)}
        for e in load(ENTRIES):
            with self.subTest(id=e.id):
                o = old[e.id]
                self.assertEqual((e.fs_uuid, e.kernel, e.initrd, e.cmdline, e.chainload),
                                 (o.fs_uuid, o.kernel, o.initrd, o.cmdline, o.chainload))

    def test_the_menu_waits_long_enough_to_pick_jetpack(self):
        self.assertIn("set timeout=3", self.cfg())


if __name__ == "__main__":
    unittest.main()
