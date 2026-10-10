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
    install -m 0755 "$ROOT/bin/nostr-stream-zap" "$HOME/.local/libexec/nostr-stream-zap"
    install -m 0755 "$ROOT/bin/lightning-goats-obs" "$HOME/.local/bin/lightning-goats-obs"
    install -m 0755 "$ROOT/bin/provision-nostr-client" "$HOME/.local/bin/provision-nostr-client"
    install -m 0644 "$ROOT/systemd/nostr-stream-zap.service" "$HOME/.config/systemd/user/nostr-stream-zap.service"
    mkdir -p "$HOME/.config/nostr-stream" "$HOME/.local/state/nostr-stream-zap" \
        "$HOME/.local/state/lightning-goats-stream"
    chmod 700 "$HOME/.config/nostr-stream" "$HOME/.local/state/nostr-stream-zap" \
        "$HOME/.local/state/lightning-goats-stream"
    if [[ ! -e "$HOME/.config/nostr-stream/zap-metadata.json" ]]; then
        install -m 0600 "$ROOT/config/zap-metadata.example.json" "$HOME/.config/nostr-stream/zap-metadata.json"
    fi
    python3 - "$HOME" <<'PY'
from pathlib import Path
import sys
home = Path(sys.argv[1])
launcher = home / ".local/bin/lightning-goats-obs"
applications = home / ".local/share/applications"
applications.mkdir(parents=True, exist_ok=True)
for source in (Path("/var/lib/snapd/desktop/applications/obs-studio_obs-studio.desktop"),
               Path("/usr/share/applications/com.obsproject.Studio.desktop")):
    if source.exists():
        target = applications / source.name
        text = target.read_text() if target.exists() else source.read_text()
        lines = ["Exec=" + str(launcher) if line.startswith("Exec=") else line for line in text.splitlines()]
        target.write_text("\n".join(lines) + "\n")
autostart = home / ".config/autostart/obs.desktop"
autostart.parent.mkdir(parents=True, exist_ok=True)
text = (autostart.read_text() if autostart.exists() else
        "[Desktop Entry]\nType=Application\nName=Lightning Goats OBS\nExec=obs\nX-GNOME-Autostart-enabled=true\n")
autostart.write_text("\n".join("Exec=" + str(launcher) if line.startswith("Exec=") else line
                             for line in text.splitlines()) + "\n")
PY
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

echo
echo "Installed Lightning Goats Nostr stream automation."
echo
if [[ "$MODE" == --zap ]]; then
    echo "zap.stream mode: finish nginx's managed destinations and localhost /stat setup."
    echo "Keep the YouTube destination profile in ~/.config/nostr-stream/youtube-service.json (mode 600)."
    echo "Install bin/lightning-goats-nginx-routes under /usr/local/libexec as root."
    echo "Enable nak-bunker.service and nostr-stream-zap.service; leave youtube-nostr-watch.service disabled."
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
