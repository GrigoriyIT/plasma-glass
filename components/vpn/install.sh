#!/bin/bash
# Install Glass VPN: sing-box (with TUN capabilities) + the tray client.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)

if ! command -v sing-box >/dev/null; then
    TAG=$(curl -fsSL https://api.github.com/repos/SagerNet/sing-box/releases/latest |
          python3 -c "import sys,json;print(json.load(sys.stdin)['tag_name'])")
    V=${TAG#v}
    TMP=$(mktemp -d)
    curl -fsSL -o "$TMP/sb.tgz" "https://github.com/SagerNet/sing-box/releases/download/$TAG/sing-box-$V-linux-amd64.tar.gz"
    tar xzf "$TMP/sb.tgz" -C "$TMP"
    sudo install -m 755 "$TMP/sing-box-$V-linux-amd64/sing-box" /usr/local/bin/sing-box
    rm -rf "$TMP"
fi
# TUN without running anything as root
sudo setcap cap_net_admin,cap_net_bind_service,cap_net_raw=+ep "$(command -v sing-box)"

install -Dm 755 "$HERE/glassvpn.py" ~/.local/bin/glassvpn
install -Dm 644 "$HERE/glassvpn.desktop" ~/.local/share/applications/glassvpn.desktop
install -Dm 644 "$HERE/glassvpn.desktop" ~/.config/autostart/glassvpn.desktop
echo "Installed. Start it from the menu (Glass VPN) and add a subscription from the tray icon."
