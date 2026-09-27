"""thor_nvme.py: the pure parts of installing Omarchy onto the Thor's NVMe next to JetPack (Slice 4).
Fixtures: the NVMe's GPT (sfdisk --dump) and JetPack's extlinux.conf as read on 2026-09-26."""
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("thor_nvme", ROOT / "scripts" / "thor_nvme.py")
nv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nv)

DUMP = (ROOT / "manifests" / "thor-nvme-gpt-2026-09-26.sfdisk").read_text()
EXTLINUX = (ROOT / "manifests" / "jetpack-extlinux-2026-09-26.conf").read_text()
APP_UUID = "1B3479B0-B4C2-4A1B-8B81-86D864B3944E"
NEW_UUID = "0E5A0B4C-1D2E-4F30-8A11-5B6C7D8E9F00"
GIB = 1 << 30


class LayoutTests(unittest.TestCase):
    def test_parses_the_recorded_table(self):
        t = nv.parse_dump(DUMP)
        self.assertEqual(t.header["label"], "gpt")
        self.assertEqual(t.last_lba, 4000797326)
        self.assertEqual(len(t.parts), 11)
        app = t.part(1)
        self.assertEqual((app.start, app.size, app.uuid, app.name), (5591104, 3995206223, APP_UUID, "APP"))

    def test_the_recorded_layout_is_accepted(self):
        self.assertEqual(nv.check_layout(nv.parse_dump(DUMP)), "original")

    def test_any_other_layout_is_refused(self):
        variants = {
            "moved APP": DUMP.replace("start=     5591104", "start=     5591112"),
            "other APP uuid": DUMP.replace(APP_UUID, "1B3479B0-B4C2-4A1B-8B81-86D864B3944F"),
            "a changed NVIDIA partition": DUMP.replace('name="UDA"', 'name="UDB"'),
            "a missing partition": "\n".join(l for l in DUMP.splitlines() if "nvme0n1p11" not in l) + "\n",
        }
        for name, text in variants.items():
            with self.subTest(name=name):
                with self.assertRaises(nv.LayoutError):
                    nv.check_layout(nv.parse_dump(text))


class AttributeTests(unittest.TestCase):
    # From Codex's Slice 4 review: GPT attributes were parsed away, so a changed APP still read
    # as the recorded layout and the split dropped them.
    def test_attributes_are_part_of_the_layout(self):
        text = DUMP.replace('name="APP"', 'name="APP", attrs="RequiredPartition"')
        with self.assertRaises(nv.LayoutError):
            nv.check_layout(nv.parse_dump(text))

    def test_attributes_survive_a_render(self):
        text = DUMP.replace('name="UDA"', 'name="UDA", attrs="GUID:63"')
        self.assertIn('attrs="GUID:63"', nv.render_dump(nv.parse_dump(text)))

    def test_unknown_fields_are_refused(self):
        with self.assertRaises(nv.LayoutError):
            nv.parse_dump(DUMP.replace('name="UDA"', 'name="UDA", bootable'))


