# Tuning reference

The values of the tuned system and why each one is set. The raw settings are in
[`reference/`](../reference).

## Corners: one radius, one outline

Every corner must be drawn by one outline at one radius. When two layers draw an
edge at slightly different radii, the corner looks doubled or shows a light gap.

| Layer | Setting | Value |
|---|---|---|
| Glass effect | `WindowCornerRadius`, `BottomCornerRadius`, `DialogCornerRadius`, `PopupCornerRadius` | 11 |
| Glass effect | `DockCornerRadius` | 16 (matches the dock SVG) |
| Glass effect | `MenuCornerRadius` | 9 (Kvantum menus) |
| Glass effect | `TooltipCornerRadius` | 11 |
| Rounded Corners | `Size`, `InactiveCornerRadius` | 11 |
| Rounded Corners | `OutlineThickness`, `InactiveOutlineThickness` | 1 |
| Rounded Corners | `OutlineColor` / alpha | white, 50 active / 28 inactive |
| Rounded Corners | second and outer outlines | 0 |
| Rounded Corners | `Exclusions` | `plasmashell,org.kde.plasmashell,krunner,org.kde.krunner` |
| Aurorae decoration | top corner arcs | 3 px (clipping is left to Rounded Corners) |

Why 11 and not smaller: Plasma applet popups (battery, calendar…) use the theme's
dialog background, whose corners are 11 px. Shrinking that SVG breaks its frame
tiles, so everything else is set to 11 instead.

## Glass

| Setting | Value | Why |
|---|---|---|
| `BlurStrength` | 7 | 3.5 left sharp details visible through windows |
| `HighlightStrength` | 0 | the glass rim read as a light leak on translucent popups |
| `IridescenceStrength`, `RgbDriftStrength`, `MagnifyGlassStrength`, `RefractionWidth` | 0 | coloured glare wedges at corners |
| Translucency effect, `Inactive` | 55 | inactive windows become frosted glass |

The glass patch keeps the glass at full strength under inactive windows; without
it the Translucency effect fades the blur too and the window turns into a sharp
see-through ghost.

## Active and inactive windows

Kvantum palette (see [`reference/kvantum-palette.ini`](../reference/kvantum-palette.ini)):

- `window.color` `#2424248C` — title bar and sidebars stay glass.
- `base.color` `#1e1e1eF0`, `alt.base.color` `#262626F0` — content views are near-solid.

KDE applications ignore Kvantum's *inactive* palette; inactive windows are handled
by the Translucency effect and by `[ColorEffects:Inactive]` in `kdeglobals`
(contrast fade 0.55, see [`reference/kdeglobals-inactive.ini`](../reference/kdeglobals-inactive.ini)).

## Theme SVG edits

All files are under `~/.local/share/aurorae/themes/MacTahoeLiquidKde-Dark/` and
`~/.local/share/plasma/desktoptheme/MacTahoeLiquidKde-Dark/`. Keep a copy of each
original.

1. **Window decoration** (`decoration.svg`)
   - Top corner arcs → 3 px with `components/corner-radius/aurorae-radius.py decoration.svg 3`.
   - Hide the decoration's own edge lines: set `opacity:0` on every element whose
     style has `fill:#000000` without a gradient, and on white lines with
     `opacity:0.1` or `0.05`. The 1 px outline now comes from Rounded Corners only.
   - Inactive title bar: `fill:#242424` → `fill:#333333`, black outlines
     `opacity:0.75` → `0.35`.
   - `MacTahoeLiquidKde-Darkrc`: `InactiveTextColor=100,100,100`.
2. **Popups** (`dialogs/background.svgz`)
   - Keep the original corners (11 px).
   - Edge strips `path1` and `rect972`: `opacity:0.55;fill:#2a2a2a` →
     `opacity:0.2;fill:#ffffff` — a light hairline that matches the windows.
     Do not hide them: without them a light ring of blurred glass shows around
     popups.
3. **Popup shadow** (`dialogs/background.svgz`): solid shadow pieces `path962` and `rect986` (`opacity:0.55;fill:#2a2a2a`) → `opacity:0`. They drew a hard dark square outside every popup's rounded frame; the soft gradient shadow stays.
4. **Tooltips** (`widgets/tooltip.svgz`): `opacity:0.55;fill:#ffffff` → `opacity:0.2;fill:#ffffff`.
5. **Kvantum menus** (`~/.config/Kvantum/mac-tahoe-liquid-kdeDark/mac-tahoe-liquid-kdeDark.svg`):
   with `menu_shadow_depth=4` the menu edge is drawn by `menu-shadow-*`, and every
   side and corner reuses `menu-shadow-top` and `menu-shadow-topright`. Their white
   1 px line inside the black outline — `path3581` and the corner arc
   `d="m 109,507 v 1 a 7.9999555…"` — `opacity:0.1` → `opacity:0.4`. On the
   translucent menu that gives the same brightness as the window hairline
   (≈ 90 on a 45 fill, the window gives 91 on 51).

After an Aurorae change, switch the decoration to Breeze and back; after a Plasma
theme change, delete `~/.cache/plasma_theme_*.kcache` and restart plasmashell.
Kvantum changes apply to applications started afterwards.

## Top bar

Panel Colorizer: panel background disabled (fully transparent), no text shadow,
foreground colour and forced icon recolouring driven by
`panel-adaptive-text`. The global menu is recoloured every 150 ms because its
entries are rebuilt on every window switch.

## Gestures

`~/.config/inputactions/config.yaml`: `motion_threshold_3: 3`, `angle_tolerance: 30`,
actions fire `on: begin`.
