# Current Fedora nginx + zap.stream deployment

The Fedora 44 deployment uses the distribution nginx 1.30.5 package and a
dynamic `ngx_rtmp_module` built against that exact nginx source version. The
build pins arut/nginx-rtmp-module at
`6c7719d0ba32e00b563ec70bd43dad11960fa9c4` and applies
`rtmp-publish-metadata.patch` and `rtmp-relay-reconnect.patch`. The
`meta publish` mode emits the
`@setDataFrame` envelope required by zap.stream while leaving `meta on`,
`meta copy`, and `meta off` unchanged.

`./build-fedora-module.sh` downloads the matching nginx source, builds the
module, generates a disposable H.264/AAC fixture, and runs
`check_metadata.py` on loopback ports 19451–19453 and
`check_relay_failure.py` on port 19454. The checks stop if their test ports
are occupied. The second test forces a native push to refuse connections and
checks that nginx keeps the ingest worker alive. `--check-only` validates a
candidate without replacing the installed module. The normal build installs
only after both checks pass; an
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

SELinux must allow nginx to bind the loopback listeners on TCP 1935 and 8089.
Outbound RTMP also needs a `name_connect` rule for TCP 1935. Fedora's stock
policy labels port 1935 for unrelated services and leaves
`httpd_can_network_connect` disabled. Do not enable that broad boolean for this
deployment. Compile `lightning_goats_rtmp.te`, install the resulting policy
module, and label TCP 1935 as `lightning_goats_rtmp_port_t`; this allows nginx's
`httpd_t` domain to connect only to that destination port. DNS already works
through the host resolver. The policy source is tested with `checkmodule` and
`semodule_package` by `tests/test_nginx_selinux_policy.py`.

For a manual install, first record local overrides with
`sudo semanage port -l -C`, then run:

```sh
checkmodule -M -m -o /tmp/lightning_goats_rtmp.mod nginx/lightning_goats_rtmp.te
semodule_package -o /tmp/lightning_goats_rtmp.pp -m /tmp/lightning_goats_rtmp.mod
sudo semodule -i /tmp/lightning_goats_rtmp.pp
sudo semanage port -m -t lightning_goats_rtmp_port_t -p tcp 1935
```

To roll back, remove the local TCP 1935 port override with
`sudo semanage port -d -p tcp 1935` (then restore any recorded local override)
and remove the policy module with
`sudo semodule -r lightning_goats_rtmp`. This restores Fedora's policy port
labels. The service waits for `network-online.target`. The stock nginx config
is backed up before the managed config replaces it. The distro had no RTMP
module at migration time. This setup does not change global TCP congestion
control.

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
