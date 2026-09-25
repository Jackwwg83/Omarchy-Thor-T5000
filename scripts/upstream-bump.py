#!/usr/bin/env python3
"""Follow an upstream Omarchy release: docs/UPSTREAM-SYNC.md.

    upstream-bump.py [--pkgs-commit SHA] [--write]

Reads omarchy-pkgs (its main branch unless --pkgs-commit), whose omarchy and omarchy-settings
recipes name the Omarchy release they build (_tag, _commit). Refuses pre-releases and recipes that
disagree. Then:

  GATE    every upstream file the Thor layer overrides (overrides/UPSTREAM.sha256) or mirrors
          (WATCHED.sha256), hashed at the new commit; each change needs a review of the Thor file.
  REVIEW  upstream changes since the pinned commit that can affect the port: migrations, the
          install tree, the base package list, pacman/update/channel scripts, the menu, SDDM.

--write copies the recipes verbatim into packages/ and updates manifests/upstream-lock.json.
Exit 0: nothing to review in the gate. 2: the gate changed (the pinned-upstream tests fail until
the overrides are reviewed and the .sha256 files updated). 1: refused.
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import urllib.request

RECIPES = ("pkgbuilds/omarchy/PKGBUILD", "pkgbuilds/omarchy-settings/PKGBUILD",
           "pkgbuilds/omarchy-settings/omarchy-settings.install")
LAYER = pathlib.Path("packages/raytone-thor-omarchy")
GATE_FILES = (LAYER / "overrides" / "UPSTREAM.sha256", LAYER / "WATCHED.sha256")
REVIEW = re.compile(r"^(migrations/|install/|default/pacman/|default/omarchy/omarchy-menu\.jsonc$|"
                    r"default/sddm/|etc/sddm|bin/omarchy-(update|refresh-pacman|channel|pkg-|migrate|hook))")


class GitHub:
    """The network side, replaced by a fake in tests."""

    def _get(self, url, accept="application/vnd.github+json"):
        req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "omarchy-thor-bump"})
        if os.environ.get("GITHUB_TOKEN"):
            req.add_header("Authorization", "Bearer " + os.environ["GITHUB_TOKEN"])
        return urllib.request.urlopen(req, timeout=30).read()

    def head(self, repo):
        return json.loads(self._get(f"https://api.github.com/repos/{repo}/commits/HEAD"))["sha"]

    def raw(self, repo, ref, path):
        return self._get(f"https://raw.githubusercontent.com/{repo}/{ref}/{path}", accept="*/*")

    def compare(self, repo, old, new):
        return json.loads(self._get(f"https://api.github.com/repos/{repo}/compare/{old}...{new}")).get("files", [])


def field(recipe, name):
    m = re.search(rf"^{name}='([^']*)'", recipe.decode(), re.M)
    return m.group(1) if m else ""


def main(argv=None, upstream=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pkgs-commit")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    args = ap.parse_args(argv)
    up = upstream or GitHub()
    root = pathlib.Path(args.root)
    lock_path = root / "manifests" / "upstream-lock.json"
    lock = json.loads(lock_path.read_text())

    pkgs_commit = args.pkgs_commit or up.head("omacom/omarchy-pkgs")
    recipes = {p: up.raw("omacom/omarchy-pkgs", pkgs_commit, p) for p in RECIPES}
    tag, commit = field(recipes[RECIPES[0]], "_tag"), field(recipes[RECIPES[0]], "_commit")
    if (field(recipes[RECIPES[1]], "_tag"), field(recipes[RECIPES[1]], "_commit")) != (tag, commit):
        print("refused: the omarchy and omarchy-settings recipes name different releases")
        return 1
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        print(f"refused: '{tag}' at '{commit}' is not a stable release (pre-release or bare commit)")
        return 1
    old_tag, old = lock["omarchy"]["tag"], lock["omarchy"]["commit"]
    hashes = {p: hashlib.sha256(d).hexdigest() for p, d in recipes.items()}
    recipes_changed = [p for p in RECIPES if lock["omarchy-pkgs"].get("recipes", {}).get(p) != hashes[p]]

    # The gate runs every time: after --write the lock names the new release, and it stays open
    # until each Thor file is reviewed and its .sha256 line updated.
    changed = []
    for gate in GATE_FILES:
        for line in (root / gate).read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            digest, rel = line.split()
            if hashlib.sha256(up.raw("omacom/omarchy", commit, rel)).hexdigest() != digest:
                changed.append((rel, gate))

    if commit == old and not recipes_changed and not changed:
        print(f"up to date: Omarchy {tag} ({commit})")
        return 0
    if commit != old:
        print(f"Omarchy {old_tag} -> {tag} ({old[:12]} -> {commit[:12]}), omarchy-pkgs {pkgs_commit[:12]}")
    else:
        print(f"Omarchy {tag} ({commit[:12]}), omarchy-pkgs {pkgs_commit[:12]}")
    if recipes_changed:
        print("\nRECIPES changed: " + ", ".join(recipes_changed))

    print("\nGATE: " + (f"{len(changed)} upstream file(s) changed; review the Thor file for each, then "
                        "update its .sha256 line" if changed else "no overridden or mirrored file changed"))
    for rel, gate in changed:
        print(f"  {rel}  ({gate.name}) https://github.com/omacom/omarchy/blob/{commit}/{rel}")

    review = [] if commit == old else [f for f in up.compare("omacom/omarchy", old, commit)
                                       if REVIEW.match(f["filename"])]
    print(f"\nREVIEW: {len(review)} change(s) that can affect the port")
    for f in review:
        print(f"  {f['status']:<9} {f['filename']}")

    if args.write:
        for p, data in recipes.items():
            (root / "packages" / p.removeprefix("pkgbuilds/")).write_bytes(data)
        lock["omarchy"].update(tag=tag, commit=commit)
        lock["omarchy-pkgs"]["commit"] = pkgs_commit
        lock["omarchy-pkgs"]["recipes"] = hashes
        lock_path.write_text(json.dumps(lock, indent=2) + "\n")
        print(f"\nwrote: packages/omarchy*, {lock_path.relative_to(root)}; next: docs/UPSTREAM-SYNC.md step 3")
    return 2 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
