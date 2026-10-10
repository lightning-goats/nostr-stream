# Native RTMP publishing to zap.stream

`rtmp-publish-metadata.patch` adds opt-in `meta publish` to the existing
nginx-rtmp module. It keeps the `@setDataFrame` envelope that zap.stream's
`rml_rtmp` receiver requires. `meta on`, `meta copy`, and `meta off` retain
their existing behavior. No extra running process or encoder is introduced.

The deployed module was built from arut/nginx-rtmp-module commit
`6c7719d0ba32e00b563ec70bd43dad11960fa9c4`, against Ubuntu nginx 1.28.3
(`nginx-dev` 1.28.3-2ubuntu1.11). Its path is
`/usr/local/lib/nginx/modules/ngx_rtmp_module.so`. The distribution module at
`/usr/lib/nginx/modules/ngx_rtmp_module.so` remains untouched.

To rebuild, obtain development headers for the exact installed nginx version
and OpenSSL/PCRE2. Copy `/usr/share/nginx/src` into a writable build directory.
Clone the pinned RTMP source, apply the patch with `patch -p1`, and configure
from the nginx source directory with:

```sh
./configure --with-compat --with-debug --with-threads \
  --with-http_ssl_module --with-http_v2_module --with-http_v3_module \
  --add-dynamic-module=/absolute/path/to/patched/nginx-rtmp-module
nice -n 19 make -f objs/Makefile modules -j1
```

Before deployment, test the actual built module without touching the live feed:

```sh
python3 nginx/check_metadata.py \
  --module /absolute/path/to/nginx-build/objs/ngx_rtmp_module.so \
  --fixture /absolute/path/to/existing-h264-aac-recording.flv
```

This uses existing nginx and FFmpeg on loopback ports 19451–19453, disposable
keys, and packet copying. It verifies normal metadata behavior and the new
publish envelope. No public streams or credentials are used. Stop if those
ports are already occupied. Then validate a private candidate production
configuration with `nginx -t -c PATH` before loading it.

Use `access_log off` in the RTMP block. Inside `application local`, use
`meta publish`, two native `push` directives from the private destinations
include, `push_reconnect 1s`, `idle_streams off`, `wait_key on`, and
`wait_video on`. Load the local module instead of loading both versions.

A graceful reload preserves existing publisher sessions. A short nginx restart
lets OBS reconnect to the new module/configuration without changing its scene
or encoder settings. Verify current public video and audio at both endpoints.
Rebuild after nginx upgrades; retain the distribution module and private
configuration backups for rollback. The deployed backups are root-only
`/etc/nginx/native-push-backup-*` directories. Retired forwarder files are
preserved there, not enabled as services.
