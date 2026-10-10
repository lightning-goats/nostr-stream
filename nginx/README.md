# Current Fedora nginx + zap.stream deployment

The Fedora 44 deployment uses the distribution nginx 1.30.5 package and a
dynamic `ngx_rtmp_module` built against that exact nginx source version. The
build pins arut/nginx-rtmp-module at
`6c7719d0ba32e00b563ec70bd43dad11960fa9c4` and applies
`rtmp-publish-metadata.patch`. The `meta publish` mode emits the
`@setDataFrame` envelope required by zap.stream while leaving `meta on`,
`meta copy`, and `meta off` unchanged.

`./build-fedora-module.sh` downloads the matching nginx source, builds the
module, generates a disposable H.264/AAC fixture, and runs
`check_metadata.py` on loopback ports 19451–19453. The check stops if any test
port is occupied. Only after this passes does it install the module; an
existing module is copied beside it with a timestamped backup. Fedora build
prerequisites are `gcc`, `make`, `git`, `patch`, `pcre2-devel`,
`openssl-devel`, and `zlib-devel`. Rebuild after every nginx package upgrade.

The managed config is `nginx.conf.fedora`. It keeps ingest at
`127.0.0.1:1935`, exposes the RTMP status page only on `127.0.0.1:8089`, and
uses the `local` application. OBS publishes one already encoded stream at
`rtmp://127.0.0.1:1935/local/lightning-goats`; nginx sends the same packets to
YouTube and zap.stream. There is no FFmpeg relay or second video encode.
Destination credentials live in root-owned mode-600
`/etc/nginx/stream-destinations.conf`; the route updater validates each host,
uses atomic replacement, runs `nginx -t`, reloads nginx, and restores the old
file if validation or reload fails.

SELinux must allow nginx to bind TCP 1935 and 8089. The installer records the
previous SELinux port configuration before assigning `http_port_t`; it does
not change global TCP congestion control. The service waits for
`network-online.target`. The stock nginx config is backed up before the
managed config replaces it. The distro had no RTMP module at migration time.

## Local metadata validation

```sh
python3 nginx/check_metadata.py \
  --module /usr/lib64/nginx/modules/ngx_rtmp_module.so \
  --fixture /path/to/h264-aac-recording.flv
```

This test only relays packets between local test processes. It verifies that
normal metadata modes preserve their prior output and `meta publish` wraps
metadata in `@setDataFrame`. It does not use real ingest credentials or public
services.

## Rollback

Stop nginx, restore `/etc/nginx/nginx.conf.native-backup-*`, and restore the
timestamped module backup if one existed. If Fedora had no prior RTMP module,
remove the managed module and restore the distro nginx config. Remove the
systemd network-online drop-in and reload systemd. Restore the saved SELinux
port export if port labels need to be reverted. Start nginx only after
validating the restored configuration. Root-only backups must remain
unreadable by regular users because they may contain ingest keys.

## Legacy NVIDIA/Snap and YouTube/self-hosted HLS deployments

Earlier hosts used Snap OBS, NVIDIA PRIME/NVENC, a different nginx build and
YouTube-only watcher. Those paths are historical and are not loaded by the
Fedora installer. The YouTube-only watcher and self-hosted HLS settings remain
available for existing legacy deployments; do not use them alongside the
zap.stream watcher because they can publish a competing NIP-53 event.
