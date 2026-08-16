# Lightning Goats Nostr Stream

Self-hosted Nostr live-stream publishing for the Lightning Goats YouTube channel.

This project watches the Lightning Goats YouTube channel, detects when a broadcast goes live, and publishes the broadcast to Nostr as a NIP-53 `kind:30311` live-stream event. When the YouTube broadcast ends, it updates the same Nostr event to `status=ended`.

The video itself remains hosted by YouTube. Nostr is used for discovery and live-event metadata. No zap.stream account or hosted Nostr streaming service is required.

## Components

```text
YouTube @lightning-goats/live
          |
          v
  youtube-nostr-watch
          |
          v
      nostr-stream
          |
          | NIP-46
          v
      nak bunker
          |
          v
     Nostr relays
```

The repository contains:

```text
bin/nak-bunker             NIP-46 signer launcher
bin/nostr-stream           Start/stop a NIP-53 live event
bin/youtube-nostr-watch    YouTube live-state watcher
systemd/nak-bunker.service
systemd/youtube-nostr-watch.service
install.sh
```

## Security model

Two separate keypairs are used:

1. **Nostr identity key** — the identity that authors the NIP-53 events. Its private key is stored as a systemd encrypted credential and is only decrypted for the `nak bunker` process.
2. **Automation client key** — a dedicated NIP-46 client keypair. Its public key is authorized by the bunker; its private key is stored separately as another systemd encrypted credential.

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

Use the 64-character hex form of the Nostr identity private key:

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

Derive and store only its public key for the publisher:

```bash
systemd-creds decrypt \
  --user \
  --name=nostr-key \
  ~/.config/nak/credentials/nostr-key.cred - |
  nak key public > ~/.config/nak/bunker.pub

chmod 600 ~/.config/nak/bunker.pub
```

## Create and authorize the NIP-46 client

Generate a dedicated automation client keypair:

```bash
CLIENT_SEC="$(nak key generate)"
CLIENT_PUB="$(printf '%s' "$CLIENT_SEC" | nak key public)"

echo "Authorized client pubkey: $CLIENT_PUB"
```

Store the public key used by the bunker:

```bash
printf '%s\n' "$CLIENT_PUB" > ~/.config/nak/authorized-client.pub
chmod 600 ~/.config/nak/authorized-client.pub
```

Encrypt the corresponding private key:

```bash
printf '%s' "$CLIENT_SEC" |
  systemd-creds encrypt \
    --user \
    --name=nostr-client \
    - \
    ~/.config/nak/credentials/nostr-client.cred

unset CLIENT_SEC
chmod 600 ~/.config/nak/credentials/nostr-client.cred
```

Verify the encrypted credential corresponds to the authorized public key without displaying the secret:

```bash
systemd-creds decrypt \
  --user \
  --name=nostr-client \
  ~/.config/nak/credentials/nostr-client.cred - |
  nak key public

cat ~/.config/nak/authorized-client.pub
```

The two public keys must match.

## Start the bunker

```bash
systemctl --user daemon-reload
systemctl --user enable --now nak-bunker.service
systemctl --user status nak-bunker.service
```

Logs:

```bash
journalctl --user -u nak-bunker.service -f
```

The launcher runs `nak bunker` in quiet mode. This is intentional: some `nak` versions print a restart command containing a supplied signer secret when the bunker is not persistent and logging is enabled.

If the service must survive logout and start with the machine:

```bash
sudo loginctl enable-linger "$USER"
```

## Test publishing manually

Before enabling the watcher, test the NIP-53 publisher with a real YouTube watch URL:

```bash
nostr-stream start 'https://www.youtube.com/watch?v=VIDEO_ID'
```

Check state:

```bash
nostr-stream status
```

End the event:

```bash
nostr-stream stop
```

`start` always requires an explicit stream URL. There is no implicit Twitch or other playback fallback.

### NIP-53 event lifecycle

