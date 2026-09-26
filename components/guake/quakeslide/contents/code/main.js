"use strict";

// Guake runs under XWayland: hiding it unmaps the window (KWin sees it as
// closed) and showing maps it again (added). Slide it vertically from/to
// above the top screen edge, and grab the add/close roles so the generic
// open/close effects (scale, fade...) leave it alone.
var quakeSlide = {
    duration: animationTime(200),

    // Only the terminal itself ("Guake!"), not its Preferences dialog.
    isGuake: function (w) {
        return w.windowClass.indexOf("guake") !== -1 && w.caption === "Guake!";
    },

    offset: function (w) {
        return -(w.y + w.height);
    },

    windowAdded: function (w) {
        if (!quakeSlide.isGuake(w)) return;
        w.setData(Effect.WindowAddedGrabRole, effect);
        animate({
            window: w,
            duration: quakeSlide.duration,
            animations: [{
                type: Effect.Translation,
                from: { value1: 0, value2: quakeSlide.offset(w) },
                to: { value1: 0, value2: 0 },
                curve: QEasingCurve.OutCubic
            }]
        });
    },

    windowClosed: function (w) {
        if (!quakeSlide.isGuake(w)) return;
        w.setData(Effect.WindowClosedGrabRole, effect);
        animate({
            window: w,
            duration: quakeSlide.duration,
            animations: [{
                type: Effect.Translation,
                from: { value1: 0, value2: 0 },
                to: { value1: 0, value2: quakeSlide.offset(w) },
                curve: QEasingCurve.InCubic
            }]
        });
    },

    init: function () {
        effects.windowAdded.connect(quakeSlide.windowAdded);
        effects.windowClosed.connect(quakeSlide.windowClosed);
    }
};

quakeSlide.init();
