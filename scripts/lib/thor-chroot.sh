# Shared by the Thor USB installers: a chroot of the drive's root at $MNT with fresh proc,
# read-only sysfs without efivarfs, a private /dev, and its own /run and /tmp. Commands run inside
# with dangerous capabilities dropped and no_new_privs set. Callers mount the drive at $MNT and run
# inside private mount and PID namespaces; $HOST_ETC is the host's /etc (for resolv.conf).
# shellcheck shell=bash

# Capabilities the package manager and Omarchy's setup never need; dropping them also keeps them
# from loading modules, remounting efivarfs, touching raw devices, or changing the host's network
# stack and firewall (net_admin, net_raw): the chroot shares the running kernel.
DROP_CAPS=-sys_module,-sys_rawio,-sys_boot,-sys_time,-bpf,-perfmon,-mac_admin,-mac_override,-syslog,-wake_alarm,-sys_admin,-sys_ptrace,-mknod,-kill,-net_admin,-net_raw

thor_chroot_mount() {
  local n
  mkdir -p "$MNT"/{proc,sys,dev,run,tmp}
  mount -t proc proc "$MNT/proc"
  # The kernel's tunables and sysrq belong to the running host: read-only inside.
  mount --bind "$MNT/proc/sys" "$MNT/proc/sys"
  mount -o remount,bind,ro "$MNT/proc/sys"
  mount --bind "$MNT/proc/sysrq-trigger" "$MNT/proc/sysrq-trigger"
  mount -o remount,bind,ro "$MNT/proc/sysrq-trigger"
  mount -t sysfs -o ro,nosuid,nodev,noexec sysfs "$MNT/sys"
  mount -t tmpfs -o mode=0755,nosuid tmpfs "$MNT/dev"
  for n in null zero full random urandom tty; do touch "$MNT/dev/$n"; mount --bind "/dev/$n" "$MNT/dev/$n"; done
  mkdir -p "$MNT/dev/pts" "$MNT/dev/shm"
  mount -t devpts -o newinstance,ptmxmode=0666 devpts "$MNT/dev/pts"
  ln -sf pts/ptmx "$MNT/dev/ptmx"
  ln -sf /proc/self/fd "$MNT/dev/fd"
  ln -sf /proc/self/fd/0 "$MNT/dev/stdin"
  ln -sf /proc/self/fd/1 "$MNT/dev/stdout"
  ln -sf /proc/self/fd/2 "$MNT/dev/stderr"
  mount -t tmpfs -o mode=0755 tmpfs "$MNT/run"
  mount -t tmpfs -o mode=1777 tmpfs "$MNT/tmp"
  rm -f "$MNT/etc/resolv.conf"
  cat "$HOST_ETC/resolv.conf" > "$MNT/etc/resolv.conf" 2>/dev/null || true
}

# in_target CMD... : as root in the drive's chroot.
in_target() {
  setpriv --no-new-privs --bounding-set "$DROP_CAPS" -- \
    chroot "$MNT" /usr/bin/env -i PATH=/usr/bin HOME=/root LANG=C.UTF-8 "$@"
}
