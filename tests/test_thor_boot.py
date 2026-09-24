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
        return [tb.Entry(id="arch", title="RaytoneOS Arch (test boot)", fs_uuid="1111-aaaa",
                         kernel="/boot/Image", initrd="/boot/initramfs-raytone-thor.img", cmdline="root=PARTUUID=x rw")]

    def test_default_hands_back_to_the_firmware(self):
        cfg = tb.grub_cfg(self.entries())
        self.assertIn('set default="firmware-next"', cfg)
        self.assertIn('set fallback="firmware-next"', cfg)
        block = cfg[cfg.index('--id firmware-next'):]
        self.assertIn("exit 1", block.split("}")[0])

    def test_one_shot_entry_is_cleared_before_it_boots(self):
        cfg = tb.grub_cfg(self.entries())
        load, use, clear, save = (cfg.index(s) for s in (
            "load_env", 'set default="${next_entry}"', "set next_entry=", "save_env"))
        self.assertLess(load, use)
        self.assertLess(use, clear)
        self.assertLess(clear, save)
        self.assertLess(save, cfg.index("menuentry"))

    def test_entries_find_their_filesystem_by_uuid(self):
        cfg = tb.grub_cfg(self.entries())
        self.assertIn("search --no-floppy --fs-uuid --set=root 1111-aaaa", cfg)
        self.assertIn("linux /boot/Image root=PARTUUID=x rw", cfg)
        self.assertIn("initrd /boot/initramfs-raytone-thor.img", cfg)

    def test_never_uses_devicetree(self):
        self.assertNotIn("devicetree", tb.grub_cfg(self.entries()))

    def test_entry_ids_are_unique_and_not_reserved(self):
        with self.assertRaises(ValueError):
            tb.grub_cfg(self.entries() * 2)
        with self.assertRaises(ValueError):
            tb.grub_cfg([tb.Entry(id="firmware-next", title="x", fs_uuid="1", kernel="/k", initrd=None, cmdline="")])


class ChainloadTests(unittest.TestCase):
    def menu(self, default="jetpack-nvme"):
        return tb.grub_cfg([
            tb.Entry(id="jetpack-nvme", title="JetPack on the internal NVMe (its own boot loader)", fs_uuid="ABCD-1234",
                     kernel=None, initrd=None, cmdline="", chainload="/EFI/BOOT/BOOTAA64.efi"),
            tb.Entry(id="jetpack-grub", title="JetPack kernel via GRUB", fs_uuid="1111-aaaa",
                     kernel="/boot/Image", initrd="/boot/initrd", cmdline="root=PARTUUID=x rw"),
        ], default=default)

    def test_chainload_entry_loads_the_other_boot_loader(self):
        block = self.menu().split("--id jetpack-nvme")[1].split("}")[0]
        self.assertIn("search --no-floppy --fs-uuid --set=root ABCD-1234", block)
        self.assertIn("chainloader /EFI/BOOT/BOOTAA64.efi", block)
        self.assertNotIn("linux ", block)

    def test_default_can_be_an_entry_and_fallback_stays_the_firmware(self):
        cfg = self.menu()
        self.assertIn('set default="jetpack-nvme"', cfg)
        self.assertIn('set fallback="firmware-next"', cfg)

    def test_default_must_exist(self):
        with self.assertRaises(ValueError):
            self.menu(default="arch")

    def test_an_entry_needs_a_kernel_or_a_chainload_target(self):
        with self.assertRaises(ValueError):
            tb.grub_cfg([tb.Entry(id="x", title="x", fs_uuid="1", kernel=None, initrd=None, cmdline="")])


class GrubInstallArgsTests(unittest.TestCase):
    def test_install_arguments_never_touch_nvram(self):
        args = tb.grub_install_args("/mnt/esp")
        for flag in ("--target=arm64-efi", "--removable", "--no-nvram", "--efi-directory=/mnt/esp",
                     "--boot-directory=/mnt/esp/boot"):
            self.assertIn(flag, args)


if __name__ == "__main__":
    unittest.main()
