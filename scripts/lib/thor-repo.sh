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

# repo_publish FILE...: sign (once) and copy each package, then add exactly these to the database.
# Older files stay in the repository for rollback; the database entry is the one published last,
# so only the files named here are added (a glob would add them in name order, -10 before -9).
repo_publish() {
  local f added=()
  mkdir -p "$MNT$REPO"
  for f in "$@"; do
    [[ -f $f.sig ]] || gpgs --yes -u "$fpr" --detach-sign "$f"
    cp -f "$f" "$f.sig" "$MNT$REPO/"
    added+=("$REPO/${f##*/}")
  done
  gpgs --export "$fpr" > "$MNT$REPO/raytone-thor.gpg"
  in_target repo-add -q "$REPO/$REPO_DB" "${added[@]}"
  [[ -f $MNT$REPO/$REPO_DB ]] || die "repo-add did not create the repository"
}
