#!/bin/bash
# Install the "Plasma Glass" icon theme: Breeze Dark for system/tray icons,
# Colloid for application icons, plus the Plasma logo for the global menu and
# the dark glass launcher tile for the dock.
#
# Only Colloid icons whose names cannot collide with system icon names are
# linked: KDE falls back from a missing name to a shorter one (battery-040 ->
# battery, kdeconnect-tray -> kdeconnect), and linking the whole Colloid apps
# directory made the tray pick Colloid's opaque app tiles, which the panel
# then recolored into solid squares.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
DEST=~/.local/share/icons/plasma-glass
COLLOID=~/.local/share/icons/Colloid/apps/scalable

if [ ! -d "$COLLOID" ]; then
    echo "Colloid icon theme not found. Install it first:"
    echo "  git clone https://github.com/vinceliuice/Colloid-icon-theme"
    echo "  cd Colloid-icon-theme && ./install.sh -s default -t default"
    exit 1
fi

rm -rf "$DEST"
mkdir -p "$DEST"
cp -r "$HERE/plasma-glass/." "$DEST/"
mkdir -p "$DEST/colloid-apps"

python3 - "$(readlink -f "$COLLOID")" "$DEST/colloid-apps" <<'PY'
import os, re, sys
src, dst = sys.argv[1], sys.argv[2]
WHITELIST = {"systemsettings", "anydesk", "google-chrome", "chromium", "code", "visual-studio-code",
             "firefox", "thunderbird", "vlc", "gimp", "inkscape", "krita", "obs", "discord",
             "spotify", "slack", "zoom", "libreoffice-startcenter", "libreoffice-writer",
             "libreoffice-calc", "libreoffice-impress", "virtualbox", "steam",
             "utilities-terminal"}
n = 0
for f in os.listdir(src):
    if not f.endswith(".svg"):
        continue
    name = f[:-4]
    if re.match(r"^(org|com|io|net|dev|app|me|de|fr|info)\.", name) or name in WHITELIST:
        os.symlink(os.path.join(src, f), os.path.join(dst, f))
        n += 1
print(f"linked {n} Colloid app icons")
PY

/usr/lib/x86_64-linux-gnu/libexec/plasma-changeicons plasma-glass
echo "Icon theme applied. Set the dock launcher icon to 'plasma-glass-launcher'."