`start` publishes a unique addressable `kind:30311` event containing:

- `d`
- `title`
- `summary`
- `streaming`
- `image`
- `starts`
- `status=live`
- `t=bitcoin`
- `t=lightning`
- `t=goats`

`stop` republishes the same `kind + pubkey + d` address with:

- `status=ended`
- `ends=<unix timestamp>`
- `recording=<stream URL>`

while retaining the original stream metadata.

Active state is stored under:

```text
~/.local/state/lightning-goats-stream/
```

The script does not mark a stream active until publication succeeds. If ending the event fails, it preserves the active state so `stop` can be retried.

## Cover images

For a YouTube watch URL, `nostr-stream` extracts the video ID locally and tries:

```text
https://i.ytimg.com/vi/VIDEO_ID/maxresdefault.jpg
https://i.ytimg.com/vi/VIDEO_ID/hqdefault.jpg
```

If neither is available, it uses the configured Lightning Goats fallback image.

This avoids giving the service browser cookies merely to retrieve a thumbnail.

## Enable automatic YouTube monitoring

The watcher monitors:

```text
https://www.youtube.com/@lightning-goats/live
```

Enable it only after manual start/stop works:

```bash
systemctl --user enable --now youtube-nostr-watch.service
```

Follow its log:

```bash
journalctl --user -u youtube-nostr-watch.service -f
```

Default behavior:

- poll every 30 seconds;
- start only when `yt-dlp` reports `live_status=is_live`;
- construct the canonical `https://www.youtube.com/watch?v=VIDEO_ID` URL;
- remember the YouTube video ID so the same broadcast is not repeatedly started;
- require three consecutive confirmed-offline checks before ending Nostr, approximately 90 seconds at the default poll interval;
- treat extraction failures, DNS errors, timeouts, and YouTube bot challenges as **indeterminate**, not as proof that the stream ended;
- automatically repair state if Nostr was manually stopped while the same YouTube broadcast is still live.

### Manual stop while YouTube is still live

If the watcher is running and you execute:

```bash
nostr-stream stop
```

then the next successful watcher poll will see that YouTube is still live but Nostr is inactive, and it will publish a new live event.

To intentionally keep a currently-live YouTube broadcast off Nostr:

```bash
systemctl --user stop youtube-nostr-watch.service
nostr-stream stop
```

Re-enable automation later:

```bash
systemctl --user start youtube-nostr-watch.service
```

## YouTube bot challenges

YouTube may occasionally cause `yt-dlp` to fail with a sign-in / bot-confirmation challenge. The watcher deliberately does not interpret this as offline.

If a bot challenge occurs while a Nostr stream is already live, the Nostr event remains live until YouTube can again be checked successfully and three confirmed-offline checks occur.

If bot challenges persist before a broadcast starts, the watcher may be unable to discover the live broadcast. Avoid adding personal browser cookies unless necessary and after considering the security implications.

## Operations

```bash
# NIP-46 bunker
systemctl --user status nak-bunker.service
systemctl --user restart nak-bunker.service
journalctl --user -u nak-bunker.service -f

# YouTube watcher
systemctl --user status youtube-nostr-watch.service
systemctl --user restart youtube-nostr-watch.service
journalctl --user -u youtube-nostr-watch.service -f

# Current local Nostr stream state
nostr-stream status
```

## Updating

```bash
cd nostr-stream
git pull
./install.sh
systemctl --user restart nak-bunker.service
systemctl --user restart youtube-nostr-watch.service
```

## Secret rotation

To rotate the automation client without changing the public Nostr identity:

1. generate a new client keypair;
2. replace `~/.config/nak/authorized-client.pub` with the new public key;
3. replace `nostr-client.cred` with an encrypted copy of the new private key;
4. restart `nak-bunker.service`;
5. test a manual start/stop.

Rotating `nostr-key.cred` changes the Nostr identity itself and therefore changes the author pubkey of future live events.

## License

MIT
