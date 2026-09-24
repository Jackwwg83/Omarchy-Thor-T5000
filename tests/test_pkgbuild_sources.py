import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pkgbuild_sources", ROOT / "scripts" / "pkgbuild_sources.py")
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)

MANIFEST = {"release": "r39.2", "packages": [
    {"name": "nvidia-l4t-core", "version": "39.2.1-1", "url": "https://r/pool/core.deb", "sha256": "aa", "size": 1},
    {"name": "nvidia-l4t-init", "version": "39.2.1-1", "url": "https://r/pool/init.deb", "sha256": "bb", "size": 2},
]}


class SourcesTests(unittest.TestCase):
    def test_renders_named_sources_in_the_requested_order(self):
        text = ps.render(MANIFEST, ["nvidia-l4t-init", "nvidia-l4t-core"])
        self.assertIn('"nvidia-l4t-init.deb::https://r/pool/init.deb"', text)
        self.assertLess(text.index("init.deb::"), text.index("core.deb::"))
        self.assertLess(text.index("'bb'"), text.index("'aa'"))
        self.assertIn("noextract=(", text)

    def test_unknown_package_is_an_error(self):
        with self.assertRaises(KeyError):
            ps.render(MANIFEST, ["nvidia-l4t-cuda"])

    def test_cli_reads_the_manifest(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(MANIFEST, f)
        self.assertIn("_l4t_debs=(nvidia-l4t-core)", ps.render(json.load(open(f.name)), ["nvidia-l4t-core"]))


if __name__ == "__main__":
    unittest.main()
