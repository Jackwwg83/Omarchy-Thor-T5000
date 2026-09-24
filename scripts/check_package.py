#!/usr/bin/env python3
"""Static content checks for a built raytone-thor package.

    check_package.py PACKAGE.pkg.tar.xz ...

Fails on files under directories that are symlinks on Arch (/lib, /bin, /sbin, /usr/sbin), on
anything the port prohibits (see l4t_manifest.py), on generic libraries in the loader directory the
port adds, on loader configuration that puts NVIDIA's whole library directory on the path, and on
glvnd, EGL platform or Vulkan ICD registrations whose library the package does not ship.
"""
import importlib.util
import json
import pathlib
import posixpath
import re
import sys
import tarfile

_spec = importlib.util.spec_from_file_location("l4t_manifest", pathlib.Path(__file__).with_name("l4t_manifest.py"))
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)

MERGED = ("lib/", "bin/", "sbin/", "usr/sbin/")
GENERIC_LIB = re.compile(r"^lib(vulkan|gbm|EGL|GLX|GL|GLESv[12]|GLdispatch|OpenGL|wayland-[a-z]+|drm|v4l2|v4lconvert|gnat|gnarl)\.so")
LOADER_DIR = "usr/lib/raytone-l4t/"
REGISTRATION_DIRS = ("usr/share/glvnd/egl_vendor.d/", "etc/glvnd/egl_vendor.d/",
                     "usr/share/egl/egl_external_platform.d/", "etc/vulkan/icd.d/", "usr/share/vulkan/icd.d/")


def resolve(path, links):
    """Follow symlinks between package members; None for a loop."""
    for _ in range(40):
        if path not in links:
            return path
        target = links[path]
        path = posixpath.normpath(target.lstrip("/") if target.startswith("/")
                                  else posixpath.join(posixpath.dirname(path), target))
    return None


def _registration(path, text, files, links):
    try:
        lib = json.loads(text)["ICD"]["library_path"]
    except (TypeError, ValueError, KeyError):
        return [f"{path}: not a readable ICD registration"]
    # A bare soname is found through the loader path, which only this package's loader directory adds to.
    member = lib.lstrip("/") if lib.startswith("/") else LOADER_DIR + lib
    if resolve(member, links) not in files:
        return [f"{path}: library {lib} is not in the package"]
    return []


def problems(paths, contents=None, links=None):
    contents = contents or {}
    links = links or {}
    files = set(paths) - set(links)
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
        if p.startswith(REGISTRATION_DIRS) and p.endswith(".json"):
            out.extend(_registration(p, contents.get(p), files, links))
    return out


def check(pkgfile):
    with tarfile.open(pkgfile) as t:
        members = [m for m in t.getmembers() if not m.isdir()]
        paths = [m.name for m in members]
        links = {m.name: m.linkname for m in members if m.issym()}
        byname = {m.name: m for m in members if m.isfile()}
        contents = {}
        for p in paths:
            if p.startswith(("etc/ld.so.conf.d/",) + REGISTRATION_DIRS):
                m = byname.get(resolve(p, links))
                if m is not None:
                    contents[p] = t.extractfile(m).read().decode(errors="replace")
    return paths, problems(paths, contents, links)


if __name__ == "__main__":
    rc = 0
    for f in sys.argv[1:]:
        paths, found = check(f)
        print(f"{pathlib.Path(f).name}: {len(paths)} entries, {len(found)} problems")
        for p in found:
            print(f"  PROBLEM {p}")
        rc |= bool(found)
    sys.exit(rc)
