#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:---youtube}"
[[ "$MODE" == --youtube || "$MODE" == --zap ]] || {
    echo "usage: install.sh [--youtube|--zap]" >&2
    exit 2
}

need() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "install: required command not found: $1" >&2
        exit 1
    }
}

need install
need systemctl
need systemd-creds
need nak
need yt-dlp
need curl
need timeout
if [[ "$MODE" == --zap ]]; then
    need python3
    need sudo
    need nginx
    need semanage
fi

mkdir -p \
    "$HOME/.local/bin" \
    "$HOME/.local/libexec" \
    "$HOME/.config/systemd/user" \
    "$HOME/.config/nak/credentials" \
    "$HOME/.local/state"

chmod 700 \
    "$HOME/.config/nak" \
    "$HOME/.config/nak/credentials"

install -m 0755 "$ROOT/bin/nostr-stream" \
    "$HOME/.local/bin/nostr-stream"

if [[ "$MODE" == --zap ]]; then
    "$ROOT/nginx/build-fedora-module.sh"
    if ! sudo find /etc/nginx -maxdepth 1 -name 'nginx.conf.native-backup-*' -print -quit | grep -q .; then
        sudo cp -a /etc/nginx/nginx.conf "/etc/nginx/nginx.conf.native-backup-$(date +%Y%m%d%H%M%S)"
    fi
    sudo install -o root -g root -m 0644 "$ROOT/nginx/nginx.conf.fedora" /etc/nginx/nginx.conf
    if ! sudo test -e /etc/nginx/stream-destinations.conf; then
        sudo install -o root -g root -m 0600 /dev/null /etc/nginx/stream-destinations.conf
    fi
    sudo install -d -o root -g root -m 0755 /etc/systemd/system/nginx.service.d
    selinux_backup=/var/lib/lightning-goats/selinux-ports-before
    if ! sudo test -e "$selinux_backup"; then
        sudo install -d -o root -g root -m 0700 /var/lib/lightning-goats
        sudo semanage export | sudo tee "$selinux_backup" >/dev/null
        sudo chmod 0600 "$selinux_backup"
    fi
    for port in 1935 8089; do
        if sudo semanage port -l -C | grep -qE "^[[:space:]]+http_port_t[[:space:]].*\\b${port}\\b"; then
            continue
        fi
        if sudo semanage port -l | grep -qE "^[[:space:]]+[^[:space:]]+[[:space:]].*\\b${port}\\b"; then
            sudo semanage port -m -t http_port_t -p tcp "$port"
        else
            sudo semanage port -a -t http_port_t -p tcp "$port"
        fi
    done
    nginx_dropin="$(mktemp)"
    printf '[Unit]\nWants=network-online.target\nAfter=network-online.target\n' >"$nginx_dropin"
    sudo install -o root -g root -m 0644 "$nginx_dropin" \
        /etc/systemd/system/nginx.service.d/10-lightning-goats.conf
    rm -f "$nginx_dropin"
    sudo systemctl daemon-reload
    sudo nginx -t
    sudo systemctl enable nginx
    if systemctl --quiet is-active nginx; then
        sudo systemctl reload nginx
    else
        sudo systemctl start nginx
    fi

    install -m 0755 "$ROOT/bin/nostr-stream-zap" "$HOME/.local/libexec/nostr-stream-zap"
    install -m 0755 "$ROOT/bin/lightning-goats-obs" "$HOME/.local/bin/lightning-goats-obs"
    install -m 0755 "$ROOT/bin/provision-nostr-client" "$HOME/.local/bin/provision-nostr-client"
    install -m 0644 "$ROOT/systemd/nostr-stream-zap.service" "$HOME/.config/systemd/user/nostr-stream-zap.service"
    install -m 0755 "$ROOT/bin/lightning-goats-nginx-routes" \
        "$HOME/.local/libexec/lightning-goats-nginx-routes"
    mkdir -p "$HOME/.config/nostr-stream" "$HOME/.local/state/nostr-stream-zap" \
        "$HOME/.local/state/lightning-goats-stream"
    chmod 700 "$HOME/.config/nostr-stream" "$HOME/.local/state/nostr-stream-zap" \
        "$HOME/.local/state/lightning-goats-stream"
    if [[ ! -e "$HOME/.config/nostr-stream/zap-metadata.json" ]]; then
        install -m 0600 "$ROOT/config/zap-metadata.example.json" "$HOME/.config/nostr-stream/zap-metadata.json"
    fi
    sudo install -o root -g root -m 0755 "$ROOT/bin/lightning-goats-nginx-routes" \
        /usr/local/libexec/lightning-goats-nginx-routes
    sudo install -d -o root -g root -m 0755 /etc/sudoers.d
    sudoers_tmp="$(mktemp)"
    trap 'rm -f "$sudoers_tmp"' EXIT
    printf '%s ALL=(root) NOPASSWD: /usr/local/libexec/lightning-goats-nginx-routes\n' "$USER" >"$sudoers_tmp"
    sudo visudo -cf "$sudoers_tmp" >/dev/null
    sudo install -o root -g root -m 0440 "$sudoers_tmp" /etc/sudoers.d/nostr-stream-nginx-routes
    sudo visudo -c >/dev/null
    rm -f "$sudoers_tmp"
    trap - EXIT
    "$HOME/.local/bin/lightning-goats-obs" --install-desktop
fi

install -m 0755 "$ROOT/bin/youtube-nostr-watch" \
    "$HOME/.local/bin/youtube-nostr-watch"

install -m 0755 "$ROOT/bin/nak-bunker" \
    "$HOME/.local/libexec/nak-bunker"

install -m 0644 "$ROOT/systemd/nak-bunker.service" \
    "$HOME/.config/systemd/user/nak-bunker.service"

install -m 0644 "$ROOT/systemd/youtube-nostr-watch.service" \
    "$HOME/.config/systemd/user/youtube-nostr-watch.service"

systemctl --user daemon-reload

if [[ "$MODE" == --zap ]]; then
    # Keep the existing bunker process alive; enabling an active unit does not restart it.
    systemctl --user enable nak-bunker.service >/dev/null
    systemctl --user disable --now youtube-nostr-watch.service >/dev/null 2>&1 || true
fi

echo
echo "Installed Lightning Goats Nostr stream automation."
echo
if [[ "$MODE" == --zap ]]; then
    echo "zap.stream mode installed. No stream was started."
    echo "The Flatpak OBS launcher uses the discovered profile and scene collection."
    echo "Existing OBS autostart entries were retargeted; no new login autostart was created."
    echo "Root route updater and a command-specific sudoers entry were installed."
    echo "Fedora nginx uses a tested RTMP module, loopback-only ingest, and native dual pushes."
    echo "Keep ~/.config/nostr-stream/youtube-service.json mode 600 with the current YouTube key."
    echo "Enable nostr-stream-zap.service after nginx and NIP-46 credentials are ready."
    echo "youtube-nostr-watch.service is disabled."
    echo "Check readiness with: lightning-goats-obs --check"
    exit 0
fi
echo "Next steps:"
echo "  1. Provision ~/.config/nak/credentials/nostr-key.cred"
echo "  2. Provision ~/.config/nak/credentials/nostr-client.cred"
echo "  3. Write ~/.config/nak/bunker.pub"
echo "  4. Write ~/.config/nak/authorized-client.pub"
echo "  5. systemctl --user enable --now nak-bunker.service"
echo "  6. Test: nostr-stream start <youtube-watch-url>"
echo "  7. Test: nostr-stream stop"
echo "  8. systemctl --user enable --now youtube-nostr-watch.service"
echo
echo "See README.md for key provisioning and operational details."
