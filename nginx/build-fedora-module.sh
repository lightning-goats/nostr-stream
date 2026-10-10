#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MODULE_REPO=https://github.com/arut/nginx-rtmp-module.git
MODULE_COMMIT=6c7719d0ba32e00b563ec70bd43dad11960fa9c4
NGINX_VERSION="$(nginx -v 2>&1 | sed -E 's#^.*/([0-9]+\.[0-9]+\.[0-9]+)$#\1#')"
[[ "$NGINX_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
    echo "Could not determine installed nginx version." >&2
    exit 1
}
need() { command -v "$1" >/dev/null 2>&1 || { echo "Required command not found: $1" >&2; exit 1; }; }
for command in nginx curl tar git patch make cc ffmpeg python3 sudo; do need "$command"; done

BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nostr-stream-rtmp.XXXXXXXX")"
echo "Building RTMP module for nginx $NGINX_VERSION in $BUILD_DIR"
curl --fail --location --silent --show-error \
    "https://nginx.org/download/nginx-${NGINX_VERSION}.tar.gz" \
    -o "$BUILD_DIR/nginx.tar.gz"
tar -xzf "$BUILD_DIR/nginx.tar.gz" -C "$BUILD_DIR"
git clone --quiet "$MODULE_REPO" "$BUILD_DIR/ngx_rtmp"
git -C "$BUILD_DIR/ngx_rtmp" checkout --quiet "$MODULE_COMMIT"
patch --directory="$BUILD_DIR/ngx_rtmp" -p1 < "$ROOT/nginx/rtmp-publish-metadata.patch"
cd "$BUILD_DIR/nginx-${NGINX_VERSION}"
./configure --with-compat --with-debug --with-threads \
    --with-http_ssl_module --with-http_v2_module --with-http_v3_module \
    --add-dynamic-module="$BUILD_DIR/ngx_rtmp" > "$BUILD_DIR/configure.log"
make -f objs/Makefile modules -j"$(getconf _NPROCESSORS_ONLN)"

ffmpeg -hide_banner -loglevel error -y \
    -f lavfi -i testsrc2=size=640x360:rate=30 \
    -f lavfi -i sine=frequency=1000:sample_rate=48000 -t 3 \
    -c:v libx264 -profile:v high -pix_fmt yuv420p -g 60 -c:a aac \
    -f flv "$BUILD_DIR/fixture.flv"
python3 "$ROOT/nginx/check_metadata.py" \
    --module "$PWD/objs/ngx_rtmp_module.so" --fixture "$BUILD_DIR/fixture.flv"

target=/usr/lib64/nginx/modules/ngx_rtmp_module.so
sudo install -d -o root -g root -m 0755 "$(dirname "$target")"
if sudo test -e "$target"; then
    sudo cp -a "$target" "${target}.backup-$(date +%Y%m%d%H%M%S)"
fi
sudo install -o root -g root -m 0755 "$PWD/objs/ngx_rtmp_module.so" "$target"
echo "Installed tested RTMP module at $target"
