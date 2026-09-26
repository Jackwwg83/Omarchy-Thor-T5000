#!/usr/bin/env python3
"""Omarchy on the Thor's NVMe next to JetPack (Slice 4): the pure, tested parts.

    thor_nvme.py check  --dump FILE                        original | split, or refuse
    thor_nvme.py split  --dump FILE --app-gib N --uuid U [--app-used-bytes B]   new sfdisk dump
    thor_nvme.py app-blocks --dump FILE                    APP's size in 4 KiB blocks (resize2fs)
    thor_nvme.py extlinux --in FILE --root-partuuid U --kernel PATH --initrd PATH   new extlinux.conf
    thor_nvme.py fstab --in FILE --root-partuuid U                              new fstab

The NVMe holds NVIDIA's layout: ten small partitions at the start (recovery, ESP, reserved) and
JetPack's APP (ext4) from 2.67 GiB to the end, recorded in manifests/thor-nvme-gpt-2026-09-26.sfdisk.
APP is shrunk from its end, keeping its start, PARTUUID (JetPack's kernel command line names it),
type and name, and a new partition RAYTONE_OMARCHY takes the rest. Nothing else in the table moves.

JetPack's L4TLauncher reads APP's /boot/extlinux/extlinux.conf (recorded as
manifests/jetpack-extlinux-2026-09-26.conf) and offers its entries for TIMEOUT tenths of a second;
an omarchy entry is added first and made the default, with an initramfs (NVIDIA's kernel has the
PCIe controller and NVMe as modules, as JetPack's own initrd shows), its command line derived from
JetPack's primary entry (root swapped, read-only, rootwait bounded, panic=10), and JetPack's entry is
left byte for byte. GPT attributes are kept and compared; unknown sfdisk fields are refused. No ESP, UEFI variable or firmware is involved.
"""
import argparse
import dataclasses
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
RECORDED_GPT = ROOT / "manifests" / "thor-nvme-gpt-2026-09-26.sfdisk"
RECORDED_EXTLINUX = ROOT / "manifests" / "jetpack-extlinux-2026-09-26.conf"
LINUX_FS = "0FC63DAF-8483-4772-8E79-3D69D8477DE4"
ROOT_NAME = "RAYTONE_OMARCHY"
ALIGN = 2048  # sectors: 1 MiB


class LayoutError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class Part:
    number: int
    start: int
    size: int
    type: str
    uuid: str
    name: str
    attrs: str = ""


@dataclasses.dataclass
class Table:
    header: dict
    device: str
    parts: list

    @property
    def last_lba(self):
        return int(self.header["last-lba"])

    def part(self, n):
        for p in self.parts:
            if p.number == n:
                return p
        raise LayoutError(f"no partition {n}")


LINE_RE = re.compile(r'^(?P<dev>\S+?)p?(?P<n>\d+)\s*:\s*(?P<fields>.*)$')


def parse_dump(text):
    header, parts, device = {}, [], None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line and "=" not in line.split(":", 1)[0] and not line.startswith("/dev/"):
            k, v = line.split(":", 1)
            header[k.strip()] = v.strip()
            continue
        m = LINE_RE.match(line)
        if not m:
            raise LayoutError(f"unreadable sfdisk line: {line}")
        fields = [x.strip() for x in re.findall(r'(?:[^,"]|"[^"]*")+', m.group("fields"))]
        f = {}
        for field in fields:
            k, eq, v = field.partition("=")
            if not eq or k not in ("start", "size", "type", "uuid", "name", "attrs"):
                raise LayoutError(f"sfdisk field {field!r} is not one the port knows: {line}")
            f[k] = v.strip()
        try:
            parts.append(Part(int(m.group("n")), int(f["start"]), int(f["size"]), f["type"],
                              f["uuid"], f.get("name", '""').strip('"'), f.get("attrs", '""').strip('"')))
        except KeyError as e:
            raise LayoutError(f"sfdisk line without {e}: {line}") from None
        device = m.group("dev")
    device = device or header.get("device", "")
    return Table(header, header.get("device", device), parts)


def render_dump(t):
    out = [f"{k}: {v}" for k, v in t.header.items()] + [""]
    for p in sorted(t.parts, key=lambda p: p.number):
        attrs = f', attrs="{p.attrs}"' if p.attrs else ""
        out.append(f'{t.device}p{p.number} : start={p.start:>12}, size={p.size:>12}, type={p.type}, '
                   f'uuid={p.uuid}, name="{p.name}"{attrs}')
    return "\n".join(out) + "\n"


def _recorded():
    return parse_dump(RECORDED_GPT.read_text())


def check_layout(t, recorded=None):
    """'original' (as recorded) or 'split' (APP shrunk, RAYTONE_OMARCHY after it); else LayoutError."""
    rec = recorded or _recorded()
    for k in ("label", "label-id", "first-lba", "last-lba", "sector-size"):
        if t.header.get(k) != rec.header.get(k):
            raise LayoutError(f"disk header {k} is {t.header.get(k)!r}, recorded {rec.header.get(k)!r}")
    for n in range(2, 12):
        if t.part(n) != rec.part(n):
            raise LayoutError(f"partition {n} differs from the recorded layout")
    app, rapp = t.part(1), rec.part(1)
    if (app.start, app.type, app.uuid, app.name, app.attrs) != (rapp.start, rapp.type, rapp.uuid, rapp.name, rapp.attrs):
        raise LayoutError("APP's start, type, PARTUUID, name or attributes differ from the recorded layout")
    numbers = sorted(p.number for p in t.parts)
    if numbers == list(range(1, 12)) and app.size == rapp.size:
        return "original"
    if numbers == list(range(1, 13)):
        root = t.part(12)
        if (root.start == app.start + app.size and root.start + root.size - 1 == t.last_lba
                and root.name == ROOT_NAME and root.type == LINUX_FS and not root.attrs):
            return "split"
    raise LayoutError("the table is neither the recorded layout nor the recorded layout split for Omarchy")


