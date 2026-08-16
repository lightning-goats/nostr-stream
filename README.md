# Lightning Goats Nostr Stream

Self-hosted Nostr live-stream publishing for the Lightning Goats YouTube channel.

This project watches the Lightning Goats YouTube channel, detects when a broadcast goes live, publishes a NIP-53 `kind:30311` live-stream event, keeps that event fresh while the broadcast is active, and updates it to `status=ended` when YouTube ends.

For each distinct YouTube broadcast it also:

- creates one NIP-75 `kind:9041` zap goal for **10,000 sats**;
- links the zap goal from the `kind:30311` event;
- publishes one regular `kind:1` announcement note;
- retires the zap goal with a NIP-09 deletion request when YouTube is confirmed ended.

The video itself remains hosted by YouTube. Nostr provides discovery, live-event metadata, zap-goal metadata, and the once-per-broadcast announcement.

## Announcement note

Each YouTube video gets one regular note:

```text
Zap Notes. Feed Goats.
https://youtu.be/VIDEO_ID
#CyberHerd
```

The event also carries `t=cyberherd` and relay-reference tags.

## NIP-75 zap goal

Each distinct YouTube video gets one `kind:9041` goal with a target of:

```text
10,000 sats = 10,000,000 millisats
```

The goal describes the target as up to ten 1,000-sat Lightning-powered goat feedings.

Conceptually:

```text
YouTube broadcast
      |
      +--> kind 9041 zap goal (10,000 sats)
      |          |
      |          +--> persisted by YouTube video ID
      |
      +--> kind 30311 live event
                  |
                  +--> ["goal", "<9041-event-id>", "wss://nos.lol/"]
```

The feeder's own payment/cycle accounting remains authoritative. The NIP-75 goal represents Nostr-attributable zaps for the stream and is not used to actuate the feeder directly.

### Goal lifetime and idempotency

Goal IDs are stored under:

```text
~/.local/state/lightning-goats-stream/goals/VIDEO_ID
```

This means:

- watcher restarts do not create another goal for the same YouTube video;
- NIP-53 refreshes reuse the same goal;
- a manual `nostr-stream stop` preserves the goal so watcher self-healing of a still-live YouTube broadcast reuses it;
- when the watcher confirms that YouTube has ended, it calls `nostr-stream stop --delete-goal` and publishes a NIP-09 `kind:5` deletion request for the `kind:9041` goal.

Nostr deletion is a request to relays and clients, not a guarantee that every copy disappears everywhere.

A stored goal can also be retired manually:

```bash
nostr-stream delete-goal 'https://www.youtube.com/watch?v=VIDEO_ID'
```

## NIP-53 freshness

Live Activity management clients are expected to keep `kind:30311` events updated. The watcher therefore republishes the same addressable event every **20 minutes** while local state says the stream is active.

The refresh keeps the same:

- `d` identifier;
- title and summary;
- YouTube streaming URL;
- image;
- original `starts` timestamp;
- zap-goal event ID;
- `status=live`.

Only the event's timestamp/signature/version changes.

Freshness is maintained even if a YouTube metadata check temporarily fails, so a bot challenge or transient `yt-dlp` error does not allow an otherwise-live NIP-53 event to become stale.

Manual controls:

```bash
nostr-stream refresh
nostr-stream refresh-if-due 1200
```

## Components

```text
YouTube @lightning-goats/live
          |
          v
  youtube-nostr-watch
          |
          v
      nostr-stream
       /    |    \
      /     |     \
 30311    9041    kind 1
      \     |     /
       \    |    /
          NIP-46
            |
            v
        nak bunker
            |
            v
       Nostr relays
```

Repository files:

```text
bin/nak-bunker
bin/nostr-stream
bin/youtube-nostr-watch
systemd/nak-bunker.service
systemd/youtube-nostr-watch.service
install.sh
```

## Security model

Two separate keypairs are used:

1. **Nostr identity key** — authors NIP-53, NIP-75, deletion requests, and announcement notes. Its private key is stored as a systemd encrypted credential and decrypted only for the `nak bunker` process.
2. **Automation client key** — dedicated NIP-46 client keypair. Its public key is authorized by the bunker and its private key is separately stored as a systemd encrypted credential.

No private keys, encrypted credential files, or local bunker state belong in this repository.

## Requirements

Linux with a recent systemd and:

- `nak`
- `yt-dlp`
- `curl`
- GNU `timeout` / coreutils
- `systemd-creds`

Check them with:

```bash
command -v nak
command -v yt-dlp
command -v curl
command -v timeout
command -v systemd-creds
```

## Install

```bash
git clone https://github.com/lightning-goats/nostr-stream.git
cd nostr-stream
./install.sh
```

The installer copies files to:

```text
~/.local/bin/nostr-stream
~/.local/bin/youtube-nostr-watch
~/.local/libexec/nak-bunker
~/.config/systemd/user/nak-bunker.service
~/.config/systemd/user/youtube-nostr-watch.service
```

