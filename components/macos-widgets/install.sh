#!/bin/bash
# Install Glass Widgets on macOS: the Plasma Glass desktop widgets (weather, markets,
# agenda) hosted by glasswidgets.py. No root needed.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
COMPONENTS=$(dirname "$HERE")
SUPPORT="$HOME/Library/Application Support/GlassWidgets"
APPDIR="$SUPPORT/app"
PY=$(brew --prefix python@3.13 2>/dev/null)/bin/python3.13
[ -x "$PY" ] || { brew install python@3.13; PY=$(brew --prefix python@3.13)/bin/python3.13; }

mkdir -p "$SUPPORT"
[ -x "$SUPPORT/venv/bin/python" ] || "$PY" -m venv "$SUPPORT/venv"
"$SUPPORT/venv/bin/pip" install -q --upgrade PyQt6 pyobjc-framework-Cocoa pyobjc-framework-Quartz \
    pyobjc-framework-EventKit

# the host, the stand-in QML modules, icons and the widget packages themselves
rm -rf "${APPDIR:?}"
mkdir -p "$APPDIR/widgets"
cp "$HERE/glasswidgets.py" "$HERE/MapPicker.qml" "$APPDIR/"
cp -R "$HERE/shim" "$HERE/icons" "$APPDIR/"
for pkg in "$COMPONENTS"/*-widget/org.plasmaglass.*; do
    cp -R "$pkg" "$APPDIR/widgets/"
done

# The bundle executable is a copy of the Python launcher itself (as for Glass VPN):
# macOS attributes windows and the Calendar permission to the bundle then.
# The Calendar permission is tied to the bundle's signature, so the bundle is only
# touched (and re-signed) when something in it really changed.
APP="$HOME/Applications/Glass Widgets.app"
SITE=$("$SUPPORT/venv/bin/python" -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")
STAGE=$(mktemp -d)
mkdir -p "$STAGE/MacOS" "$STAGE/py"
cp "$(brew --prefix python@3.13)/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python" \
   "$STAGE/MacOS/Glass Widgets"
cat > "$STAGE/py/sitecustomize.py" <<'EOF'
import os, runpy
if os.environ.get("GLASSWIDGETS_MAIN") and not os.environ.get("GLASSWIDGETS_RUNNING"):
    os.environ["GLASSWIDGETS_RUNNING"] = "1"
    runpy.run_path(os.environ["GLASSWIDGETS_MAIN"], run_name="__main__")
    raise SystemExit
EOF
cat > "$STAGE/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Glass Widgets</string>
  <key>CFBundleDisplayName</key><string>Glass Widgets</string>
  <key>CFBundleIdentifier</key><string>local.glasswidgets</string>
  <key>CFBundleExecutable</key><string>Glass Widgets</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSUIElement</key><true/>
  <key>NSCalendarsFullAccessUsageDescription</key><string>Виджет «Календарь» показывает ближайшие события из ваших календарей.</string>
  <key>NSCalendarsUsageDescription</key><string>Виджет «Календарь» показывает ближайшие события из ваших календарей.</string>
  <key>LSEnvironment</key>
  <dict>
    <key>PYTHONPATH</key><string>$APP/Contents/Resources/py:$SITE</string>
    <key>GLASSWIDGETS_MAIN</key><string>$APPDIR/glasswidgets.py</string>
  </dict>
</dict>
</plist>
EOF
CHANGED=0
put() {   # put <staged file> <bundle path>: copy only when different
    if ! cmp -s "$1" "$2"; then
        mkdir -p "$(dirname "$2")"
        cp "$1" "$2"
        CHANGED=1
    fi
}
# the launcher gets the signature embedded, so compare the source by checksum instead
SUM=$(shasum -a 256 "$STAGE/MacOS/Glass Widgets" | cut -d" " -f1)
if [ "$SUM" != "$(cat "$SUPPORT/launcher.sha256" 2>/dev/null)" ] || [ ! -f "$APP/Contents/MacOS/Glass Widgets" ]; then
    mkdir -p "$APP/Contents/MacOS"
    cp "$STAGE/MacOS/Glass Widgets" "$APP/Contents/MacOS/Glass Widgets"
    echo "$SUM" > "$SUPPORT/launcher.sha256"
    CHANGED=1
fi
put "$STAGE/py/sitecustomize.py" "$APP/Contents/Resources/py/sitecustomize.py"
put "$STAGE/Info.plist" "$APP/Contents/Info.plist"
if [ ! -f "$APP/Contents/Resources/AppIcon.icns" ] && [ -f "$HERE/make-icon.py" ]; then
    "$SUPPORT/venv/bin/python" "$HERE/make-icon.py" "$STAGE/AppIcon.iconset"
    iconutil -c icns "$STAGE/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
    CHANGED=1
fi
rm -rf "${STAGE:?}"
if [ $CHANGED = 1 ] || ! codesign -v "$APP" 2>/dev/null; then
    codesign --force --deep -s - "$APP" 2>/dev/null
    touch "$APP"
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP"
    echo "App bundle updated: macOS may ask for Calendar access again."
fi
echo "Installed. Open Glass Widgets (Spotlight); right-click a widget for its menu."