class SplitTests(unittest.TestCase):
    def split(self):
        return nv.split(nv.parse_dump(DUMP), app_gib=950, new_uuid=NEW_UUID)

    def test_app_keeps_its_start_uuid_type_and_name(self):
        new = self.split()
        old = nv.parse_dump(DUMP).part(1)
        app = new.part(1)
        self.assertEqual((app.start, app.uuid, app.type, app.name), (old.start, old.uuid, old.type, old.name))

    def test_app_is_about_950_gib_and_whole_4k_blocks(self):
        app = self.split().part(1)
        self.assertGreaterEqual(app.size * 512, 950 * GIB)
        self.assertLess(app.size * 512, 950 * GIB + (1 << 20))
        self.assertEqual(app.size % 8, 0)  # ext4 blocks of 4 KiB: resize2fs to exactly the partition

    def test_the_new_root_fills_the_rest_aligned(self):
        t = self.split()
        app, root = t.part(1), t.part(12)
        self.assertEqual(root.start, app.start + app.size)
        self.assertEqual(root.start % 2048, 0)
        self.assertEqual(root.start + root.size - 1, t.last_lba)
        self.assertEqual((root.uuid, root.name), (NEW_UUID, "RAYTONE_OMARCHY"))
        self.assertEqual(root.type, "0FC63DAF-8483-4772-8E79-3D69D8477DE4")  # Linux filesystem
        self.assertGreater(root.size * 512, 950 * GIB)

    def test_every_other_partition_and_the_header_are_unchanged(self):
        old, new = nv.parse_dump(DUMP), self.split()
        self.assertEqual(old.header, new.header)
        for n in range(2, 12):
            self.assertEqual(old.part(n), new.part(n))

    def test_the_split_table_is_recognised_as_split(self):
        t = nv.parse_dump(nv.render_dump(self.split()))
        self.assertEqual(nv.check_layout(t), "split")

    def test_render_roundtrips(self):
        self.assertEqual(nv.parse_dump(nv.render_dump(nv.parse_dump(DUMP))), nv.parse_dump(DUMP))

    def test_app_cannot_be_shrunk_below_what_it_holds(self):
        with self.assertRaises(nv.LayoutError):
            nv.split(nv.parse_dump(DUMP), app_gib=50, new_uuid=NEW_UUID, app_used_bytes=53 * GIB)

    def test_app_blocks_for_resize2fs(self):
        app = self.split().part(1)
        self.assertEqual(nv.app_blocks(app), app.size * 512 // 4096)


class ExtlinuxTests(unittest.TestCase):
    def add(self):
        return nv.add_omarchy_entry(EXTLINUX, root_partuuid=NEW_UUID.lower(), kernel="/boot/raytone-thor/Image",
                                    initrd="/boot/raytone-thor/initrd")

    def test_jetpack_entry_is_unchanged_byte_for_byte(self):
        new = self.add()
        self.assertEqual(nv.entry(new, "primary"), nv.entry(EXTLINUX, "primary"))

    def test_omarchy_is_the_default_and_listed_first(self):
        new = self.add()
        self.assertIn("\nDEFAULT omarchy\n", "\n" + new)
        self.assertLess(new.index("LABEL omarchy"), new.index("LABEL primary"))
        self.assertIn("TIMEOUT 30", new)

    def test_omarchy_entry_boots_its_partition_from_jetpacks_command_line(self):
        e = nv.entry(self.add(), "omarchy")
        self.assertIn("      LINUX /boot/raytone-thor/Image", e)
        # NVIDIA's kernel has the PCIe controller and NVMe as modules: an initramfs loads them
        # (Codex, Slice 4 review; JetPack's own initrd carries the same modules)
        self.assertIn("      INITRD /boot/raytone-thor/initrd", e)
        append = next(l for l in e.splitlines() if l.strip().startswith("APPEND"))
        args = append.split()[1:]
        self.assertEqual(args[0], "${cbootargs}")
        self.assertIn(f"root=PARTUUID={NEW_UUID.lower()}", args)
        self.assertNotIn("root=PARTUUID=1b3479b0-b4c2-4a1b-8b81-86d864b3944e", args)
        for a in ("ro", "rootwait=20", "rootfstype=ext4", "panic=10", "systemd.gpt_auto=0",
                  "firmware_class.path=/etc/firmware", "console=tty0"):
            self.assertIn(a, args)
        self.assertNotIn("rw", args)
        self.assertNotIn("rootwait", args)

    def test_adding_twice_is_refused(self):
        with self.assertRaises(nv.LayoutError):
            nv.add_omarchy_entry(self.add(), root_partuuid=NEW_UUID.lower(), kernel="/boot/raytone-thor/Image",
                                 initrd="/boot/raytone-thor/initrd")

    def test_the_file_must_be_the_one_recorded(self):
        with self.assertRaises(nv.LayoutError):
            nv.add_omarchy_entry(EXTLINUX.replace("DEFAULT primary", "DEFAULT backup"),
                                 root_partuuid=NEW_UUID.lower(), kernel="/boot/raytone-thor/Image",
                                 initrd="/boot/raytone-thor/initrd")


class FstabTests(unittest.TestCase):
    def test_root_moves_to_the_new_partition(self):
        fstab = ("# comment\nPARTUUID=ca5a56c6-4a4b-4e02-8183-ff166514ae3b / ext4 defaults,noatime 0 1\n"
                 "efivarfs /sys/firmware/efi/efivars efivarfs ro,nosuid,nodev,noexec 0 0\n")
        new = nv.retarget_fstab(fstab, NEW_UUID.lower())
        self.assertIn(f"PARTUUID={NEW_UUID.lower()} / ext4 defaults,noatime 0 1\n", new)
        self.assertNotIn("ca5a56c6", new)
        self.assertIn("efivarfs /sys/firmware/efi/efivars", new)

    def test_exactly_one_root_line(self):
        with self.assertRaises(nv.LayoutError):
            nv.retarget_fstab("efivarfs /sys/firmware/efi/efivars efivarfs ro 0 0\n", NEW_UUID.lower())


if __name__ == "__main__":
    unittest.main()
