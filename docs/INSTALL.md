# Installing Plasma Glass

Plasma Glass is installed component by component on top of a working
MacTahoe Liquid KDE setup. Every step below was done on Kubuntu 26.04 with
Plasma 6.6.6 on Wayland. Back up `~/.config` before you start.

## 1. Prerequisites

```bash
sudo apt install git qt-style-kvantum librsvg2-bin imagemagick \
    cmake extra-cmake-modules kwin-dev libyaml-cpp-dev libxkbcommon-dev \
    libevdev-dev libinput-dev guake fonts-hack
```

### MacTahoe Liquid KDE (dark)

```bash
git clone --depth=1 https://github.com/lestercorderomurillo/macos-tahoe-liquid-kde ~/src/macos-tahoe-liquid-kde
cd ~/src/macos-tahoe-liquid-kde
sudo ./install --dark --no-wallpapers --no-firefox --no-plymouth \
    --no-nautilus --no-nautilus-bookmarks --no-apps --no-grub-modify
```

The installer needs `qmake6` and asks for confirmation; run it in a terminal.
It builds the *liquidglass* and KDE Rounded Corners KWin effects and restarts
Plasma.

### Colloid icons

```bash
git clone --depth=1 https://github.com/vinceliuice/Colloid-icon-theme ~/src/Colloid-icon-theme
cd ~/src/Colloid-icon-theme && ./install.sh -s default -t default
```

## 2. Glass effect patch

Makes glass edges crisp (no light rim on translucent popups), shapes the glass
to the popup's blur region, and keeps full-strength glass under inactive
windows.

```bash
cd ~/src/macos-tahoe-liquid-kde/src/offline/kwin-effects/acrylic-glass
patch -p1 < /path/to/plasma-glass/components/glass-effect/liquidglass.patch
# shader changes live in a Qt resource: force it to rebuild
touch src/liquidglass.qrc
rm -f ~/src/macos-tahoe-liquid-kde/build/kwin-effects/acrylic-glass/src/liquidglass_autogen/*/qrc_liquidglass.cpp
cmake --build ~/src/macos-tahoe-liquid-kde/build/kwin-effects/acrylic-glass -j4
sudo install -m 644 ~/src/macos-tahoe-liquid-kde/build/kwin-effects/acrylic-glass/src/liquidglass.so \
    /usr/lib/x86_64-linux-gnu/qt6/plugins/kwin/effects/plugins/liquidglass.so
```

Log out and back in: KWin loads a plugin library only at session start.

## 3. Window corners and outline

One radius and one outline everywhere. Apply the values from
[`reference/kwinrc-effects.ini`](../reference/kwinrc-effects.ini) (sections
`[Effect-liquidglass]`, `[Round-Corners]`, `[Effect-translucency]`) to
`~/.config/kwinrc`, then:

```bash
T=~/.local/share/aurorae/themes/MacTahoeLiquidKde-Dark/decoration.svg
cp "$T" "$T.orig"
python3 components/corner-radius/aurorae-radius.py "$T" 3   # near-square top corners
qdbus6 org.kde.KWin /KWin reconfigure
```

The theme SVG edits that remove doubled lines (window edge lines, popup edge
strips, tooltip rim) are described step by step in
[TUNING.md](TUNING.md#theme-svg-edits). Aurorae caches the decoration: switch the
window decoration to Breeze and back to reload it.

## 4. Icons

```bash
components/icons/install.sh
```

Then set the dock launcher's icon to `plasma-glass-launcher` in its settings.

## 5. Launcher with a category column

```bash
L=~/.local/share/plasma/plasmoids/org.kde.mac-tahoe-liquid-kde.launcher/contents/ui
cp -a "$L" "$L.orig"
cp components/launcher/*.qml "$L/"
systemctl --user restart plasma-plasmashell
```

## 6. Clock wallpaper

```bash
cp -r components/clock-wallpaper/local.clockwallpaper ~/.local/share/plasma/wallpapers/
```

Right-click the desktop → *Configure Desktop and Wallpaper* → *Clock Wallpaper*.
Pick the image, the clock position, font and weight there.

## 7. Adaptive top bar

Needs MacTahoe's Panel Colorizer widget on the top panel.

```bash
install -m 755 components/adaptive-panel/panel-adaptive-text.py ~/.local/bin/panel-adaptive-text
cp components/adaptive-panel/panel-adaptive-text.{service,path} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now panel-adaptive-text.path
~/.local/bin/panel-adaptive-text --force
```

## 8. Touchpad gestures

Build the InputActions KWin plugin:

```bash
git clone --recurse-submodules --shallow-submodules --depth=1 \
    https://github.com/InputActions/kwin ~/src/inputactions-kwin
cd ~/src/inputactions-kwin
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr
cmake --build build -j4 && sudo cmake --install build
kwriteconfig6 --file kwinrc --group Plugins --key kwin_gesturesEnabled true
```

Install the *App Cycle* script and the gesture config:

```bash
kpackagetool6 --type KWin/Script -i components/gestures/appcycle
kwriteconfig6 --file kwinrc --group Plugins --key appcycleEnabled true
mkdir -p ~/.config/inputactions
cp components/gestures/config.yaml ~/.config/inputactions/config.yaml
qdbus6 org.kde.KWin /KWin reconfigure
```

Also remove *Paste* from the desktop's middle-click action (right-click the
desktop → *Configure Desktop* → *Mouse Actions*): a three-finger touch counts as a
middle click and would paste the clipboard onto the desktop as sticky notes.

## 9. Drop-down Guake

```bash
components/guake/setup.sh
```

F12 is registered as a KDE global shortcut. On HP laptops the top row may send
media keys; set the key in *System Settings → Shortcuts → Guake Toggle* if F12
does nothing.

## 10. Chrome font-cache fix

Only if you use Google Chrome 154 or newer.

```bash
components/chrome-fontconfig-fix/install.sh
```

## 11. Two-entry boot menu (optional)

```bash
sudo install -m 755 components/grub/09_two_entries /etc/grub.d/09_two_entries
sudo chmod -x /etc/grub.d/{10_linux,10_linux_zfs,20_linux_xen,20_memtest86+,30_os-prober,30_uefi-firmware,35_fwupd}
sudo sed -i -E 's/^GRUB_TIMEOUT_STYLE=.*/GRUB_TIMEOUT_STYLE=menu/; s/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=5/' /etc/default/grub
sudo update-grub
```

To restore the stock menu: `sudo chmod +x` the generators above, remove
`09_two_entries`, run `sudo update-grub`.
