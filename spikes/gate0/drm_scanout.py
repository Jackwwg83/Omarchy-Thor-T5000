#!/usr/bin/env python3
"""Judge scanout from two drm_info text dumps of one DRM node (Gate 0b spike).

    drm_scanout.py SAMPLE1 SAMPLE2 [--require-flip]

Follows the connected HDMI connector to its CRTC and that CRTC's primary plane.
Passes when, in both samples, the CRTC is active, the primary plane shows a
framebuffer at 2560x1440, and (with --require-flip) the framebuffer ID differs
between the samples, i.e. the kernel is flipping new frames to the connector.
"""
import re
import sys

WANT = (2560, 1440)


def blocks(text, kind):
    """Split a drm_info section ("Connector", "CRTC", "Plane") into per-object text."""
    parts = re.split(rf"^[│ ]+[├└]───{kind} \d+\n", text, flags=re.M)
    return parts[1:]


def prop(block, name):
    m = re.search(rf'"{re.escape(name)}"[^\n]*= (-?\d+|\w+)\s*$', block, re.M)
    return m.group(1) if m else None


def object_id(block):
    m = re.search(r"Object ID: (\d+)", block)
    return int(m.group(1)) if m else None


def scanout(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    conns = [b for b in blocks(text, "Connector") if "Type: HDMI-A" in b and "Status: connected" in b]
    if not conns:
        return {"error": "no connected HDMI connector"}
    crtc_id = int(prop(conns[0], "CRTC_ID") or 0)
    info = {"crtc": crtc_id}
    if not crtc_id:
        info["error"] = "HDMI connector has no CRTC"
        return info
    for c in blocks(text, "CRTC"):
        if object_id(c) == crtc_id:
            info["active"] = int(prop(c, "ACTIVE") or 0)
    for p in blocks(text, "Plane"):
        if prop(p, "type") == "Primary" and int(prop(p, "CRTC_ID") or 0) == crtc_id:
            info.update(fb=int(prop(p, "FB_ID") or 0), w=int(prop(p, "CRTC_W") or 0), h=int(prop(p, "CRTC_H") or 0))
    return info


def main(argv):
    if len(argv) < 3:
        print(__doc__.strip())
        return 2
    s1, s2 = scanout(argv[1]), scanout(argv[2])
    print(f"sample 1: {s1}")
    print(f"sample 2: {s2}")
    problems = []
    for n, s in (("1", s1), ("2", s2)):
        if "error" in s:
            problems.append(f"sample {n}: {s['error']}")
            continue
        if s.get("active") != 1:
            problems.append(f"sample {n}: CRTC {s['crtc']} not active")
        if not s.get("fb"):
            problems.append(f"sample {n}: no framebuffer on the primary plane")
        if (s.get("w"), s.get("h")) != WANT:
            problems.append(f"sample {n}: primary plane is {s.get('w')}x{s.get('h')}, want {WANT[0]}x{WANT[1]}")
    flipped = s1.get("fb") and s2.get("fb") and s1["fb"] != s2["fb"]
    if "--require-flip" in argv and not flipped:
        problems.append("framebuffer did not change between samples")
    print(f"flipping between samples: {'yes' if flipped else 'no'}")
    for p in problems:
        print(f"PROBLEM {p}")
    print("SCANOUT PASS" if not problems else "SCANOUT FAIL")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
