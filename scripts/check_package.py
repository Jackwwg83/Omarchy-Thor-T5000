#!/usr/bin/env python3
"""Static content checks for a built raytone-thor package.

    check_package.py PACKAGE.pkg.tar.xz ...

Fails on files under directories that are symlinks on Arch (/lib, /bin, /sbin, /usr/sbin), on
anything the port prohibits (see l4t_manifest.py), on generic libraries in the loader directory the
port adds, and on loader configuration that puts NVIDIA's whole library directory on the path.
"""
import importlib.util
import pathlib
import re
import sys
import tarfile

_spec = importlib.util.spec_from_file_location("l4t_manifest", pathlib.Path(__file__).with_name("l4t_manifest.py"))
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)

MERGED = ("lib/", "bin/", "sbin/", "usr/sbin/")
GENERIC_LIB = re.compile(r"^lib(vulkan|gbm|EGL|GLX|GL|GLESv[12]|GLdispatch|OpenGL|wayland-[a-z]+|drm|v4l2|v4lconvert|gnat|gnarl)\.so")
LOADER_DIR = "usr/lib/raytone-l4t/"


def problems(paths, contents=None):
    contents = contents or {}
    out = []
    for p in paths:
        if p.startswith("."):
            continue
        if p.startswith(MERGED):
            out.append(f"{p}: under a directory that is a symlink on Arch")
        if _m.prohibited_path("/" + p):
            out.append(f"{p}: prohibited")
        if p.startswith(LOADER_DIR) and GENERIC_LIB.match(p[len(LOADER_DIR):]):
            out.append(f"{p}: generic library would shadow Arch's")
        if p.startswith("etc/ld.so.conf.d/") and "/usr/lib/aarch64-linux-gnu/nvidia" in contents.get(p, ""):
            out.append(f"{p}: puts NVIDIA's whole library directory on the loader path")
    return out


def check(pkgfile):
    with tarfile.open(pkgfile) as t:
        members = [m for m in t.getmembers() if not m.isdir()]
        paths = [m.name for m in members]
        contents = {m.name: t.extractfile(m).read().decode(errors="replace")
                    for m in members if m.name.startswith("etc/ld.so.conf.d/") and m.isfile()}
    return paths, problems(paths, contents)


if __name__ == "__main__":
    rc = 0
    for f in sys.argv[1:]:
        paths, found = check(f)
        print(f"{pathlib.Path(f).name}: {len(paths)} entries, {len(found)} problems")
        for p in found:
            print(f"  PROBLEM {p}")
        rc |= bool(found)
    sys.exit(rc)
