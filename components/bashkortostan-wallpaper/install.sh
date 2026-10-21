#!/bin/bash
# Install the Bashkortostan wallpaper and switch every desktop to it.
# The previous desktop config is saved first; restore it with
#   ./install.sh --restore
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
ID=org.plasmaglass.bashkortostan
RC=~/.config/plasma-org.kde.plasma.desktop-appletsrc
BACKUP=~/.local/state/bashkortostan-wallpaper/appletsrc.before

if [ "$1" = "--restore" ]; then
    [ -f "$BACKUP" ] || { echo "no backup at $BACKUP"; exit 1; }
    # Put the old wallpaper plugin back on every desktop (only that key changes).
    python3 - "$BACKUP" <<'PY' > /tmp/bashkortostan-restore.js
import configparser, json, re, sys
cp = configparser.RawConfigParser(strict=False, interpolation=None); cp.optionxform = str
cp.read(sys.argv[1])
old = {sec.split("][")[1]: cp.get(sec, "wallpaperplugin") for sec in cp.sections()
       if re.fullmatch(r"Containments\]\[\d+", sec) and cp.has_option(sec, "wallpaperplugin")}
print("var old = %s; desktops().forEach(function (d) { if (old[d.id]) d.wallpaperPlugin = old[d.id]; });" % json.dumps(old))
PY
    qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "$(cat /tmp/bashkortostan-restore.js)"
    rm -f /tmp/bashkortostan-restore.js
    echo "Previous wallpaper restored."
    exit 0
fi

mkdir -p "$(dirname "$BACKUP")"
[ -f "$BACKUP" ] || cp "$RC" "$BACKUP"

PKG=$(mktemp -d)
cp -r "$HERE/metadata.json" "$HERE/contents" "$PKG/"
kpackagetool6 -t Plasma/Wallpaper -u "$PKG" >/dev/null 2>&1 || kpackagetool6 -t Plasma/Wallpaper -i "$PKG"
rm -rf "$PKG"

# The point for the sun and the weather: the weather widget's, if it is set up.
read -r LAT LON < <(python3 - "$RC" <<'PY'
import configparser, sys
cp = configparser.RawConfigParser(strict=False, interpolation=None); cp.optionxform = str
cp.read(sys.argv[1])
for sec in cp.sections():
    if cp.has_option(sec, "latitude") and cp.has_option(sec, "longitude"):
        print(cp.get(sec, "latitude"), cp.get(sec, "longitude")); break
else:
    print("54.7558 56.005")   # Ufa
PY
)

qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "
desktops().forEach(function (d) {
    d.wallpaperPlugin = '$ID';
    d.currentConfigGroup = ['Wallpaper', '$ID', 'General'];
    d.writeConfig('Latitude', $LAT);
    d.writeConfig('Longitude', $LON);
});"
echo "Bashkortostan wallpaper on every desktop (point $LAT, $LON)."
