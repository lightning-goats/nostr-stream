#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

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

install -m 0755 "$ROOT/bin/youtube-nostr-watch" \
    "$HOME/.local/bin/youtube-nostr-watch"

install -m 0755 "$ROOT/bin/nak-bunker" \
    "$HOME/.local/libexec/nak-bunker"

install -m 0644 "$ROOT/systemd/nak-bunker.service" \
    "$HOME/.config/systemd/user/nak-bunker.service"

install -m 0644 "$ROOT/systemd/youtube-nostr-watch.service" \
    "$HOME/.config/systemd/user/youtube-nostr-watch.service"

systemctl --user daemon-reload

echo
echo "Installed Lightning Goats Nostr stream automation."
echo
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
