#!/usr/bin/env python3
"""Lay unpacked L4T .deb trees out as an Arch package root.

    l4t_repack.py --out PKGDIR --pkgname NAME [--exclude REGEX ...] [--report FILE] STAGE...

Each STAGE is one unpacked data.tar. Paths move to Arch's merged-/usr layout (/lib, /bin, /sbin and
/usr/sbin under /usr), systemd units and udev rules move from /etc to /usr/lib, Debian's enablement
symlinks (*.wants) and metadata are dropped, and copyright files become license files. Anything the
port prohibits (boot-loader, OTA, capsule, partition and first-boot items; see l4t_manifest.py) is
dropped and reported. Two stages writing the same target path is an error. The report lists every
kept and dropped path, for the package-content tests and the evidence.
"""
import argparse
import importlib.util
import json
import os
import pathlib
import re
import shutil
import sys

_spec = importlib.util.spec_from_file_location("l4t_manifest", pathlib.Path(__file__).with_name("l4t_manifest.py"))
_manifest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_manifest)
prohibited_path = _manifest.prohibited_path

UNIT_RE = re.compile(r"^/etc/systemd/system/[^/]+\.(service|timer|path|socket|target|mount)$")


class RepackError(Exception):
    pass


def _drop_reason(path, exclude):
    if prohibited_path(path):
        return "prohibited"
    if re.match(r"^/etc/systemd/system/[^/]+\.(wants|requires)/", path):
        return "debian enablement link"
    if path.startswith("/usr/share/lintian/") or (path.startswith("/usr/share/doc/") and not path.endswith("/copyright")):
        return "debian metadata"
    for rx in exclude:
        if re.search(rx, path):
            return f"excluded by {rx}"
    return None


def map_path(path, pkgname="", exclude=()):
    """Target path in the Arch package for a path in a deb, or None when it is dropped."""
    if _drop_reason(path, exclude):
        return None
    m = re.match(r"^/usr/share/doc/([^/]+)/copyright$", path)
    if m:
        return f"/usr/share/licenses/{pkgname}/{m.group(1)}.copyright"
    if UNIT_RE.match(path):
        return "/usr/lib/systemd/system/" + path.rsplit("/", 1)[1]
    if path.startswith("/etc/udev/rules.d/"):
        return "/usr/lib/udev/rules.d/" + path[len("/etc/udev/rules.d/"):]
    for old, new in (("/usr/sbin/", "/usr/bin/"), ("/sbin/", "/usr/bin/"), ("/bin/", "/usr/bin/"), ("/lib/", "/usr/lib/")):
        if path.startswith(old):
            return new + path[len(old):]
    return path


def _retarget(target):
    """Absolute symlink targets follow the same move; relative ones stay as they are."""
    if not target.startswith("/"):
        return target
    return map_path(target) or target


def repack(stages, out, pkgname, exclude=()):
    out = pathlib.Path(out)
    kept, dropped, origin = [], {}, {}
    for stage in map(pathlib.Path, stages):
        for dirpath, dirnames, filenames in os.walk(stage):
            names = filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]
            for name in sorted(names):
                src = pathlib.Path(dirpath) / name
                rel = "/" + str(src.relative_to(stage))
                reason = _drop_reason(rel, exclude)
                if reason:
                    dropped[rel] = reason
                    continue
                target = map_path(rel, pkgname=pkgname, exclude=exclude)
                if target in origin:
                    raise RepackError(f"{target} comes from both {origin[target]} and {stage}{rel}")
                origin[target] = f"{stage}{rel}"
                dest = out / target.lstrip("/")
                dest.parent.mkdir(parents=True, exist_ok=True)
                if src.is_symlink():
                    os.symlink(_retarget(os.readlink(src)), dest)
                else:
                    shutil.copy2(src, dest)
                kept.append(target)
    return {"pkgname": pkgname, "kept": sorted(kept), "dropped": dict(sorted(dropped.items()))}


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pkgname", required=True)
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--report")
    ap.add_argument("stages", nargs="+")
    args = ap.parse_args(argv)
    try:
        report = repack(args.stages, args.out, args.pkgname, args.exclude)
    except RepackError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1)
    print(f"{args.pkgname}: {len(report['kept'])} paths kept, {len(report['dropped'])} dropped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
