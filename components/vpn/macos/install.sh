#!/bin/bash
# Install Glass VPN on macOS: Xray-core + sing-box + root helper into /opt/glassvpn,
# the menu bar app into ~/Library/Application Support/GlassVPN and ~/Applications.
# Asks for the password once (sudo).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
SB_VER=1.14.2
XRAY_VER=26.3.27
APPDIR="$HOME/Library/Application Support/GlassVPN"
PY=/usr/local/opt/python@3.13/bin/python3.13
ARCH=$(uname -m); [ "$ARCH" = x86_64 ] && SB_ARCH=amd64 XR_ARCH=64 || SB_ARCH=arm64 XR_ARCH=arm64-v8a

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
curl -fsSL -o "$TMP/sb.tgz" "https://github.com/SagerNet/sing-box/releases/download/v$SB_VER/sing-box-$SB_VER-darwin-$SB_ARCH.tar.gz"
curl -fsSL -o "$TMP/xray.zip" "https://github.com/XTLS/Xray-core/releases/download/v$XRAY_VER/Xray-macos-$XR_ARCH.zip"
tar xzf "$TMP/sb.tgz" -C "$TMP"
unzip -oq "$TMP/xray.zip" xray -d "$TMP"

# root-owned all the way down: sudo runs the helper and the helper runs sing-box as root
sudo install -d -o root -g wheel -m 755 /opt/glassvpn
sudo install -o root -g wheel -m 755 "$TMP/sing-box-$SB_VER-darwin-$SB_ARCH/sing-box" /opt/glassvpn/sing-box
sudo install -o root -g wheel -m 755 "$TMP/xray" /opt/glassvpn/xray
sudo install -o root -g wheel -m 755 "$HERE/glassvpn-helper" /opt/glassvpn/glassvpn-helper
sudo xattr -dr com.apple.quarantine /opt/glassvpn 2>/dev/null || true

# password-less start/stop of the tunnel for this user only
SUDOERS=$(mktemp)
echo "$USER ALL=(root) NOPASSWD: /opt/glassvpn/glassvpn-helper start *, /opt/glassvpn/glassvpn-helper stop" > "$SUDOERS"
sudo visudo -cf "$SUDOERS" >/dev/null
sudo install -o root -g wheel -m 440 "$SUDOERS" /etc/sudoers.d/glassvpn
rm -f "$SUDOERS"

sudo install -o root -g wheel -m 644 "$HERE/local.glassvpn.cleanup.plist" /Library/LaunchDaemons/local.glassvpn.cleanup.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/local.glassvpn.cleanup.plist 2>/dev/null || true

# the menu bar app
[ -x "$PY" ] || brew install python@3.13
mkdir -p "$APPDIR"; chmod 700 "$APPDIR"
[ -x "$APPDIR/venv/bin/python" ] || "$PY" -m venv "$APPDIR/venv"
"$APPDIR/venv/bin/pip" install -q --upgrade PyQt6 pyobjc-framework-Cocoa
install -m 755 "$HERE/../glassvpn.py" "$APPDIR/glassvpn.py"

# "Glass VPN" in Launchpad/Spotlight; LSUIElement keeps it out of the Dock.
# The bundle executable must be a copy of the Python launcher itself: macOS 26 drops the
# menu bar item of an app whose CFBundleExecutable is a script that execs Python.
# Python gets the app script through sitecustomize.py (LSEnvironment can set env vars,
# not arguments).
APP="$HOME/Applications/Glass VPN.app"
SITE=$("$APPDIR/venv/bin/python" -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")
rm -f "$APP/Contents/MacOS/glassvpn"   # the old script launcher
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/py"
cp "$(brew --prefix python@3.13)/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python" "$APP/Contents/MacOS/Glass VPN"
cat > "$APP/Contents/Resources/py/sitecustomize.py" <<'EOF'
import os, runpy
if os.environ.get("GLASSVPN_MAIN") and not os.environ.get("GLASSVPN_RUNNING"):
    os.environ["GLASSVPN_RUNNING"] = "1"   # child Pythons (none today) must not start the app again
    runpy.run_path(os.environ["GLASSVPN_MAIN"], run_name="__main__")
    raise SystemExit
EOF
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Glass VPN</string>
  <key>CFBundleIdentifier</key><string>local.glassvpn</string>
  <key>CFBundleExecutable</key><string>Glass VPN</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
  <key>LSEnvironment</key>
  <dict>
    <key>PYTHONPATH</key><string>$APP/Contents/Resources/py:$SITE</string>
    <key>GLASSVPN_MAIN</key><string>$APPDIR/glassvpn.py</string>
  </dict>
</dict>
</plist>
EOF
ICONSET=$(mktemp -d)/AppIcon.iconset
"$APPDIR/venv/bin/python" "$HERE/make-icon.py" "$ICONSET"
mkdir -p "$APP/Contents/Resources"
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
/usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string AppIcon" "$APP/Contents/Info.plist" 2>/dev/null || true
codesign --force --deep -s - "$APP" 2>/dev/null
touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP"
echo "Installed. Open Glass VPN (Spotlight) and add a subscription from its menu bar icon."
