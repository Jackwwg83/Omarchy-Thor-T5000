#!/usr/bin/env python3
"""Pin the L4T packages the port repackages, from NVIDIA's apt indexes.

    l4t_manifest.py OUT.json --release r39.2 --wanted packages.tsv \\
        BASE_URL=PACKAGES_FILE [BASE_URL=PACKAGES_FILE ...]

packages.tsv holds "name<TAB>version" lines (as recorded from the JetPack host).
Each package must appear exactly once at that version across the given indexes.
Packages that update boot firmware, repartition or run first-boot provisioning are
refused here, before anything is downloaded; prohibited_path() applies the same
policy to single files inside otherwise allowed packages.
"""
import argparse
import json
import re
import sys

PROHIBITED_PACKAGES = frozenset({
    "nvidia-l4t-bootloader",
    "nvidia-l4t-bootloader-utils",
    "nvidia-l4t-kernel-partitions",
    "nvidia-l4t-firstboot",
    "nvidia-l4t-oobe",
})

# Boot-chain, OTA, capsule, partition, fuse-writing and first-boot items, wherever they appear.
PROHIBITED_PATH = re.compile(
    r"(nvbootctrl|nv_update_engine|nv_update_verifier|nv_part_update|nv_bootloader_capsule|"
    r"nv-l4t-bootloader-config|nv-rootfs-validation|nv_create_usbkey|gen_luks|l4t_payload|"
    r"/nvfb[-_][^/]*$|nv-oobe|/fwupd/|\.Cap$|/UpdateCapsule/)"
)


class ManifestError(Exception):
    pass


def parse_packages(text):
    """Parse a Debian Packages index into a list of field dicts (continuation lines folded)."""
    stanzas, current, last = [], {}, None
    for line in text.splitlines():
        if not line.strip():
            if current:
                stanzas.append(current)
            current, last = {}, None
        elif line[0] in " \t":
            if last:
                current[last] += "\n" + line.strip()
        else:
            key, _, value = line.partition(":")
            current[key] = value.strip()
            last = key
    if current:
        stanzas.append(current)
    return stanzas


def prohibited_path(path):
    return bool(PROHIBITED_PATH.search(path))


def select(stanzas, name, version, base):
    if name in PROHIBITED_PACKAGES:
        raise ManifestError(f"{name} is prohibited: it updates boot firmware or provisions a first boot")
    hits = [s for s in stanzas if s.get("Package") == name and s.get("Version") == version]
    if not hits:
        raise ManifestError(f"{name} {version} not in index {base}")
    if len(hits) > 1:
        raise ManifestError(f"{name} {version} appears {len(hits)} times in index {base}")
    s = hits[0]
    return {
        "name": name,
        "version": version,
        "url": f"{base.rstrip('/')}/{s['Filename']}",
        "sha256": s["SHA256"],
        "size": int(s["Size"]),
    }


def build(indexes, wanted, release):
    """indexes: [(base_url, path)], wanted: {name: version}. Every package must resolve exactly once."""
    if not wanted:
        raise ManifestError("no packages requested")
    parsed = [(base, parse_packages(open(path, encoding="utf-8").read())) for base, path in indexes]
    packages = []
    for name in sorted(wanted):
        found = []
        for base, stanzas in parsed:
            try:
                found.append(select(stanzas, name, wanted[name], base))
            except ManifestError as e:
                if "prohibited" in str(e) or "appears" in str(e):
                    raise
        if len(found) != 1:
            raise ManifestError(f"{name} {wanted[name]} resolved {len(found)} times across the indexes")
        packages.append(found[0])
    return {"release": release, "packages": packages}


def read_wanted(path):
    wanted = {}
    for line in open(path, encoding="utf-8"):
        if line.strip():
            name, version = line.rstrip("\n").split("\t")[:2]
            wanted[name] = version
    return wanted


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--release", required=True)
    ap.add_argument("--wanted", required=True)
    ap.add_argument("indexes", nargs="+", help="BASE_URL=PACKAGES_FILE")
    args = ap.parse_args(argv)
    indexes = [tuple(i.split("=", 1)) for i in args.indexes]
    try:
        manifest = build(indexes, read_wanted(args.wanted), args.release)
    except ManifestError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print(f"{len(manifest['packages'])} packages pinned to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
