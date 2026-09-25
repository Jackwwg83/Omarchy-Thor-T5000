"""upstream-bump.py against a fake upstream: recipes, lock file, the hash gate, the review list."""
import hashlib
import importlib.util
import io
import json
import pathlib
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("upstream_bump", ROOT / "scripts" / "upstream-bump.py")
bump = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bump)

OLD = "c668141e9c42b13c80c9ca4ea108e11708c5e8a5"
NEW = "1111111111111111111111111111111111111111"
PKGS_NEW = "2222222222222222222222222222222222222222"


def recipe(tag, commit, name="omarchy"):
    return (f"pkgname='{name}'\n_tag='{tag}'\n_commit='{commit}'\npkgver={tag.lstrip('v')}\npkgrel=1\n").encode()


def sha(b):
    return hashlib.sha256(b).hexdigest()


class FakeUpstream:
    def __init__(self, tag="v4.0.5", commit=NEW, settings_commit=None, changed=(), files=(), pkgrel=1):
        self.tag, self.commit, self.pkgrel = tag, commit, pkgrel
        self.settings_commit = settings_commit or commit
        self.changed = set(changed)  # gated upstream paths whose content differs at the new commit
        self.files = list(files)     # compare API entries
        self.fetched = []

    def head(self, repo):
        assert repo == "omacom/omarchy-pkgs"
        return PKGS_NEW

    def raw(self, repo, ref, path):
        self.fetched.append((repo, ref, path))
        if repo == "omacom/omarchy-pkgs":
            assert ref == PKGS_NEW
            if path == "pkgbuilds/omarchy/PKGBUILD":
                return recipe(self.tag, self.commit).replace(b"pkgrel=1", f"pkgrel={self.pkgrel}".encode())
            if path == "pkgbuilds/omarchy-settings/PKGBUILD":
                return recipe(self.tag, self.settings_commit, "omarchy-settings")
            if path == "pkgbuilds/omarchy-settings/omarchy-settings.install":
                return b"post_install() { :; }\n"
        if repo == "omacom/omarchy":
            assert ref == self.commit
            return (b"changed " + path.encode()) if path in self.changed else ORIGINAL[path]
        raise AssertionError((repo, ref, path))

    def compare(self, repo, old, new):
        assert (repo, old, new) == ("omacom/omarchy", OLD, self.commit)
        return self.files


# the gated files' "old" contents: their hashes are written into the temp tree's .sha256 files
ORIGINAL = {p: f"original {p}".encode() for p in (
    "install/config/firewall.sh", "install/config/snapper.sh", "install/hardware/nvidia.sh",
    "install/post-install/pacman.sh", "etc/sddm.conf.d/10-wayland.conf")}


class UpstreamBumpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        for rel in ("manifests/upstream-lock.json", "packages/omarchy/PKGBUILD",
                    "packages/omarchy-settings/PKGBUILD", "packages/omarchy-settings/omarchy-settings.install"):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / rel, self.root / rel)
        layer = self.root / "packages" / "raytone-thor-omarchy"
        (layer / "overrides").mkdir(parents=True)
        (layer / "overrides" / "UPSTREAM.sha256").write_text("".join(
            f"{sha(ORIGINAL[p])}  {p}\n" for p in sorted(ORIGINAL) if p.startswith("install/")))
        (layer / "WATCHED.sha256").write_text(
            "# mirrored\n" + f"{sha(ORIGINAL['etc/sddm.conf.d/10-wayland.conf'])}  etc/sddm.conf.d/10-wayland.conf\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_bump(self, up, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = bump.main(["--root", str(self.root), *args], upstream=up)
        return code, out.getvalue()

    def lock(self):
        return json.loads((self.root / "manifests" / "upstream-lock.json").read_text())

    def test_report_only_changes_nothing(self):
        before = (self.root / "packages" / "omarchy" / "PKGBUILD").read_bytes()
        code, out = self.run_bump(FakeUpstream())
        self.assertEqual(code, 0, out)
        self.assertIn("v4.0.4 -> v4.0.5", out)
        self.assertEqual((self.root / "packages" / "omarchy" / "PKGBUILD").read_bytes(), before)
        self.assertEqual(self.lock()["omarchy"]["commit"], OLD)

    def test_write_updates_recipes_and_lock(self):
        code, out = self.run_bump(FakeUpstream(), "--write")
        self.assertEqual(code, 0, out)
        self.assertEqual((self.root / "packages" / "omarchy" / "PKGBUILD").read_bytes(), recipe("v4.0.5", NEW))
        lock = self.lock()
        self.assertEqual((lock["omarchy"]["tag"], lock["omarchy"]["commit"]), ("v4.0.5", NEW))
        self.assertEqual(lock["omarchy-pkgs"]["commit"], PKGS_NEW)
        self.assertEqual(lock["omarchy-pkgs"]["recipes"]["pkgbuilds/omarchy/PKGBUILD"], sha(recipe("v4.0.5", NEW)))

    def pin_to(self, up):
        # the lock as a previous --write for this fake upstream would have left it
        lock = self.lock()
        lock["omarchy"].update(tag=up.tag, commit=up.commit)
        lock["omarchy-pkgs"]["recipes"] = {p: sha(up.raw("omacom/omarchy-pkgs", PKGS_NEW, p)) for p in bump.RECIPES}
        (self.root / "manifests" / "upstream-lock.json").write_text(json.dumps(lock))

    def test_up_to_date(self):
        up = FakeUpstream(tag="v4.0.4", commit=OLD)
        self.pin_to(up)
        code, out = self.run_bump(up, "--write")
        self.assertEqual(code, 0)
        self.assertIn("up to date", out)

    def test_a_recipe_change_for_the_same_release_is_followed(self):
        # upstream repackages (pkgrel) without a new Omarchy commit
        self.pin_to(FakeUpstream(tag="v4.0.4", commit=OLD))
        up = FakeUpstream(tag="v4.0.4", commit=OLD, pkgrel=2)
        code, out = self.run_bump(up, "--write")
        self.assertEqual(code, 0, out)
        self.assertNotIn("up to date", out)
        self.assertIn("pkgbuilds/omarchy/PKGBUILD", out)
        self.assertIn(b"pkgrel=2", (self.root / "packages" / "omarchy" / "PKGBUILD").read_bytes())

    def test_the_gate_holds_until_it_is_reviewed(self):
        # after --write the lock names the new release; a rerun must still report the open gate
        up = FakeUpstream(changed={"install/hardware/nvidia.sh"})
        self.assertEqual(self.run_bump(up, "--write")[0], 2)
        code, out = self.run_bump(up)
        self.assertEqual(code, 2, out)
        self.assertIn("install/hardware/nvidia.sh", out)

    def test_gate_names_every_changed_upstream_file(self):
        up = FakeUpstream(changed={"install/hardware/nvidia.sh", "etc/sddm.conf.d/10-wayland.conf"})
        code, out = self.run_bump(up, "--write")
        self.assertEqual(code, 2, out)
        self.assertIn("install/hardware/nvidia.sh", out)
        self.assertIn("etc/sddm.conf.d/10-wayland.conf", out)
        self.assertNotIn("install/config/snapper.sh", out.split("GATE")[1])
        # recipes are written so the build follows upstream; the tests stay red until the review
        self.assertEqual(self.lock()["omarchy"]["commit"], NEW)

    def test_refuses_a_pre_release(self):
        code, out = self.run_bump(FakeUpstream(tag="v4.1.0rc1"), "--write")
        self.assertEqual(code, 1)
        self.assertIn("pre-release", out)
        self.assertEqual(self.lock()["omarchy"]["commit"], OLD)

    def test_refuses_recipes_that_disagree(self):
        code, out = self.run_bump(FakeUpstream(settings_commit="3" * 40), "--write")
        self.assertEqual(code, 1)
        self.assertIn("omarchy-settings", out)
        self.assertEqual(self.lock()["omarchy"]["commit"], OLD)

    def test_review_list(self):
        files = [{"filename": "migrations/1790000000.sh", "status": "added"},
                 {"filename": "install/hardware/new-thing.sh", "status": "added"},
                 {"filename": "install/omarchy-base.packages", "status": "modified"},
                 {"filename": "bin/omarchy-refresh-pacman", "status": "modified"},
                 {"filename": "default/omarchy/omarchy-menu.jsonc", "status": "modified"},
                 {"filename": "themes/tokyo/colors.toml", "status": "modified"}]
        code, out = self.run_bump(FakeUpstream(files=files))
        self.assertEqual(code, 0, out)
        review = out.split("REVIEW")[1]
        for f in ("migrations/1790000000.sh", "install/hardware/new-thing.sh", "install/omarchy-base.packages",
                  "bin/omarchy-refresh-pacman", "default/omarchy/omarchy-menu.jsonc"):
            self.assertIn(f, review)
        self.assertNotIn("themes/tokyo", review)


if __name__ == "__main__":
    unittest.main()
