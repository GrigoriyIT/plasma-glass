# Wide edge snap

KWin tiles a dragged window to half the screen only when the cursor is within
20 px of a side edge (hardcoded in `Window::checkQuickTilingMaximizationZones`),
and gives a quarter of each side edge to the corner (quarter-tile) zones.

- `edgesnap` KWin script: dropping a window within 80 px of a side edge tiles it
  to that half. KWin's own preview outline still appears only in the last 20 px.
- Smaller corner zones, so quarter tiling needs a deliberate move into the corner:

```bash
kwriteconfig6 --file kwinrc --group Windows --key ElectricBorderCornerRatio 0.06
kpackagetool6 --type KWin/Script -i components/edge-snap/edgesnap
kwriteconfig6 --file kwinrc --group Plugins --key edgesnapEnabled true
qdbus6 org.kde.KWin /KWin reconfigure
```

`SIDE` at the top of `contents/code/main.js` sets the width of the zone.
