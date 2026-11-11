#!/bin/bash
# Restore only to an independent rehearsal database, never to the live DB.
set -euo pipefail
umask 077
backup_file="${1:?Usage: restore.sh /backup/file.dump [--yes]}"
target="${RESTORE_DATABASE:-kglearn_restore_test}"
[[ "$target" =~ ^kglearn_restore_test(_[a-z0-9]+)?$ ]] || { echo 'Unsafe restore database name' >&2; exit 1; }
export PGHOST="${PGHOST:-localhost}" PGUSER="${POSTGRES_USER:-kglearn_admin}"
export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
test -s "$backup_file"
if [ "${2:-}" != --yes ]; then
    read -r -p "Replace rehearsal database $target? Type yes: " answer
    [ "$answer" = yes ] || exit 1
fi
directory=$(cd "$(dirname "$backup_file")" && pwd)
name=$(basename "$backup_file")
(cd "$directory" && sha256sum --check "$name.sha256")
pg_restore --list "$backup_file" >/dev/null
dropdb --if-exists "$target"
createdb --template=template0 --owner=kglearn_migrator "$target"
pg_restore --exit-on-error --single-transaction --no-owner --role=kglearn_migrator -d "$target" "$backup_file"
actual=$(mktemp)
trap 'rm -f -- "$actual"' EXIT
psql -X -qAt -v ON_ERROR_STOP=1 -d "$target" -f "${VERIFY_SQL:-/opt/kglearn/verify_restore.sql}" >"$actual"
diff -u "$backup_file.counts" "$actual"
cat "$actual"
echo "Restore verified: $target (counts and all foreign keys)"