def split(t, app_gib, new_uuid, app_used_bytes=0):
    if check_layout(t) != "original":
        raise LayoutError("only the recorded, unsplit layout can be split")
    app = t.part(1)
    target = app.start + app_gib * (1 << 30) // 512
    root_start = -(-target // ALIGN) * ALIGN
    app_size = root_start - app.start
    if app_size % 8:
        raise LayoutError("APP would not end on a 4 KiB block")
    if app_size * 512 < app_used_bytes * 1.2:
        raise LayoutError(f"APP at {app_gib} GiB leaves under 20% headroom over its {app_used_bytes} used bytes")
    if root_start >= t.last_lba:
        raise LayoutError("no room left for the Omarchy partition")
    parts = [dataclasses.replace(app, size=app_size) if p.number == 1 else p for p in t.parts]
    parts.append(Part(12, root_start, t.last_lba - root_start + 1, LINUX_FS, new_uuid, ROOT_NAME))
    return Table(dict(t.header), t.device, parts)


def app_blocks(app):
    return app.size * 512 // 4096


# extlinux.conf
def entry(text, label):
    """The lines of one LABEL block, up to the next LABEL or a comment/blank run, as text."""
    lines, out, on = text.splitlines(keepends=True), [], False
    for line in lines:
        if line.startswith("LABEL "):
            on = line.split()[1] == label
        elif on and not line.startswith((" ", "\t")):
            on = False
        if on:
            out.append(line)
    if not out:
        raise LayoutError(f"no LABEL {label}")
    return "".join(out)


def _primary_append(text):
    e = entry(text, "primary")
    for line in e.splitlines():
        if line.strip().startswith("APPEND "):
            return line.strip().split()[1:]
    raise LayoutError("JetPack's primary entry has no APPEND")


def omarchy_args(primary_args, root_partuuid):
    if not primary_args or primary_args[0] != "${cbootargs}":
        raise LayoutError("JetPack's primary APPEND does not start with ${cbootargs}")
    keep = [a for a in primary_args[1:]
            if not a.startswith(("root=", "panic=", "rootwait")) and a not in ("rw", "ro")]
    return (["${cbootargs}", f"root=PARTUUID={root_partuuid}", "ro", "rootwait=20"] + keep
            + ["panic=10", "systemd.gpt_auto=0"])


def add_omarchy_entry(text, root_partuuid, kernel, initrd):
    if text != RECORDED_EXTLINUX.read_text():
        raise LayoutError("extlinux.conf is not the one recorded (manifests/jetpack-extlinux-2026-09-26.conf)")
    path = r"/boot/[A-Za-z0-9._/-]+"
    if not re.fullmatch(r"[0-9a-f-]{36}", root_partuuid) or not re.fullmatch(path, kernel) or not re.fullmatch(path, initrd):
        raise LayoutError("bad PARTUUID, kernel or initrd path")
    args = " ".join(omarchy_args(_primary_append(text), root_partuuid))
    block = ("LABEL omarchy\n"
             "      MENU LABEL RaytoneOS Omarchy (NVMe)\n"
             f"      LINUX {kernel}\n"
             f"      INITRD {initrd}\n"
             f"      APPEND {args}\n\n")
    if "\nDEFAULT primary\n" not in "\n" + text:
        raise LayoutError("no DEFAULT primary line")
    new = ("\n" + text).replace("\nDEFAULT primary\n", "\nDEFAULT omarchy\n", 1)[1:]
    return new.replace("LABEL primary\n", block + "LABEL primary\n", 1)


def retarget_fstab(text, root_partuuid):
    out, n = [], 0
    for line in text.splitlines(keepends=True):
        fields = line.split()
        if len(fields) >= 2 and not line.lstrip().startswith("#") and fields[1] == "/":
            line = line.replace(fields[0], f"PARTUUID={root_partuuid}", 1)
            n += 1
        out.append(line)
    if n != 1:
        raise LayoutError(f"fstab has {n} root lines, expected 1")
    return "".join(out)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("--dump", required=True)
    s = sub.add_parser("split"); s.add_argument("--dump", required=True); s.add_argument("--app-gib", type=int, required=True)
    s.add_argument("--uuid", required=True); s.add_argument("--app-used-bytes", type=int, default=0)
    b = sub.add_parser("app-blocks"); b.add_argument("--dump", required=True)
    e = sub.add_parser("extlinux"); e.add_argument("--in", dest="inp", required=True)
    e.add_argument("--root-partuuid", required=True); e.add_argument("--kernel", required=True)
    e.add_argument("--initrd", required=True)
    f = sub.add_parser("fstab"); f.add_argument("--in", dest="inp", required=True); f.add_argument("--root-partuuid", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "check":
            print(check_layout(parse_dump(pathlib.Path(a.dump).read_text())))
        elif a.cmd == "split":
            print(render_dump(split(parse_dump(pathlib.Path(a.dump).read_text()), a.app_gib, a.uuid, a.app_used_bytes)), end="")
        elif a.cmd == "app-blocks":
            t = parse_dump(pathlib.Path(a.dump).read_text())
            check_layout(t)
            print(app_blocks(t.part(1)))
        elif a.cmd == "extlinux":
            print(add_omarchy_entry(pathlib.Path(a.inp).read_text(), a.root_partuuid, a.kernel, a.initrd), end="")
        elif a.cmd == "fstab":
            print(retarget_fstab(pathlib.Path(a.inp).read_text(), a.root_partuuid), end="")
    except LayoutError as err:
        print(f"thor_nvme: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
