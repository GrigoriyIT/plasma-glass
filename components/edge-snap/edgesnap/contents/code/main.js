// KWin tiles a dragged window only when the cursor is within 20 px of a side
// edge (hardcoded). This widens that to SIDE px: when a move ends there,
// the window is tiled to the left or right half. KWin's own zone (and its
// preview outline) still handles the last 20 px and the corners.
var SIDE = 80;            // px from the side edge that count as "snap to half"
var KWIN_ZONE = 20;       // KWin's built-in zone; leave it to KWin

var moving = {};

function watch(w) {
    if (!w || !w.normalWindow)
        return;
    w.interactiveMoveResizeStarted.connect(function () {
        // only plain moves, not resizes
        moving[w.internalId] = w.move;
    });
    w.interactiveMoveResizeFinished.connect(function () {
        var wasMove = moving[w.internalId];
        delete moving[w.internalId];
        if (!wasMove)
            return;
        var c = workspace.cursorPos;
        var area = workspace.clientArea(KWin.MaximizeArea, w);
        if (c.y < area.y || c.y > area.y + area.height)
            return;
        var fromLeft = c.x - area.x;
        var fromRight = area.x + area.width - c.x;
        if (fromLeft > KWIN_ZONE && fromLeft <= SIDE) {
            workspace.activeWindow = w;
            workspace.slotWindowQuickTileLeft();
        } else if (fromRight > KWIN_ZONE && fromRight <= SIDE) {
            workspace.activeWindow = w;
            workspace.slotWindowQuickTileRight();
        }
    });
}

workspace.windowAdded.connect(watch);
workspace.windowList().forEach(watch);
