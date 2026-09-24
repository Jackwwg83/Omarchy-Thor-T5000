#!/usr/bin/env python3
"""Print the PKGBUILD source block for L4T debs pinned in the manifest.

    pkgbuild_sources.py manifests/l4t-r39.2.1.json nvidia-l4t-core nvidia-l4t-init ...

Emits _l4t_debs, source, sha256sums and noextract arrays, in the order given, to paste between the
"# BEGIN l4t sources" and "# END l4t sources" markers of a recipe. Regenerate after the manifest changes.
"""
import json
import sys


def render(manifest, names):
    by_name = {p["name"]: p for p in manifest["packages"]}
    pkgs = [by_name[n] for n in names]  # KeyError for a package not in the manifest
    lines = [f"# L4T {manifest['release']} debs, from manifests/ (scripts/pkgbuild_sources.py)",
             f"_l4t_debs=({' '.join(names)})",
             "source=(" + "\n        ".join(f'"{p["name"]}.deb::{p["url"]}"' for p in pkgs) + ")",
             "sha256sums=(" + "\n            ".join(f"'{p['sha256']}'" for p in pkgs) + ")",
             "noextract=(" + " ".join(f"{n}.deb" for n in names) + ")"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__.strip())
    sys.stdout.write(render(json.load(open(sys.argv[1])), sys.argv[2:]))
