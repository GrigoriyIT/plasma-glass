# Plasma Glass

A frosted-glass desktop for KDE Plasma 6 on Kubuntu: Kubuntu's own identity (Breeze
icons, the Plasma logo) with Mac-style ergonomics — a top menu bar, a dock, touchpad
gestures and a drop-down terminal.

[Русская версия](README.ru.md)

## 📲 Glass VPN for Android and Android TV

The VPN client from this repository: VLESS (Reality, gRPC, XHTTP, ML-KEM), Russian sites
direct, everything else through the VPN. Phones and TVs on Android 9 or newer.

**[⬇ Download for phones](https://github.com/GrigoriyIT/plasma-glass/releases/latest/download/GlassVPN-arm64.apk)** · **[⬇ Download for TVs](https://github.com/GrigoriyIT/plasma-glass/releases/latest/download/GlassVPN-armv7.apk)** · [all versions and what's new](https://github.com/GrigoriyIT/plasma-glass/releases/latest)

The links always point to the latest version. The TV build is for 32-bit systems (e.g. Xiaomi
Mi TV 4S/4A); it also installs on phones that refuse the phone build. Details:
[Glass VPN](components/vpn/README.md#android).

| ![Glass VPN on a TV: the glass orb button, time connected and the server list](docs/images/glassvpn-tv.png) | ![Glass VPN on a phone](docs/images/glassvpn-phone.png) |
|---|---|

![Frosted-glass desktop: active Dolphin window, inactive Konsole behind it, adaptive top bar and dock](docs/images/desktop.jpg)

| ![Launcher with the category column](docs/images/launcher.jpg) | ![Drop-down Guake terminal](docs/images/guake.jpg) |
|---|---|

## What you get

- **Frosted glass everywhere, one outline.** Windows, dialogs and popups share one
  11 px radius and a single 1 px light hairline, like macOS. No doubled corners,
  no light leaks at the edges.
- **Active vs. inactive windows.** The active window keeps a glass sidebar and a
  near-solid content area for focus; inactive windows turn into strongly
  transparent frosted glass.
- **Adaptive top bar.** A fully transparent bar whose text and monochrome icons
  switch between dark and light to match the wallpaper under it.
- **Clock wallpaper.** Any image with a large centred clock and date; it redraws
  once a minute, so it costs almost nothing.
- **Touchpad gestures.** Three fingers left/right switch applications, up shows all
  windows, down shows the windows of the current application.
- **Drop-down terminal.** Guake slides strictly vertically from the top edge on F12,
  one third of the screen, with no dock icon and no busy cursor.
- **Launcher with a category sidebar.** Every category is visible and readable in full.
- **Fixes found along the way**: Chrome 154 poisoning the system font cache (which
  crashes Plasma), a two-entry Kubuntu/Windows boot menu.

## Status

Experimental. Built and tuned on one machine:

| | |
|---|---|
| Distribution | Kubuntu 26.04 |
| Plasma / KWin | 6.6.6, Wayland |
| Display | 1920×1080, scale 100% |

There is no one-shot installer yet: components are installed one by one, see
[docs/INSTALL.md](docs/INSTALL.md). Two components are compiled against the running
KWin (the patched glass effect and the gesture plugin) and must be rebuilt after a
KWin upgrade.

## Components

| Path | What it does |
|---|---|
| [`components/glass-effect`](components/glass-effect) | Patch for the MacTahoe *liquidglass* KWin effect: crisp glass edges, glass shaped to the popup's blur region and rounded like its frame, full-strength glass under inactive windows |
| [`components/corner-radius`](components/corner-radius) | Rewrites corner arcs in Aurorae / Plasma theme SVGs |
| [`components/icons`](components/icons) | *Plasma Glass* icon theme (Breeze Dark + Colloid apps + launcher tile) |
| [`components/launcher`](components/launcher) | MacTahoe launcher QML with a left category column |
| [`components/clock-wallpaper`](components/clock-wallpaper) | Wallpaper plugin: image + large clock |
| [`components/adaptive-panel`](components/adaptive-panel) | Top bar text/icon colour follows the wallpaper |
| [`components/gestures`](components/gestures) | Touchpad gestures (InputActions config + *App Cycle* KWin script) |
| [`components/edge-snap`](components/edge-snap) | Wider side-edge zone for half-screen snapping, smaller quarter-tile corners |
| [`components/guake`](components/guake) | Drop-down Guake with a vertical slide effect |
| [`components/chrome-fontconfig-fix`](components/chrome-fontconfig-fix) | Keeps Chrome from breaking the system font cache |
| [`components/vpn`](components/vpn) | *Glass VPN*: tray client for VLESS subscriptions on sing-box, Russian sites and LAN direct |
| [`components/grub`](components/grub) | Boot menu with exactly two entries: Kubuntu and Windows |
| [`reference`](reference) | The exact KWin, Kvantum and colour settings of the tuned system |

Every setting and the reason behind it: [docs/TUNING.md](docs/TUNING.md).
Problems and fixes: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Built on

Plasma Glass is a layer on top of other free projects and does not bundle them.
See [CREDITS.md](CREDITS.md).

- [MacTahoe Liquid KDE](https://github.com/lestercorderomurillo/macos-tahoe-liquid-kde) — base theme, Kvantum style, glass effect
- [Colloid icon theme](https://github.com/vinceliuice/Colloid-icon-theme) — application icons
- [InputActions](https://github.com/InputActions/kwin) — touchpad gestures
- [Guake](https://github.com/Guake/guake) — drop-down terminal

## License and trademarks

GPL-3.0-or-later, see [LICENSE](LICENSE).

Plasma Glass is not affiliated with Apple, Canonical or KDE e.V. "Kubuntu" is a
trademark of Canonical Ltd.; "macOS" is a trademark of Apple Inc. No Apple fonts,
logos or artwork are included. The MacTahoe installer can download the SF Pro fonts;
those are licensed by Apple for its own platforms only — do not redistribute a system
that ships them.
