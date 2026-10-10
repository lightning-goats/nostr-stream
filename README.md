# Lightning Goats Nostr Stream

## OBS with local nginx and zap.stream

The `--zap` installation mode uses this route:

```text
OBS (NVENC, 1080p30, 3 Mbps) -> nginx on localhost:1935/local/lightning-goats
                              |-> native RTMP push -> YouTube
                              |-> native RTMP push -> zap.stream -> HLS / NIP-53
```

`nostr-stream zap` authenticates API requests through the local NIP-46 bunker.
The identity nsec stays in the bunker. The client credential must match
`~/.config/nak/authorized-client.pub`.

```bash
./install.sh --zap
sudo install -m 755 bin/lightning-goats-nginx-routes /usr/local/libexec/
nostr-stream zap account
nostr-stream zap metadata --file ~/.config/nostr-stream/zap-metadata.json
nostr-stream zap metadata --file metadata.json --stream-id ZAP_STREAM_UUID
nostr-stream zap sync-ingest
lightning-goats-obs --check
```

The account command redacts ingest keys. `sync-ingest` fetches the current Basic
endpoint and key from zap.stream and passes them on stdin to the root-owned
`/usr/local/libexec/lightning-goats-nginx-routes` updater. It preserves the YouTube
key from `~/.config/nostr-stream/youtube-service.json` (mode 600). Update that file
when rotating the YouTube key, or set a new YouTube destination in OBS before
closing it; the launcher captures that key before restoring the nginx route.
The zap.stream API does not provide YouTube credentials.

The updater accepts only YouTube's ingest host and `*.zap.stream`, writes
`/etc/nginx/stream-destinations.conf` with mode 600, validates nginx, and reloads
it when a destination changes. A lock serializes updates. Failed validation
restores the previous file; a failed reload also reapplies the previous running
configuration. Keys remain in this root-owned file, outside process arguments.

Include that file inside nginx's `application local` block. Keep the RTMP
listener on loopback and use one worker, `chunk_size 4096`, `push_reconnect 1s`,
`idle_streams off`, `wait_key on`, `wait_video on`, and `meta publish`. Disable
RTMP access logging with `access_log off` in the `rtmp` block.
OBS provides the only video encoding, using NVIDIA NVENC. Nginx forwards the
same encoded video and audio directly to both endpoints without transcoding,
remux processes, or custom publishers. The launcher uses NVIDIA PRIME with
XWayland (`XDG_SESSION_TYPE=x11`, `QT_QPA_PLATFORM=xcb`) so this OBS Snap
selects the NVIDIA GPU for scene rendering as well as NVENC encoding. The
interface stays on the laptop display. Native Wayland selected Intel on this
host despite PRIME variables; verify the selected adapter in the startup log.
The host uses the existing Balanced power profile (`powerprofilesctl set balanced`)
to reduce CPU heat while keeping NVIDIA rendering and encoding active. In
Performance mode, the CPU repeatedly exceeded 90°C with intermittent missed frames.

The installed nginx RTMP module needs the small compatibility patch in
`nginx/rtmp-publish-metadata.patch`. Standard `meta on` and `meta copy` strip
`@setDataFrame`, but zap.stream's RTMP receiver requires that envelope before
it initializes its FLV input. The patch adds opt-in `meta publish`, retaining
normal metadata behavior for other applications. Build it against the exact
installed nginx version with `--with-compat`; validate an isolated nginx
instance and its outgoing metadata before deployment. Rebuild the module after
nginx upgrades. Keep the distribution module and prior configuration for rollback.

Enable `nak-bunker.service` and `nostr-stream-zap.service`. Leave
`youtube-nostr-watch.service` disabled in this mode to avoid another live event.
The zap watcher observes nginx's actual publisher, waits for the current YouTube
broadcast and zap.stream event, creates/reuses one goal and announcement, then
updates that existing event's metadata and goal. It refreshes metadata every 20
minutes and retires the goal after three consecutive confirmed YouTube offline
checks. Older broadcasts remain tracked across restarts until their individual
YouTube URLs are confirmed ended; transient failures reset confirmation counts.
zap.stream owns live/ended status and the playback URL. The watcher accepts
its UK regional service address and chooses HTTPS playback when events also
advertise another transport.

The zap installer wires desktop and login launchers to `lightning-goats-obs`. It refreshes ingest
destinations, initializes metadata, restores OBS's local nginx destination, and
launches OBS with streaming enabled. Existing OBS service settings are backed
up privately before replacement. Close and reopen an already-running OBS
instance to load the new service settings. The launcher selects the uniquely
named `Lightning Goats` scene collection and the `Untitled` profile. Preserve
the camera and overlay in that collection. To open a stopped preview during
repairs, create `~/.config/nostr-stream/hold-stream`; remove it after verifying
the picture to restore automatic streaming on startup.

Run regression tests with `python3 -m unittest discover -s tests -v`. The tests
use generated, disposable identities and local HTTP fixtures; they do not
publish public events or use deployment credentials.

## Original YouTube watcher with self-hosted HLS

Self-hosted Nostr live-stream publishing for the Lightning Goats YouTube channel and Lightning Goats HLS endpoint.

