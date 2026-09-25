# RaytoneOS Thor override of install/hardware/nvidia.sh.
#
# Upstream sees the Thor's integrated GPU (10de:2b00, a PCI 3D controller) as a desktop GSP GPU and
# installs nvidia-open-dkms, nvidia-utils and lib32-nvidia-utils. On the Thor the kernel modules,
# OpenGL/EGL/Vulkan libraries and firmware come from NVIDIA's L4T release instead
# (raytone-thor-linux, raytone-thor-graphics), and the desktop packages conflict with them.
# Early KMS is not needed: nv-load-display-modules loads the display driver.
echo "Jetson AGX Thor: NVIDIA drivers come from the raytone-thor L4T packages; nothing to install"
