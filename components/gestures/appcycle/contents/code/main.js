// Next/previous application window in a stable (open) order, so a
// three-finger swipe walks through apps like a row of cards instead of the
// most-recently-used shuffle of Alt+Tab.
function candidates() {
    return workspace.windowList().filter(function (w) {
        return w.normalWindow && !w.skipTaskbar && !w.deleted
            && (w.onAllDesktops || w.desktops.indexOf(workspace.currentDesktop) !== -1);
    });
}

function step(delta) {
    var list = candidates();
    if (list.length === 0)
        return;
    var i = list.indexOf(workspace.activeWindow);
    var next = list[((i < 0 ? 0 : i + delta) % list.length + list.length) % list.length];
    if (next.minimized)
        next.minimized = false;
    workspace.activeWindow = next;
}

registerShortcut("AppCycle Next", "App Cycle: next application window", "", function () { step(1); });
registerShortcut("AppCycle Previous", "App Cycle: previous application window", "", function () { step(-1); });
