# Gate 0a evidence — 2026-09-24

Arch Linux ARM userspace (glibc 2.43, Mesa 26.2.3, libglvnd 1.7.0, Vulkan loader 1.4.357) in a chroot on the
JetPack 7.2.1 host, against the host's L4T R39.2.1 libraries (driver 595.78), GDM running.
Rootfs: `ArchLinuxARM-aarch64-latest.tar.gz`, MD5 and Arch Linux ARM build-key signature verified (`rootfs.txt`).
All probes ran as uid 1000 with the video and render groups. Raw outputs are the `*.txt` files here; the
monitor serial number has been removed from `drm_info.txt`, and the JSON dump with the raw EDID is not kept.

`summary.txt` is the script's own tally. It counts a probe as failed when any sub-check fails, including
checks expected to fail (alternate EGL devices, linear render targets); the reading below is per check.

## DRM topology

| Node | Driver | Device | Role |
| --- | --- | --- | --- |
| `card3` / `renderD130` | nvidia-drm | platform `nvidia,tegra264-display` | KMS: 4 CRTCs, HDMI-A-1 connected, atomic, `ADDFB2_MODIFIERS`, `SYNCOBJ_TIMELINE`, PRIME import/export |
| `card2` / `renderD129` | nvidia-drm | PCI `10de:2b00` GB10B [Jetson AGX Thor] | GPU, no connectors |
| `card1` | tegra | host1x | no KMS |

`nvidia_drm modeset=Y fbdev=Y`. Primary and overlay planes take NVIDIA block-linear modifiers and linear;
cursor planes take only linear ARGB8888.

EGL devices, as the NVIDIA driver pairs them: 0 = `card3` + `renderD129`, 1 = `card3` + `renderD130`,
2 = `card2` + `renderD129`, 3 = `card1` + `renderD128`, 4 = no DRM device.

## Results

| Check | Status | Evidence |
| --- | --- | --- |
| NVIDIA libraries resolve against Arch glibc; no L4T copy shadows Arch's libvulkan, libgbm, libEGL | real data | `ldd.txt`, `ldcache.txt`, `l4t-excluded.txt` |
| EGL surfaceless: NVIDIA, "NVIDIA Thor/PCIe", OpenGL 4.6 / GLES 3.2, 595.78 | real data | `egl_surfaceless.txt` |
| Vulkan: "NVIDIA Thor", integrated GPU, API 1.4.329, driver 595.78 | real data | `vulkan.txt` |
| GBM + EGL on `card3` (the KMS node): all needed extensions (dma-buf import with modifiers, surfaceless, native fence, wait sync) | real data | `gbmprobe_card3.txt` |
| Path A on `card3`: render into a gbm_surface, lock the front buffer (block-linear `0x0300000000606014`) | real data | `gbmprobe_card3.txt` |
| **Path B on `card3`: scanout buffer with modifiers → dma-buf → EGLImage → FBO complete → rendered green read back as `0 255 0 255`** (the step that fails on Orin) | real data | `gbmprobe_card3.txt` |
| EGLImage from dma-buf sampled as a GL texture | real data | `gbmprobe_card3.txt` |
| Explicit sync: native fence fd exported | real data | `gbmprobe_card3.txt` |
| EGL device platform, device 0 (`card3` + `renderD129`), with buffers allocated on each of `card3`, `renderD130`, `card2`, `renderD129`: import, render, read back green | real data | `devplat_*.txt` |
| Linear buffer usable for scanout **and** rendering | fails, expected | EGL lists linear as external-only; hardware cursor will likely fall back to software |
| GBM platform EGL on `renderD130` or `card2` | fails, `EGL_NOT_INITIALIZED` | `gbmprobe_renderD130.txt`, `gbmprobe_card2.txt` |
| EGL device platform on devices 1–3 | fails | `devplat_*.txt` |
| `eglinfo -p gbm` | fails, probe artefact: it passes `EGL_DEFAULT_DISPLAY`, which NVIDIA's GBM platform rejects | `egl_gbm_default_display.txt` |

## Reading

The GBM/dma-buf render path that blocks Wayland compositors on Orin works on Thor, on the KMS node Hyprland
will use. Hyprland prefers the EGL device platform and picks the first EGL device whose primary node matches
the KMS device, which is device 0 here — the combination that passed with buffers from every node, including
the render node aquamarine opens. A compositor that falls back to GBM-platform EGL on the render node
(`renderD130`) would fail; Gate 0b has to confirm which path Hyprland takes.

Not established by 0a: page flips on a real connector, compositor behaviour, seat and logind permissions,
boot, device-tree selection and module loading.
