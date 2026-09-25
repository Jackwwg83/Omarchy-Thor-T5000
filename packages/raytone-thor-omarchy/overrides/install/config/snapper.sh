# RaytoneOS Thor override of install/config/snapper.sh.
#
# Upstream creates a snapper config for / unconditionally; that fails on the Thor's ext4 root (GRUB
# boot, no snapper, no Limine snapshot entries). Snapshots only make sense on btrfs with snapper.
if [[ $(findmnt -no FSTYPE /) != btrfs ]] || ! command -v snapper >/dev/null; then
  echo "Root is not btrfs with snapper installed; skipping Omarchy snapshot setup"
  exit 0
fi
echo "btrfs root: run upstream install/config/snapper.sh by hand if snapshots are wanted" >&2
