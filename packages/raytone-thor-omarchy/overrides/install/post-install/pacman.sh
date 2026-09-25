# RaytoneOS Thor override of install/post-install/pacman.sh.
#
# Upstream copies its x86_64 pacman.conf and mirrorlist (multilib, Omarchy's x86 mirrors). The Thor
# uses Arch Linux ARM, the port's own repository first (L4T packages, patched Hyprland, Omarchy
# built from the stable release) and Omarchy's aarch64 package repository last.
etc=${RAYTONE_ETC:-/etc}
templates=${RAYTONE_PACMAN_TEMPLATES:-/usr/share/raytone-thor/pacman}
install -m 0644 "$templates/pacman.conf" "$etc/pacman.conf"
install -m 0644 "$templates/mirrorlist" "$etc/pacman.d/mirrorlist"

# As upstream: once CUPS owns the file, apply Omarchy's override.
if [[ -f $OMARCHY_PATH/etc-overrides/cups-cups-files.conf && -f $etc/cups/cups-files.conf ]]; then
  install -m 0640 -o root -g cups "$OMARCHY_PATH/etc-overrides/cups-cups-files.conf" "$etc/cups/cups-files.conf"
  rm -f "$etc/cups/cups-files.conf.pacnew"
fi

source "$OMARCHY_INSTALL/hardware/pacman.sh"
