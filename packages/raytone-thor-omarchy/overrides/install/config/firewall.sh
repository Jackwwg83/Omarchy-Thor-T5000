# RaytoneOS Thor override of install/config/firewall.sh.
#
# Upstream's rules, plus SSH and mDNS so the Thor stays reachable over the network (it is
# administered remotely, and upstream denies all incoming traffic). Upstream writes ENABLED=yes and
# only then relies on UFW doing file-only updates; with ENABLED=yes, ufw commands update the running
# kernel's iptables, which in this chroot would be JetPack's. Here UFW stays disabled while every
# rule is written, so each ufw command only edits files, and ENABLED=yes is the last step, after the
# SSH rule is confirmed. A failure anywhere leaves UFW disabled: no lockout on the next boot.
ufw_conf=${RAYTONE_UFW_CONF:-/etc/ufw/ufw.conf}
# Rewrites the file in place (keeps its mode and owner).
set_enabled() {
  sed "s/^ENABLED=.*/ENABLED=$1/" "$ufw_conf" >"$ufw_conf.raytone"
  cat "$ufw_conf.raytone" >"$ufw_conf"
  rm -f "$ufw_conf.raytone"
  grep -qx "ENABLED=$1" "$ufw_conf"
}
set_enabled no

# Allow nothing in, everything out.
ufw default deny incoming
ufw default allow outgoing

# Allow ports for LocalSend.
ufw allow 53317/udp
ufw allow 53317/tcp

# Allow Docker containers to use DNS on host.
ufw allow in proto udp from 172.16.0.0/12 to 172.17.0.1 port 53 comment 'allow-docker-dns'
ufw allow in proto udp from 192.168.0.0/16 to 172.17.0.1 port 53 comment 'allow-docker-dns'

# Thor: remote administration and .local name resolution.
ufw allow 22/tcp comment 'raytone-ssh'
ufw allow 5353/udp comment 'raytone-mdns'

# Upstream's ufw-docker step, unchanged: a status shim satisfies ufw-docker's preflight.
install_ufw_docker_rules() {
  local shim_dir status ufw_docker_bin

  ufw_docker_bin=$(command -v ufw-docker)
  shim_dir=$(mktemp -d)
  cat >"$shim_dir/ufw" <<'SHIM'
#!/bin/bash
if [[ ${1:-} == "status" ]]; then
  echo "Status: active"
  exit 0
fi

exec /usr/bin/ufw "$@"
SHIM

  sed "0,/^PATH=/s#^PATH=.*#PATH=\"$shim_dir:/bin:/usr/bin:/sbin:/usr/sbin:/snap/bin/\"#" \
    "$ufw_docker_bin" >"$shim_dir/ufw-docker"
  chmod 755 "$shim_dir/ufw" "$shim_dir/ufw-docker"

  if "$shim_dir/ufw-docker" install; then
    status=0
  else
    status=$?
  fi

  rm -rf "$shim_dir"
  return "$status"
}

install_ufw_docker_rules

# Enable for the next boot only now that every rule is in place.
set_enabled yes
systemctl enable ufw
