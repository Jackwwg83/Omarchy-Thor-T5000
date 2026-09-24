import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("thor_boot", ROOT / "scripts" / "thor_boot.py")
tb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tb)

JETPACK = ("root=PARTUUID=1b3479b0-b4c2-4a1b-8b81-86d864b3944e rw rootwait rootfstype=ext4 mminit_loglevel=4 "
           "earlycon=tegra_utc,mmio32,0xc5a0000 console=ttyUTC0,115200 firmware_class.path=/etc/firmware fbcon=map:0 "
           "efi=runtime audit=1 audit_backlog_limit=8192 swiotlb=2048 video=efifb:off console=tty0 "
           "bl_prof_dataptr=6225920@0x2004010000 bl_prof_ro_ptr=65536@0x2004000000")
USB_ROOT = "0f2c55d1-7b3a-4c6e-9a51-2d3e4f5a6b7c"


class CmdlineTests(unittest.TestCase):
    def test_replaces_root_and_drops_boot_loader_profiling(self):
        c = tb.cmdline(JETPACK, USB_ROOT)
        self.assertIn(f"root=PARTUUID={USB_ROOT}", c)
        self.assertNotIn("1b3479b0", c)
        self.assertNotIn("bl_prof", c)

    def test_keeps_platform_arguments_in_order(self):
        c = tb.cmdline(JETPACK, USB_ROOT).split()
        kept = [t for t in JETPACK.split() if not t.startswith(("root=", "bl_prof_"))]
        self.assertEqual([t for t in c if t in kept], kept)

    def test_adds_panic_reboot_once(self):
        c = tb.cmdline(JETPACK + " panic=30", USB_ROOT).split()
        self.assertEqual([t for t in c if t.startswith("panic=")], ["panic=10"])

    def test_rootwait_can_be_bounded_so_a_missing_root_panics_and_reboots(self):
        c = tb.cmdline(JETPACK, USB_ROOT, rootwait=20).split()
        self.assertIn("rootwait=20", c)
        self.assertNotIn("rootwait", c)

    def test_extra_arguments_are_appended(self):
        self.assertTrue(tb.cmdline(JETPACK, USB_ROOT, extra=["rd.emergency=reboot"]).endswith("rd.emergency=reboot"))

    def test_rejects_a_bad_partuuid(self):
        for bad in ("", "abc", "0f2c55d1-7b3a-4c6e-9a51-2d3e4f5a6b7c; reboot"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                tb.cmdline(JETPACK, bad)

    def test_rejects_characters_grub_would_interpret(self):
        with self.assertRaises(ValueError):
            tb.cmdline(JETPACK + " evil=$(x)", USB_ROOT)


class GrubCfgTests(unittest.TestCase):
    def entries(self):
        return [
            tb.Entry(id="jetpack-nvme", title="JetPack on the internal NVMe (its own boot loader)", fs_uuid="2BBE-D8EC",
                     kernel=None, initrd=None, cmdline="", chainload="/EFI/BOOT/BOOTAA64.efi"),
            tb.Entry(id="arch", title="RaytoneOS Arch (test boot)", fs_uuid="51cac00d-1733-4097-a9dc-82f35a4a1c8f",
                     kernel="/boot/Image", initrd="/boot/initramfs-raytone-thor.img", cmdline="root=PARTUUID=x rw"),
        ]

    def cfg(self, default="jetpack-nvme"):
        return tb.grub_cfg(self.entries(), default=default)

    def block(self, cfg, entry_id):
        return cfg.split(f"--id {entry_id} {{")[1].split("\n}")[0]

    def test_default_is_explicit_and_must_be_a_real_entry(self):
        self.assertIn('set default="jetpack-nvme"', self.cfg())
        for bad in ("missing", "retry-reboot", "uefi-menu"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.cfg(default=bad)

    def test_fallback_is_the_number_of_the_reboot_entry(self):
        cfg = self.cfg()
        ids = [line.split("--id ")[1].split()[0] for line in cfg.splitlines() if line.startswith("menuentry")]
        self.assertIn(f'set fallback="{ids.index("retry-reboot")}"', cfg)
        self.assertIn("reboot", self.block(cfg, "retry-reboot"))

    def test_exit_is_only_a_manual_entry(self):
        cfg = self.cfg()
        self.assertIn("exit", self.block(cfg, "uefi-menu"))
        self.assertEqual(cfg.count("exit"), 1)

    def test_one_shot_switches_the_default_only_after_save_env_succeeds(self):
        cfg = self.cfg()
        self.assertIn("load_env -f $prefix/grubenv next_entry", cfg)
        order = [cfg.index(s) for s in ('set try_entry="${next_entry}"', "set next_entry=",
                                        "if save_env -f $prefix/grubenv next_entry; then",
                                        'set default="${try_entry}"', "menuentry")]
        self.assertEqual(order, sorted(order))

    def test_entries_boot_only_after_their_filesystem_is_found(self):
        cfg = self.cfg()
        for entry_id in ("arch", "jetpack-nvme"):
            b = self.block(cfg, entry_id)
            self.assertLess(b.index("if search --no-floppy --fs-uuid --set=root"), b.index("boot\n"))
            self.assertLess(b.index("fi"), b.index("reboot"))
        self.assertIn("linux /boot/Image root=PARTUUID=x rw", self.block(cfg, "arch"))
        self.assertIn("initrd /boot/initramfs-raytone-thor.img", self.block(cfg, "arch"))
        self.assertIn("chainloader /EFI/BOOT/BOOTAA64.efi", self.block(cfg, "jetpack-nvme"))

    def test_never_uses_devicetree(self):
        self.assertNotIn("devicetree", self.cfg())

    def test_entry_ids_are_unique_and_not_reserved(self):
        with self.assertRaises(ValueError):
            tb.grub_cfg(self.entries() * 2, default="arch")
        with self.assertRaises(ValueError):
            tb.grub_cfg([tb.Entry(id="retry-reboot", title="x", fs_uuid="1234-ABCD", kernel="/k", initrd=None,
                                  cmdline="")], default="retry-reboot")

    def test_an_entry_needs_a_kernel_or_a_chainload_target(self):
        with self.assertRaises(ValueError):
            tb.grub_cfg([tb.Entry(id="x", title="x", fs_uuid="1234-ABCD", kernel=None, initrd=None, cmdline="")],
                        default="x")

    def test_rendered_fields_are_validated(self):
        good = dict(id="arch", title="Arch", fs_uuid="1234-ABCD", kernel="/boot/Image", initrd=None, cmdline="rw")
        for field, bad in (("id", "Arch Linux"), ("title", 'x" --id evil'), ("fs_uuid", "1234 --set"),
                           ("kernel", "/boot/Image; reboot"), ("initrd", "/boot/in rd"), ("cmdline", "rw $(x)")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                tb.grub_cfg([tb.Entry(**dict(good, **{field: bad}))], default=good["id"] if field != "id" else bad)


class GrubInstallArgsTests(unittest.TestCase):
    def test_install_arguments_never_touch_nvram(self):
        args = tb.grub_install_args("/mnt/esp")
        for flag in ("--target=arm64-efi", "--removable", "--no-nvram", "--efi-directory=/mnt/esp",
                     "--boot-directory=/mnt/esp/boot"):
            self.assertIn(flag, args)


if __name__ == "__main__":
    unittest.main()
