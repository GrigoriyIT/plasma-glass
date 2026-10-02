# Credits

Plasma Glass builds on these projects. They are dependencies, not bundled code,
except where a file below says it is derived from one of them.

| Project | License | Used for |
|---|---|---|
| [MacTahoe Liquid KDE](https://github.com/lestercorderomurillo/macos-tahoe-liquid-kde) by Lester Cordero Murillo | GPL-3.0 | Base Plasma/Aurorae/Kvantum theme, the *liquidglass* KWin effect, the launcher and dock plasmoids |
| [Colloid icon theme](https://github.com/vinceliuice/Colloid-icon-theme) by Vince Liuice | GPL-3.0 | Application icons |
| [Breeze icons](https://invent.kde.org/frameworks/breeze-icons) by KDE | LGPL-3.0 | System and tray icons, the Plasma logo used for the global menu |
| [InputActions](https://github.com/InputActions/kwin) by taj-ny | GPL-3.0 | Touchpad gesture plugin for KWin |
| [KDE Rounded Corners](https://github.com/matinlotfali/KDE-Rounded-Corners) by Matin Lotfaliei | GPL-3.0 | Corner clipping and the 1 px window outline (installed by MacTahoe) |
| [sing-box](https://github.com/SagerNet/sing-box) by SagerNet | GPL-3.0-or-later | VPN core for Glass VPN (downloaded by its installer) |
| [Xray-core](https://github.com/XTLS/Xray-core) by XTLS | MPL-2.0 | VLESS client for Glass VPN (downloaded by its installer) |
| [AndroidLibXrayLite](https://github.com/2dust/AndroidLibXrayLite) by 2dust | LGPL-3.0 | Xray-core packaged for Android (Glass VPN for Android, downloaded by `fetch-libs.sh`) |
| [hev-socks5-tunnel](https://github.com/heiher/hev-socks5-tunnel) by heiher | MIT | TUN → SOCKS5 for Glass VPN for Android (downloaded by `fetch-libs.sh`) |
| [Guake](https://github.com/Guake/guake) | GPL-2.0-or-later | Drop-down terminal |
| [Panel Colorizer](https://github.com/luisbocanegra/plasma-panel-colorizer) by Luis Bocanegra | GPL-3.0 | Top bar transparency and recolouring (installed by MacTahoe) |

## Files derived from other projects

- `components/glass-effect/liquidglass.patch` — changes to MacTahoe's *liquidglass* effect (GPL-3.0).
- `components/launcher/*.qml` — modified copies of MacTahoe's launcher plasmoid (GPL-3.0).
- `components/icons/plasma-glass/scalable/places/start-here-kde-symbolic.svg` — Breeze icon (LGPL-3.0).
- `components/icons/plasma-glass/tray/places/user-trash*.svg` — Breeze icons (LGPL-3.0).
- `components/icons/plasma-glass/dock/places/user-trash*.svg`, `components/icons/extras/trash-tahoe*.svg`, `components/icons/extras/launcher-tahoe.svg` — MacTahoe icons (GPL-3.0).
- `components/icons/extras/trash-colloid*.svg`, `components/icons/extras/launcher-plasma-colloid.svg` — Colloid icons (GPL-3.0).

Everything else is original to this project.
