// A free-floating KRunner has a full frame (rounded top corners) but opens in
// the middle of the screen, and it positions itself, so a window rule can't
// move it. Pin it just below the top panel, horizontally centred, every time
// it appears or resizes while you type.
var GAP = 24;   // px below the top of the work area

function place(w) {
    var area = workspace.clientArea(KWin.PlacementArea, w);
    var g = w.frameGeometry;
    var x = Math.round(area.x + (area.width - g.width) / 2);
    var y = Math.round(area.y + GAP);
    if (Math.round(g.x) !== x || Math.round(g.y) !== y)
        w.frameGeometry = { x: x, y: y, width: g.width, height: g.height };
}

function watch(w) {
    if (!w || w.resourceClass !== "krunner")
        return;
    place(w);
    w.frameGeometryChanged.connect(function () { place(w); });
}

workspace.windowAdded.connect(watch);
workspace.windowList().forEach(watch);
