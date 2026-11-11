#!/bin/bash
# Run inside postgres: bash /opt/kglearn/backup.sh [daily|release]
set -euo pipefail
umask 077
export TZ=Asia/Shanghai
export PGHOST="${PGHOST:-localhost}" PGUSER="${POSTGRES_USER:-kglearn_admin}"
export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
backup_dir="${BACKUP_DIR:-/backup}"
kind="${1:-daily}"
case "$kind" in daily|release) ;; *) echo 'Expected daily or release' >&2; exit 1;; esac
mkdir -p "$backup_dir/weekly"
exec 9>"$backup_dir/.backup.lock"
# mkdir is portable across images; trap removes only our own lock.
if ! mkdir "$backup_dir/.backup-running" 2>/dev/null; then echo 'Backup already running' >&2; exit 1; fi
stage=$(mktemp -d "$backup_dir/.backup-XXXXXXXX")
cleanup() {
    if [ -n "${snapshot_pid:-}" ]; then kill "$snapshot_pid" 2>/dev/null || true; fi
    rm -rf -- "$stage"
    rmdir "$backup_dir/.backup-running"
}
trap cleanup EXIT
stamp=$(date +%Y%m%d_%H%M%S)
if [ "$kind" = daily ]; then name="kglearn_daily_$(date +%Y%m%d).dump"; else name="kglearn_release_${stamp}_$$.dump"; fi
database="${POSTGRES_DB:-kglearn}"
# Keep an exported snapshot alive so pg_dump and the count manifest describe
# exactly the same committed data even during an online scheduled backup.
coproc SNAPSHOT { psql -X -qAt -v ON_ERROR_STOP=1 -d "$database"; }
snapshot_pid=$SNAPSHOT_PID
exec {snapshot_in}>&"${SNAPSHOT[1]}"
exec {snapshot_out}<&"${SNAPSHOT[0]}"
printf 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SELECT pg_export_snapshot();\n' >&"$snapshot_in"
read -r snapshot_id <&"$snapshot_out"
snapshot_id=${snapshot_id%$'\r'}
[[ "$snapshot_id" =~ ^[0-9A-Fa-f-]+$ ]]
pg_dump -Fc --snapshot="$snapshot_id" -d "$database" -f "$stage/$name"
pg_restore --list "$stage/$name" >/dev/null
psql -X -qAt -v ON_ERROR_STOP=1 -d "$database" \
    -c "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET TRANSACTION SNAPSHOT '$snapshot_id';" \
    -f "${VERIFY_SQL:-/opt/kglearn/verify_restore.sql}" -c COMMIT >"$stage/$name.counts"
printf 'COMMIT;\n\\q\n' >&"$snapshot_in"
wait "$snapshot_pid"
snapshot_pid=''
(cd "$stage" && sha256sum "$name" "$name.counts" >"$name.sha256")
mv -- "$stage/$name" "$stage/$name.counts" "$stage/$name.sha256" "$backup_dir/"
if [ "$kind" = daily ] && [ "$(date +%u)" = 7 ]; then
    week_name="kglearn_week_$(date +%Y%m%d).dump"
    cp -- "$backup_dir/$name" "$backup_dir/weekly/$week_name"
    cp -- "$backup_dir/$name.counts" "$backup_dir/weekly/$week_name.counts"
    (cd "$backup_dir/weekly" && sha256sum "$week_name" "$week_name.counts" >"$week_name.sha256")
fi
prune() {
    local directory=$1 pattern=$2 keep=$3 file index=0
    while IFS= read -r file; do
        index=$((index+1))
        if [ "$index" -gt "$keep" ]; then rm -f -- "$file" "$file.counts" "$file.sha256"; fi
    done < <(find "$directory" -maxdepth 1 -type f -name "$pattern" | LC_ALL=C sort -r)
}
prune "$backup_dir" 'kglearn_daily_*.dump' 14
prune "$backup_dir/weekly" 'kglearn_week_*.dump' 4
# Hard cap: no backup or its metadata survives 35 days.
find "$backup_dir" -maxdepth 2 -type f -name 'kglearn_*.dump*' -mtime +34 -delete
printf '%s\n' "$backup_dir/$name"
