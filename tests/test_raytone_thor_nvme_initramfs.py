"""The initramfs the NVMe install boots with carries the PCIe controller and NVMe drivers, which
NVIDIA's kernel builds as modules (pcie_tegra264, phy_tegra194_p2u, nvme), as JetPack's own initrd
does; the kernel sync copies it to JetPack's APP with the kernel, after mkinitcpio has rebuilt it."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "packages" / "raytone-thor-omarchy"


class NvmeInitramfsTests(unittest.TestCase):
    def test_mkinitcpio_takes_the_nvme_boot_modules(self):
        conf = (PKG / "mkinitcpio-raytone-thor-nvme.conf").read_text()
        self.assertIn("MODULES+=(pcie_tegra264 phy_tegra194_p2u nvme)", conf.splitlines())
        text = (PKG / "PKGBUILD").read_text()
        self.assertIn("etc/mkinitcpio.conf.d/raytone-thor-nvme.conf", text)

    def test_the_sync_runs_after_mkinitcpio_and_copies_the_initramfs(self):
        # alpm runs hooks in name order: mkinitcpio's is 90-mkinitcpio-install.hook
        self.assertTrue((PKG / "95-raytone-thor-nvme-kernel.hook").exists())
        self.assertFalse((PKG / "90-raytone-thor-nvme-kernel.hook").exists())
        script = (PKG / "raytone-thor-nvme-kernel-sync").read_text()
        self.assertIn("INITRD", script)


if __name__ == "__main__":
    unittest.main()
