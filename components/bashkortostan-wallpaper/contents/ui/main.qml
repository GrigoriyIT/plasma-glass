import QtQuick
import QtQuick.Window
import QtQuick.Effects
import org.kde.plasma.plasmoid
import "sky.js" as Sky

// Landscapes of Bashkortostan: one panorama over three screens (or a one-screen
// composition), lit by the real sun and moon over the configured point, with the
// season and the current met.no weather, and a large clock.
WallpaperItem {
    id: root

    property date now: new Date()
    readonly property real lat: root.configuration.Latitude
    readonly property real lon: root.configuration.Longitude

    // --- screens: three side by side -> panorama slice; otherwise one-screen composition
    property var screenXs: []
    function updateScreens() {
        const xs = [];
        for (let i = 0; i < Qt.application.screens.length; i++)
            xs.push(Qt.application.screens[i].virtualX);
        xs.sort((a, b) => a - b);
        screenXs = xs;
    }
    readonly property bool wide: screenXs.length >= 3
    readonly property int screenIndex: Math.max(0, screenXs.indexOf(Screen.virtualX))
    readonly property bool mainScreen: wide ? screenIndex === 1 : screenIndex === 0
    Connections {
        target: Qt.application
        function onScreensChanged() { root.updateScreens(); }
    }

    // --- weather from MET Norway (free, no key; needs an identifying User-Agent)
    property var wx: ({ clouds: 0.2, precip: "none", intensity: 0.5, fog: 0, thunder: false })
    property var temp: undefined
    function fetchWeather() {
        const x = new XMLHttpRequest();
        x.onreadystatechange = function () {
            if (x.readyState !== XMLHttpRequest.DONE)
                return;
            if (x.status !== 200) {
                console.warn("bashkortostan wallpaper: weather HTTP", x.status);
                return;
            }
            try {
                const ts = JSON.parse(x.responseText).properties.timeseries;
                // the entry for the current hour
                let e = ts[0];
                for (let i = 0; i < ts.length; i++) {
                    if (Date.parse(ts[i].time) > Date.now())
                        break;
                    e = ts[i];
                }
                const d = e.data;
                const sym = d.next_1_hours ? d.next_1_hours.summary.symbol_code
                          : d.next_6_hours ? d.next_6_hours.summary.symbol_code : "";
                root.wx = Sky.weather(sym, d.instant.details);
                root.temp = d.instant.details.air_temperature;
            } catch (err) {
                console.warn("bashkortostan wallpaper:", err);
            }
        };
        x.open("GET", "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat="
               + lat.toFixed(4) + "&lon=" + lon.toFixed(4));
        x.setRequestHeader("User-Agent", "PlasmaGlass-wallpaper/1.0 github.com/GrigoriyIT/plasma-glass");
        x.send();
    }
    Timer {
        interval: 30 * 60 * 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: root.fetchWeather()
    }
    onLatChanged: fetchWeather()
    onLonChanged: fetchWeather()

    // --- "key=value;..." override for testing: elevation, azimuth, precip, intensity,
    // clouds, fog, thunder, season, snow (e.g. "elevation=-20;precip=snow")
    readonly property var ov: {
        const o = {};
        const s = root.configuration.Override || "";
        s.split(";").forEach(kv => {
            const p = kv.split("=");
            if (p.length === 2 && p[0].trim())
                o[p[0].trim()] = isNaN(Number(p[1])) ? p[1].trim() : Number(p[1]);
        });
        return o;
    }

    readonly property var sunPos: {
        const p = Sky.sun(now, lat, lon);
        if (ov.elevation !== undefined) p.elevation = ov.elevation;
        if (ov.azimuth !== undefined) p.azimuth = ov.azimuth;
        return p;
    }
    readonly property var moonPos: Sky.moon(now, lat, lon)
    readonly property var seasonNow: Sky.season(now, temp)

    Scene {
        id: scene
        anchors.fill: parent
        single: !root.wide
        sceneX: root.wide ? Math.min(root.screenIndex, 2) * 1920 : 0
        animate: root.configuration.Animate
        elevation: root.sunPos.elevation
        sun: Sky.place(root.sunPos, scene.sc.width)
        moon: Sky.place(root.moonPos, scene.sc.width)
        moonUp: root.moonPos.elevation > 0
        moonPhase: root.moonPos.phase
        season: root.ov.season !== undefined ? root.ov.season : root.seasonNow.season
        snowGround: root.ov.snow !== undefined ? root.ov.snow === 1 : root.seasonNow.snowGround
        clouds: root.ov.clouds !== undefined ? root.ov.clouds : root.wx.clouds
        precip: root.ov.precip !== undefined ? root.ov.precip : root.wx.precip
        intensity: root.ov.intensity !== undefined ? root.ov.intensity : root.wx.intensity
        fog: root.ov.fog !== undefined ? root.ov.fog : root.wx.fog
        thunder: root.ov.thunder !== undefined ? root.ov.thunder === 1 : root.wx.thunder
        Component.onCompleted: root.loading = false
    }

    // Brightness of the sky under the top bar, for panel-adaptive-text. Every
    // screen writes its own config (the script reads the primary screen's), in
    // steps of 0.05 so the config isn't rewritten often.
    readonly property real skyLuminance: {
        const c = scene.c.skyTop;
        return Math.round((0.299 * c.r + 0.587 * c.g + 0.114 * c.b) * 20) / 20;
    }
    onSkyLuminanceChanged: publishLuminance()
    function publishLuminance() {
        if (Math.abs(root.configuration.SkyLuminance - skyLuminance) < 0.01)
            return;
        root.configuration.SkyLuminance = skyLuminance;
        root.configuration.writeConfig();
    }

    Column {
        id: clock
        visible: root.mainScreen || root.configuration.ClockEverywhere
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.height * root.configuration.VerticalPosition / 100 - height / 2
        spacing: -root.height * 0.012

        layer.enabled: true
        layer.effect: MultiEffect {
            shadowEnabled: true
            shadowColor: "black"
            shadowOpacity: 0.35
            shadowBlur: 0.6
            shadowVerticalOffset: 2
            shadowHorizontalOffset: 0
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: root.configuration.ShowDate
            text: {
                const s = Qt.locale().toString(root.now, "dddd, d MMMM");
                return s.charAt(0).toUpperCase() + s.slice(1);
            }
            color: "white"
            opacity: 0.9
            font.family: root.configuration.ClockFont
            font.weight: Font.Medium
            font.pixelSize: root.height * 0.028
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: Qt.locale().toString(root.now, "HH:mm")
            color: "white"
            font.family: root.configuration.ClockFont
            font.weight: root.configuration.ClockWeight
            font.pixelSize: root.height * 0.17
        }
    }

    // Fire right after each minute boundary: the sun moves, the clock ticks.
    Timer {
        id: minuteTimer
        running: true
        repeat: false
        onTriggered: {
            root.now = new Date();
            interval = 60000 - (root.now.getSeconds() * 1000 + root.now.getMilliseconds()) + 50;
            start();
        }
        Component.onCompleted: {
            const d = new Date();
            interval = 60000 - (d.getSeconds() * 1000 + d.getMilliseconds()) + 50;
        }
    }

    // Catch up after suspend/resume, when the timers may have been frozen.
    Connections {
        target: Qt.application
        function onStateChanged() {
            root.now = new Date();
            minuteTimer.triggered();
            root.fetchWeather();
        }
    }

    Component.onCompleted: updateScreens()
}
