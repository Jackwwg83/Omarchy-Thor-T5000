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


def run_override(rel, env_extra, stubs):
    """Run one override the way upstream's run_logged does (bash -eE) with stubbed commands."""
    t = pathlib.Path(env_extra["TMP"])
    (t / "bin").mkdir(exist_ok=True)
    for name, body in stubs.items():
        (t / "bin" / name).write_text("#!/bin/bash\n" + f"echo {name} \"$@\" >> {t}/calls\n" + body)
        (t / "bin" / name).chmod(0o755)
    env = dict(os.environ, PATH=f"{t}/bin:{os.environ['PATH']}", **env_extra)
    return subprocess.run(["bash", "-eE", str(OVERRIDES / rel)], env=env, capture_output=True, text=True)


class ThorSnapperTests(unittest.TestCase):
    def test_skips_on_a_non_btrfs_root(self):
        with tempfile.TemporaryDirectory() as t:
            r = run_override("install/config/snapper.sh", {"TMP": t},
                             {"findmnt": "echo ext4\n", "snapper": "", "systemctl": ""})
            self.assertEqual(r.returncode, 0, r.stderr)
            calls = pathlib.Path(t, "calls").read_text()
            self.assertNotIn("snapper ", calls)
            self.assertNotIn("systemctl", calls)


class ThorPacmanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.tmp.name)
        self.etc = t / "etc"
        (self.etc / "pacman.d").mkdir(parents=True)
        (self.etc / "pacman.conf").write_text("[multilib]\n")
        self.install = t / "install"
        (self.install / "hardware").mkdir(parents=True)
        (self.install / "hardware" / "pacman.sh").write_text("echo sourced-hardware-pacman >> $TMP/calls\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_pacman(self):
        return run_override("install/post-install/pacman.sh",
                            {"TMP": self.tmp.name, "RAYTONE_ETC": str(self.etc), "OMARCHY_INSTALL": str(self.install),
                             "OMARCHY_PATH": self.tmp.name, "RAYTONE_PACMAN_TEMPLATES": str(PKG / "pacman")}, {})

    def test_writes_the_thor_aarch64_config(self):
        r = self.run_pacman()
        self.assertEqual(r.returncode, 0, r.stderr)
        conf = (self.etc / "pacman.conf").read_text()
        self.assertEqual(conf, (PKG / "pacman" / "pacman.conf").read_text())
        self.assertEqual((self.etc / "pacman.d" / "mirrorlist").read_text(), (PKG / "pacman" / "mirrorlist").read_text())
        self.assertIn("sourced-hardware-pacman", pathlib.Path(self.tmp.name, "calls").read_text())

    def test_template_repo_order_and_signatures(self):
        conf = (PKG / "pacman" / "pacman.conf").read_text()
        repos = [l.strip()[1:-1] for l in conf.splitlines() if l.strip().startswith("[") and l.strip() != "[options]"]
        self.assertEqual(repos, ["raytone-thor", "core", "extra", "alarm", "aur", "omarchy"])
        self.assertNotIn("multilib", conf)
        self.assertNotIn("TrustAll", conf)
        self.assertNotIn("SigLevel = Never", conf)
        self.assertIn("Architecture = aarch64", conf)
        self.assertIn("https://pkgs.omarchy.org/edge/$arch", conf)


class ThorFirewallTests(unittest.TestCase):
    """Omarchy's rules plus SSH and mDNS, written while UFW stays disabled; enabled only at the very end."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.tmp.name)
        self.conf = t / "ufw.conf"
        self.conf.write_text("# /etc/ufw/ufw.conf\nENABLED=yes\nLOGLEVEL=low\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_fw(self, ufw_body=""):
        # every stub records its call and the ENABLED line at that moment
        record = f'echo "$(basename $0) $* | $(grep ^ENABLED= {self.conf})" >> {self.tmp.name}/calls\n'
        return run_override("install/config/firewall.sh", {"TMP": self.tmp.name, "RAYTONE_UFW_CONF": str(self.conf)},
                            {"ufw": record + ufw_body, "systemctl": record, "ufw-docker": record})

    def calls(self):
        """Only the lines that record UFW's ENABLED state at the time of each call."""
        return [c for c in pathlib.Path(self.tmp.name, "calls").read_text().splitlines() if " | " in c]

    def test_rules_are_written_while_disabled_then_enabled_last(self):
        r = self.run_fw()
        self.assertEqual(r.returncode, 0, r.stderr)
        ufw = [c for c in self.calls() if c.startswith("ufw ")]
        self.assertTrue(ufw)
        for c in ufw:
            self.assertTrue(c.endswith("ENABLED=no"), c)
        joined = "\n".join(ufw)
        for rule in ("allow 22/tcp", "allow 5353/udp", "allow 53317/udp", "allow 53317/tcp", "default deny incoming"):
            self.assertIn(rule, joined)
        self.assertIn("ENABLED=yes", self.conf.read_text())
        self.assertTrue(any(c.startswith("systemctl enable ufw") for c in self.calls()))

    def test_never_touches_the_running_firewall(self):
        self.run_fw()
        for c in self.calls():
            self.assertNotRegex(c, r"^ufw (enable|reload|--force enable)")
            self.assertNotRegex(c, r"^systemctl (start|restart|reload)")

    def test_a_failed_rule_leaves_ufw_disabled(self):
        r = self.run_fw(ufw_body='[[ "$*" == *22/tcp* ]] && exit 1\nexit 0\n')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ENABLED=no", self.conf.read_text())
        self.assertFalse(any(c.startswith("systemctl enable ufw") for c in self.calls()))


if __name__ == "__main__":
    unittest.main()
