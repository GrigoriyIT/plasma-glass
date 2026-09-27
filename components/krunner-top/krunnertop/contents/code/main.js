// A free-floating KRunner has a full frame (rounded top corners) but opens in
// the middle of the screen, and it positions itself, so a window rule can't
// move it. Pin it just below the top panel, horizontally centred, every time
// it appears or resizes while you type.
var GAP = 24;   // px below the top of the work area
// The theme's dialog frame has 24 px top and bottom tiles. Collapsed KRunner is
// 47 px tall, so they overlap by one row and draw a dark line across the middle.
var MIN_HEIGHT = 48;

function place(w) {
    var area = workspace.clientArea(KWin.PlacementArea, w);
    var g = w.frameGeometry;
    var h = Math.max(Math.round(g.height), MIN_HEIGHT);
    var x = Math.round(area.x + (area.width - g.width) / 2);
    var y = Math.round(area.y + GAP);
    if (Math.round(g.x) !== x || Math.round(g.y) !== y || Math.round(g.height) !== h)
        w.frameGeometry = { x: x, y: y, width: g.width, height: h };
}

function watch(w) {
    if (!w || w.resourceClass !== "krunner")
        return;
    place(w);
    w.frameGeometryChanged.connect(function () { place(w); });
}

workspace.windowAdded.connect(watch);
workspace.windowList().forEach(watch);