This project watches the Lightning Goats YouTube channel, detects when a broadcast goes live, publishes a NIP-53 `kind:30311` live-stream event, keeps that event fresh while the broadcast is active, and updates it to `status=ended` when YouTube ends.

Live Nostr playback uses the directly playable HLS endpoint:

```text
https://lightning-goats.com/hls/live_goats.m3u8
```

YouTube remains the broadcast identity, announcement link, zap-goal URL reference, and ended-stream recording URL.

For each distinct YouTube broadcast it also:

- creates one NIP-75 `kind:9041` zap goal for **10,000 sats**;
- links the zap goal from the `kind:30311` event;
- publishes one regular `kind:1` announcement note that references the same zap goal;
- retires the zap goal with a NIP-09 deletion request when YouTube is confirmed ended.

## Playback model

The live-event and announcement paths intentionally use different URLs:

```text
OBS / nginx
   |
   +--> YouTube live broadcast
   |       |
   |       +--> watcher identity / video ID
   |       +--> kind-1 announcement link
   |       +--> NIP-75 goal r tag
   |       +--> ended 30311 recording tag
   |
   +--> Lightning Goats HLS
           |
           +--> https://lightning-goats.com/hls/live_goats.m3u8
                  |
                  +--> live 30311 streaming tag
```

This gives Nostr clients such as Primal a direct HLS media source while retaining YouTube as the durable archive and public promotional link.

## Announcement note

Each YouTube video gets one regular note:

```text
Zap Notes. Feed Goats.
https://youtu.be/VIDEO_ID
#CyberHerd
```

The kind-1 note continues to point to YouTube rather than the HLS playlist.

The event also carries `t=cyberherd`, relay-reference tags, and—when the per-stream NIP-75 goal is available—references that same `kind:9041` goal using:

```text
["goal", "<9041-event-id>", "wss://nos.lol/"]
["q", "<9041-event-id>", "wss://nos.lol/", "<goal-author-pubkey>"]
```

NIP-75 formally specifies the `goal` tag for addressable events such as `kind:30311`; clients are therefore not required to render zap-goal UI on a `kind:1` announcement. The `q` tag provides a standards-based event reference, while the additional `goal` tag gives clients that support goal discovery on regular notes the same goal ID.

Kind-1 notes are immutable. If an announcement note was already published before this behavior was installed, the existing note is left alone rather than creating a duplicate solely to add these tags.

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
      |           |
      |           +--> HLS streaming URL
      |           +--> goal reference
      |
      +--> kind 1 announcement
                  |
                  +--> YouTube URL
                  +--> goal + q references to same 9041
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
- the once-per-stream kind-1 announcement references the same stored goal;
- a manual `nostr-stream stop` preserves the goal so watcher self-healing of a still-live YouTube broadcast reuses it;
- when the watcher confirms that YouTube has ended, it calls `nostr-stream stop --delete-goal` and publishes a NIP-09 `kind:5` deletion request for the `kind:9041` goal.

Nostr deletion is a request to relays and clients, not a guarantee that every copy disappears everywhere.

A stored goal can also be retired manually:

```bash
nostr-stream delete-goal 'https://www.youtube.com/watch?v=VIDEO_ID'
```

## NIP-53 event lifecycle

While live, `kind:30311` publishes:

```text
streaming=https://lightning-goats.com/hls/live_goats.m3u8
status=live
```

along with the title, summary, image, original start timestamp, hashtags, and NIP-75 goal reference.

When the YouTube broadcast ends, the same addressable event is updated with:

```text
streaming=https://lightning-goats.com/hls/live_goats.m3u8
recording=https://www.youtube.com/watch?v=VIDEO_ID
status=ended
ends=<unix timestamp>
```

Clients should therefore use HLS for live playback and YouTube for replay/archive playback.

## NIP-53 freshness

Live Activity management clients are expected to keep `kind:30311` events updated. The watcher therefore republishes the same addressable event every **20 minutes** while local state says the stream is active.

The refresh keeps the same:

- `d` identifier;
- title and summary;
- Lightning Goats HLS `streaming` URL;
- YouTube broadcast identity in local state;
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
YouTube @lightning-goats/live      Lightning Goats HLS
          |                              |
          v                              |
  youtube-nostr-watch                    |
          |                              |
          +--------------+---------------+
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

Start a stream using the YouTube broadcast URL:

```bash
nostr-stream start 'https://www.youtube.com/watch?v=VIDEO_ID'
```

The YouTube URL identifies the broadcast. `nostr-stream` creates or recovers the video-specific 10,000-sat zap goal, publishes the NIP-53 event with the Lightning Goats HLS playback URL, records local state, and attempts the regular kind-1 announcement pointing to YouTube.

Check state:

```bash
nostr-stream status
```

Typical output includes:

```text
Nostr stream LIVE
  id:           lightning-goats-...
  streaming:    https://lightning-goats.com/hls/live_goats.m3u8
  YouTube:      https://www.youtube.com/watch?v=...
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
- uses the YouTube video ID as the per-broadcast identity;
- publishes the Lightning Goats HLS URL as NIP-53 `streaming`;
- creates one zap goal per YouTube video ID;
- publishes one regular announcement per YouTube video ID, pointing to YouTube and referencing the same goal when available;
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
