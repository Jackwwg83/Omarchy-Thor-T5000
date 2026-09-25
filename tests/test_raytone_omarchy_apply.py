"""raytone-omarchy-apply-system: runs upstream omarchy-apply-system with the Thor overrides, behind a hash gate."""
import hashlib
import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "raytone-thor-omarchy"
SCRIPT = PKG / "raytone-omarchy-apply-system"
OVERRIDES = PKG / "overrides"

# Stands in for upstream omarchy-apply-system: records its arguments and the install tree it was given.
APPLY_STUB = textwrap.dedent("""\
    #!/bin/bash
    echo "$*" > "$STATE/apply-args"
    echo "$OMARCHY_INSTALL" > "$STATE/apply-install-dir"
    cp -a "$OMARCHY_INSTALL" "$STATE/seen-install"
    """)


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


class ApplySystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.tmp.name)
        self.state, self.bin, self.omarchy = t / "state", t / "bin", t / "omarchy"
        for d in (self.state, self.bin):
            d.mkdir()
        # A fake upstream tree whose overridden files have exactly the recorded upstream hashes is not
        # possible to fabricate, so the gate list is rewritten to this fake tree's hashes; the real
        # recorded hashes are checked against upstream in test_recorded_hashes_are_the_pinned_upstream_files.
        self.overrides = t / "overrides"
        subprocess.run(["cp", "-a", str(OVERRIDES), str(self.overrides)], check=True)
        lines = []
        for rel in self.override_paths():
            f = self.omarchy / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f"# upstream {rel}\n")
            lines.append(f"{sha(f)}  {rel}")
        (self.overrides / "UPSTREAM.sha256").write_text("\n".join(lines) + "\n")
        (self.omarchy / "install" / "helpers").mkdir(parents=True, exist_ok=True)
        (self.omarchy / "install" / "helpers" / "logging.sh").write_text("# upstream helper\n")
        (self.bin / "omarchy-apply-system").write_text(APPLY_STUB)
        (self.bin / "omarchy-apply-system").chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def override_paths(self):
        return sorted(str(p.relative_to(OVERRIDES)) for p in (OVERRIDES / "install").rglob("*") if p.is_file())

    def run_script(self, *args):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", STATE=str(self.state),
                   OMARCHY_PATH=str(self.omarchy), RAYTONE_OMARCHY_OVERRIDES=str(self.overrides))
        return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True)

    def test_runs_upstream_with_the_merged_tree_and_the_same_arguments(self):
        r = self.run_script("--install-user", "nvidia", "--first-install")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.state / "apply-args").read_text().strip(), "--install-user nvidia --first-install")
        seen = self.state / "seen-install"
        for rel in self.override_paths():
            with self.subTest(rel=rel):
                self.assertEqual((seen / rel[len("install/"):]).read_text(), (OVERRIDES / rel).read_text())
        self.assertEqual((seen / "helpers" / "logging.sh").read_text(), "# upstream helper\n")

    def test_refuses_when_an_overridden_upstream_file_changed(self):
        rel = self.override_paths()[0]
        (self.omarchy / rel).write_text("# upstream changed in a new release\n")
        r = self.run_script("--install-user", "nvidia", "--first-install")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(rel, r.stderr)
        self.assertFalse((self.state / "apply-args").exists())

    def test_refuses_an_override_without_a_recorded_upstream_hash(self):
        extra = self.overrides / "install" / "config" / "unreviewed.sh"
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("true\n")
        r = self.run_script("--install-user", "nvidia", "--first-install")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unreviewed.sh", r.stderr)
        self.assertFalse((self.state / "apply-args").exists())

    def test_leaves_the_packaged_upstream_tree_untouched(self):
        before = {p: p.read_bytes() for p in self.omarchy.rglob("*") if p.is_file()}
        self.run_script("--install-user", "nvidia", "--first-install")
        after = {p: p.read_bytes() for p in self.omarchy.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_recorded_hashes_cover_every_override(self):
        recorded = [line.split()[1] for line in (OVERRIDES / "UPSTREAM.sha256").read_text().splitlines() if line.strip()]
        self.assertEqual(sorted(recorded), self.override_paths())


class PinnedUpstreamTests(unittest.TestCase):
    def test_recorded_hashes_are_the_pinned_upstream_files(self):
        """The gate must describe the Omarchy release in manifests/upstream-lock.json (needs network)."""
        import json
        import urllib.request
        lock = json.loads((ROOT / "manifests" / "upstream-lock.json").read_text())
        commit = lock["omarchy"]["commit"]
        for line in (OVERRIDES / "UPSTREAM.sha256").read_text().splitlines():
            if not line.strip():
                continue
            digest, rel = line.split()
            url = f"https://raw.githubusercontent.com/omacom/omarchy/{commit}/{rel}"
            try:
                data = urllib.request.urlopen(url, timeout=20).read()
            except OSError as e:
                self.skipTest(f"cannot fetch {url}: {e}")
            with self.subTest(rel=rel):
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)


class ThorNvidiaTests(unittest.TestCase):
    def test_installs_no_driver_packages(self):
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t)
            (t / "bin").mkdir()
            for tool in ("omarchy-pkg-add", "pacman", "lspci"):
                (t / "bin" / tool).write_text(f"#!/bin/bash\necho {tool} \"$@\" >> {t}/calls\n"
                                              + ("echo 'NVIDIA Corporation GB10B [Jetson AGX Thor]'\n" if tool == "lspci" else ""))
                (t / "bin" / tool).chmod(0o755)
            r = subprocess.run(["bash", "-eE", str(OVERRIDES / "install" / "hardware" / "nvidia.sh")],
                               env=dict(os.environ, PATH=f"{t}/bin:{os.environ['PATH']}"), capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            calls = (t / "calls").read_text() if (t / "calls").exists() else ""
            self.assertNotIn("omarchy-pkg-add", calls)
            self.assertNotIn("pacman", calls)


if __name__ == "__main__":
    unittest.main()