It intentionally does **not** create or import keys.

## Provision the Nostr identity

Create the credential directory:

```bash
mkdir -p ~/.config/nak/credentials
chmod 700 ~/.config/nak ~/.config/nak/credentials
```

Encrypt the 64-character hex Nostr identity private key:

```bash
read -rsp 'Nostr identity hex secret: ' NOSTR_HEX
echo

printf '%s' "$NOSTR_HEX" |
  systemd-creds encrypt \
    --user \
    --name=nostr-key \
    - \
    ~/.config/nak/credentials/nostr-key.cred

unset NOSTR_HEX
chmod 600 ~/.config/nak/credentials/nostr-key.cred
```

Store its public key:

```bash
systemd-creds decrypt \
  --user \
  --name=nostr-key \
  ~/.config/nak/credentials/nostr-key.cred - |
  nak key public > ~/.config/nak/bunker.pub

chmod 600 ~/.config/nak/bunker.pub
```

## Create and authorize the NIP-46 client

```bash
CLIENT_SEC="$(nak key generate)"
CLIENT_PUB="$(printf '%s' "$CLIENT_SEC" | nak key public)"

printf '%s\n' "$CLIENT_PUB" > ~/.config/nak/authorized-client.pub
chmod 600 ~/.config/nak/authorized-client.pub

printf '%s' "$CLIENT_SEC" |
  systemd-creds encrypt \
    --user \
    --name=nostr-client \
    - \
    ~/.config/nak/credentials/nostr-client.cred

unset CLIENT_SEC
chmod 600 ~/.config/nak/credentials/nostr-client.cred
```

## Start the bunker

```bash
systemctl --user daemon-reload
systemctl --user enable --now nak-bunker.service
systemctl --user status nak-bunker.service
```

If it must survive logout and start with the machine:

```bash
sudo loginctl enable-linger "$USER"
```

## Manual operation

Start a stream:

```bash
nostr-stream start 'https://www.youtube.com/watch?v=VIDEO_ID'
```

This creates or recovers the video-specific 10,000-sat zap goal, publishes the NIP-53 event linked to that goal, records local state, and attempts the regular kind-1 announcement.

Check state:

```bash
nostr-stream status
```

Typical output includes:

```text
Nostr stream LIVE
  id:           lightning-goats-...
  video:        https://www.youtube.com/watch?v=...
  cover:        ...
  start:        ...
  last-refresh: ...
  goal:         <9041-event-id>
  goal-target:  10000 sats
  note:         published
```

A manual stop preserves the zap goal:

```bash
nostr-stream stop
```

This is useful because the watcher will recreate the NIP-53 live event if YouTube is still live, and the same goal is reused.

To explicitly end a stream and retire its goal:

```bash
nostr-stream stop --delete-goal
```

## Automatic YouTube monitoring

The watcher monitors:

```text
https://www.youtube.com/@lightning-goats/live
```

Enable it after manual publishing works:

```bash
systemctl --user enable --now youtube-nostr-watch.service
```

Follow logs:

```bash
journalctl --user -u youtube-nostr-watch.service -f
```

Default behavior:

- polls YouTube every 30 seconds;
- starts only when `yt-dlp` reports `live_status=is_live`;
- creates one zap goal per YouTube video ID;
- publishes one regular announcement per YouTube video ID;
- refreshes the active NIP-53 event every 20 minutes;
- requires three consecutive confirmed-offline checks before ending Nostr;
- treats extraction failures, DNS errors, timeouts, and YouTube bot challenges as indeterminate, not proof that the stream ended;
- self-heals if Nostr is manually stopped while the same YouTube broadcast remains live;
- retires the NIP-75 goal when YouTube is actually confirmed ended or a different live video replaces it.

## Cover images

For a YouTube watch URL, `nostr-stream` tries:

```text
https://i.ytimg.com/vi/VIDEO_ID/maxresdefault.jpg
https://i.ytimg.com/vi/VIDEO_ID/hqdefault.jpg
```

If neither is available, it uses the configured Lightning Goats fallback image.

## Operations

```bash
# Current state
nostr-stream status

# Force a NIP-53 refresh
nostr-stream refresh

# Idempotently ensure the announcement exists
nostr-stream announce 'https://www.youtube.com/watch?v=VIDEO_ID'

# Retire a stored zap goal manually
nostr-stream delete-goal 'https://www.youtube.com/watch?v=VIDEO_ID'

# Watcher
systemctl --user status youtube-nostr-watch.service
systemctl --user restart youtube-nostr-watch.service
journalctl --user -u youtube-nostr-watch.service -f
```

## Updating

```bash
cd nostr-stream
git pull
./install.sh
systemctl --user restart youtube-nostr-watch.service
```

A bunker restart is only necessary when bunker code/configuration or credentials change.

## License

MIT
