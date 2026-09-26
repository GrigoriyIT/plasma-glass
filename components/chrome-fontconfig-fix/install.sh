#!/bin/bash
# Google Chrome 154+ ships its own fontconfig that writes cache-12 files into
# ~/.cache/fontconfig and turns the system's cache-9 files into symlinks to
# them. The system fontconfig then reads data in a format it doesn't know and
# every Qt/KDE app crashes on the first text it draws (plasmashell, Konsole…).
# Give Chrome its own cache directory and launch it through that config.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p ~/.config/chrome-fontconfig ~/.local/share/applications
cp "$HERE/fonts.conf" ~/.config/chrome-fontconfig/fonts.conf
SRC=/usr/share/applications/google-chrome.desktop
[ -f "$SRC" ] || { echo "google-chrome.desktop not found — is Chrome installed?"; exit 1; }
sed -E "s#^Exec=/usr/bin/google-chrome-stable#Exec=env FONTCONFIG_FILE=$HOME/.config/chrome-fontconfig/fonts.conf /usr/bin/google-chrome-stable#" \
    "$SRC" > ~/.local/share/applications/google-chrome.desktop
update-desktop-database ~/.local/share/applications 2>/dev/null || true
# Repair a cache that Chrome may already have poisoned.
if [ -n "$(find ~/.cache/fontconfig -maxdepth 1 -type l 2>/dev/null)" ]; then
    rm -rf ~/.cache/fontconfig && fc-cache -f >/dev/null
fi
echo "Done. Restart Chrome from the menu or the dock."
