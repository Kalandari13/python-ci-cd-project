#!/bin/sh
# Custom-format PostgreSQL dumps, checked before becoming visible as backups.
set -eu
umask 077
backup_dir=/backups
mkdir -p "$backup_dir"
backup_once() {
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    partial="$backup_dir/gather-$stamp-$$.partial"
    final="$backup_dir/gather-$stamp-$$.dump"
    if pg_dump --format=custom --file="$partial"; then
        if pg_restore --list "$partial" > /dev/null; then
            mv "$partial" "$final"
            echo "Database backup saved: $(basename "$final")"
        else
            rm -f "$partial"
            return 1
        fi
    else
        rm -f "$partial"
        return 1
    fi
}
if [ "${1:-}" = '--once' ]; then
    backup_once
    exit
fi
while :; do
    # A temporary failure retries after five minutes rather than waiting a day.
    if backup_once; then sleep 86400; else sleep 300; fi
done
