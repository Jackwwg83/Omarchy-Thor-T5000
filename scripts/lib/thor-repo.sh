# Shared by install-thor-omarchy.sh and publish-thor-repo.sh: the drive's [raytone-thor] repository
# at $MNT$REPO, signed with a local key in $SIGNING (never leaves the Thor's NVMe). Callers mount the
# drive at $MNT with thor_chroot_mount (lib/thor-chroot.sh) and define die().
# shellcheck shell=bash

REPO=/var/lib/raytone/repo
REPO_DB=raytone-thor.db.tar.gz

gpgs() { GNUPGHOME=$SIGNING gpg --batch "$@"; }

# repo_signing_key [--create]: sets $fpr to the signing key's fingerprint.
repo_signing_key() {
  install -d -m 0700 "$SIGNING"
  fpr=$(gpgs --list-secret-keys --with-colons 2>/dev/null | awk -F: '$1 == "fpr" {print $10; exit}')
  if [[ -z $fpr && ${1:-} == --create ]]; then
    echo "+ creating the local repository signing key in $SIGNING"
    gpgs --passphrase '' --quick-generate-key 'RaytoneOS Thor local repository' ed25519 sign never
    fpr=$(gpgs --list-secret-keys --with-colons | awk -F: '$1 == "fpr" {print $10; exit}')
  fi
  [[ $fpr =~ ^[0-9A-F]{40}$ ]] || die "no usable signing key in $SIGNING"
}

# The host (JetPack, as root) writes into the drive's repository, so a link on the drive must not
# redirect those writes to the host: refuse links on the way to the repository and at each target.
repo_no_links() {
  local d=$MNT f
  for f in var lib raytone repo; do
    d=$d/$f
    [[ ! -L $d ]] || die "${d#"$MNT"} on the drive is a link; refusing to write through it"
  done
  for f in "$@"; do
    [[ ! -L $MNT$REPO/$f ]] || die "$REPO/$f on the drive is a link; refusing to write through it"
  done
}

# repo_sign FILE: a detached signature by $fpr next to FILE; an existing one is kept only if it is
# a valid signature by $fpr of this file (a rebuild keeps the file name, not the signature).
repo_sign() {
  if [[ -f $1.sig ]] && gpgs --status-fd 1 --verify "$1.sig" "$1" 2>/dev/null | grep -q "^\[GNUPG:\] VALIDSIG $fpr"; then
    return 0
  fi
  gpgs --yes -u "$fpr" --detach-sign "$1"
}

# repo_publish FILE...: sign and copy each package, then add exactly these to the database.
# Older files stay in the repository for rollback; the database entry is the one published last,
# so only the files named here are added (a glob would add them in name order, -10 before -9).
repo_publish() {
  local f names=() added=()
  for f in "$@"; do names+=("${f##*/}" "${f##*/}.sig"); done
  repo_no_links raytone-thor.gpg "${names[@]}"
  mkdir -p "$MNT$REPO"
  for f in "$@"; do
    repo_sign "$f"
    cp -f "$f" "$f.sig" "$MNT$REPO/"
    added+=("$REPO/${f##*/}")
  done
  gpgs --export "$fpr" > "$MNT$REPO/raytone-thor.gpg"
  in_target repo-add -q "$REPO/$REPO_DB" "${added[@]}"
  [[ -f $MNT$REPO/$REPO_DB ]] || die "repo-add did not create the repository"
}
