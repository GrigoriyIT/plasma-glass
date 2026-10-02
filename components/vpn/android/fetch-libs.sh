#!/bin/bash
# Download the two native cores into app/libs, pinned and checksummed.
set -e
LIBS=$(cd "$(dirname "$0")" && pwd)/app/libs
mkdir -p "$LIBS"

get() {  # url file sha256
    if [ -f "$LIBS/$2" ] && shasum -a 256 "$LIBS/$2" | grep -q "^$3 "; then
        return
    fi
    curl -fL --progress-bar -o "$LIBS/$2.part" "$1"
    if ! shasum -a 256 "$LIBS/$2.part" | grep -q "^$3 "; then
        echo "checksum mismatch: $2" >&2
        rm -f "$LIBS/$2.part"
        exit 1
    fi
    mv "$LIBS/$2.part" "$LIBS/$2"
}

# Xray-core for Android (gomobile), LGPL-3.0 wrapper around MPL-2.0 Xray
get https://github.com/2dust/AndroidLibXrayLite/releases/download/v26.9.30/libv2ray.aar \
    libv2ray.aar cf71680b776b9ca583747ba652f816b047a655eab875d8951e6141636d88bbd6
# TUN -> SOCKS5, MIT
get https://github.com/heiher/hev-socks5-tunnel/releases/download/2.18.0/hev-socks5-tunnel.aar \
    hev-socks5-tunnel.aar 15ec8ed121663b562c99caa5bb602d1009f24e5b09e733438b81988f12feaaab
