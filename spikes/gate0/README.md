# Gate 0 spikes

Throw-away probes for the plan's biggest risk: whether Hyprland can run on the
Thor's GBM/EGL stack with an Arch userspace. They are kept for the record only;
nothing here is packaged, and the build tooling that replaces them is written
test-first.

## gate0a.sh — no display interruption

Runs on JetPack as the normal user; GDM keeps running.

1. Downloads the Arch Linux ARM rootfs tarball and checks its MD5 and signature.
2. Writes read-only facts for the package ledger to `~/raytone/cache/l4t-host/`:
   files per `nvidia-l4t-*` package, apt policy, module paths and vermagic,
   maintainer scripts, modprobe/depmod config and NVIDIA service units.
   These are NVIDIA's files; they stay out of git.
3. In a private mount namespace (`sudo unshare --mount`), unpacks the rootfs to
   `~/raytone/probe-root`, mounts a fresh read-only sysfs (no efivarfs), binds the
   host's L4T library directories read-only, and links an allowlisted subset of
   those libraries into `/usr/lib/raytone-l4t` so that L4T's own `libvulkan` and
   `libv4l` copies cannot shadow Arch's.
4. Runs `drm_info`, `eglinfo` (device, surfaceless, GBM) and `vulkaninfo` inside
   the root and writes each output to `~/raytone/evidence/gate0a/`.

Host changes: files under `~/raytone` only. The chroot binds the host `/dev`, so
nothing in it may write there.

What 0a cannot show: page flips on a real connector, compositor behaviour,
seat/logind permissions, boot, device-tree selection or module loading.
Gate 0b covers the first three.
