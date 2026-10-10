#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

if [[ $EUID -ne 0 || $# -ne 1 || ! -f $1 ]]; then
    echo "usage: sudo install-tested-module.sh CANDIDATE_MODULE" >&2
    exit 2
fi

candidate=$1
target=/usr/lib64/nginx/modules/ngx_rtmp_module.so
backup="${target}.before-relay-fix-$(date +%Y%m%d%H%M%S)"
install -d -o root -g root -m 0755 "$(dirname "$target")"
cp -a "$target" "$backup"
install -o root -g root -m 0755 "$candidate" "$target"

restore() {
    install -o root -g root -m 0755 "$backup" "$target"
    /usr/sbin/nginx -t
    /usr/bin/systemctl reload nginx
}

if ! /usr/sbin/nginx -t; then
    restore
    exit 1
fi
if ! /usr/bin/systemctl reload nginx; then
    restore
    exit 1
fi

echo "Tested RTMP module installed; nginx reloaded gracefully. Backup: $backup"
