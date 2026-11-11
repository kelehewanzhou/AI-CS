#!/bin/bash
# Requires a pre-provisioned GPG public key and SSH destination on the host.
set -euo pipefail
umask 077
file="${1:?Usage: backup-offsite.sh backup/file.dump}"
: "${GPG_RECIPIENT:?Set GPG_RECIPIENT in the backup service environment}"
: "${BACKUP_REMOTE:?Set BACKUP_REMOTE to user@host:/dedicated/path/}"
encrypted=$(mktemp --suffix=.tar.gpg)
trap 'rm -f -- "$encrypted"' EXIT
name=$(basename "$file")
tar -C "$(dirname "$file")" -cf - "$name" "$name.counts" "$name.sha256" |
    gpg --batch --yes --encrypt --recipient "$GPG_RECIPIENT" --output "$encrypted"
scp -- "$encrypted" "${BACKUP_REMOTE%/}/${name}.tar.gpg"
# The dedicated remote location must enforce the same 35-day maximum retention.
