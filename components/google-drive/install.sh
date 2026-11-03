#!/bin/bash
# Google Drive as a folder: rclone mount at ~/GoogleDrive, started at login,
# with a "Google Диск" place in Dolphin.
#   ./install.sh                         use rclone's built-in client id
#   ./install.sh CLIENT_ID CLIENT_SECRET use your own Google Cloud client (see README)
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
REMOTE=gdrive

# rclone from rclone.org: the Ubuntu package is years behind.
need=1.70
have=$(rclone version 2>/dev/null | awk 'NR==1{sub(/^v/,"",$2); print $2}')
if [ -z "$have" ] || [ "$(printf '%s\n' "$need" "$have" | sort -V | head -1)" != "$need" ]; then
    TMP=$(mktemp -d)
    curl -fsSL -o "$TMP/rclone.deb" https://downloads.rclone.org/rclone-current-linux-amd64.deb
    sudo dpkg -i "$TMP/rclone.deb"
    rm -rf "$TMP"
fi
command -v fusermount3 >/dev/null || sudo apt-get install -y fuse3

# Sign in to Google (opens the browser) unless the remote is already set up.
if ! rclone listremotes | grep -qx "$REMOTE:"; then
    if [ -n "$2" ]; then
        rclone config create "$REMOTE" drive scope=drive client_id="$1" client_secret="$2"
    else
        rclone config create "$REMOTE" drive scope=drive
    fi
elif [ -n "$2" ]; then
    rclone config update "$REMOTE" client_id="$1" client_secret="$2"
    rclone config reconnect "$REMOTE:"
fi
chmod 600 ~/.config/rclone/rclone.conf

install -Dm 644 "$HERE/rclone-gdrive.service" ~/.config/systemd/user/rclone-gdrive.service
systemctl --user daemon-reload
systemctl --user enable rclone-gdrive.service
systemctl --user restart rclone-gdrive.service

# Dolphin place, next to the other folders.
python3 - <<'PY'
import os, re, uuid
p = os.path.expanduser("~/.local/share/user-places.xbel")
href = "file://" + os.path.expanduser("~/GoogleDrive")
s = open(p).read() if os.path.exists(p) else ""
if s and href not in s:
    entry = (' <bookmark href="%s">\n  <title>Google Диск</title>\n  <info>\n'
             '   <metadata owner="http://freedesktop.org">\n    <bookmark:icon name="folder-gdrive"/>\n   </metadata>\n'
             '   <metadata owner="http://www.kde.org">\n    <ID>%s</ID>\n    <isSystemItem>false</isSystemItem>\n   </metadata>\n'
             '  </info>\n </bookmark>\n') % (href, uuid.uuid4().hex)
    last = None
    for m in re.finditer(r'<bookmark href="file://[^"]*">.*?</bookmark>\n', s, re.S):
        last = m
    pos = last.end() if last else s.rindex("</xbel>")
    open(p, "w").write(s[:pos] + entry + s[pos:])
PY
echo "Google Drive is mounted at ~/GoogleDrive."
