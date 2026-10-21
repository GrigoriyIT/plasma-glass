import QtQuick
import QtQuick.Shapes
import "scene3.js" as Scene3
import "scene1.js" as Scene1
import "palette.js" as P

// One screen's slice of the 5760x1080 panorama. Everything static (sky,
// landscape, sun, moon, stars) is rendered into one texture that is redrawn
// only when the colours change; clouds, rain and snow move on top of it.
Item {
    id: root
    clip: true

    // true: the one-screen composition; false: the three-screen panorama.
    property bool single: false
    readonly property var sc: single ? Scene1 : Scene3
    // Left edge of this screen in scene units (0, 1920, 3840 for three screens).
    property real sceneX: 0
    property real elevation: 20          // sun elevation, degrees
    property point sun: Qt.point(2880, 300)
    property point moon: Qt.point(3800, 250)
    property bool moonUp: false
    property real moonPhase: 0.5         // 0 new, 0.5 full
    property string season: "summer"
    property bool snowGround: false
    property real clouds: 0              // 0..1
    property string precip: "none"       // none, rain, snow, sleet
    property real intensity: 0.5         // 0..1
    property real fog: 0
    property bool thunder: false
    property bool animate: true

    readonly property real k: height / root.sc.height
    readonly property var c: P.colours({ elevation: elevation, season: season, snowGround: snowGround, clouds: clouds, fog: fog, precip: precip })

    component Layer: Shape {
        property alias d: svg.path
        property alias fill: sp.fillColor
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            id: sp
            fillRule: ShapePath.WindingFill
            strokeWidth: -1
            strokeColor: "transparent"
            PathSvg { id: svg }
        }
    }

    Item {
        id: still
        anchors.fill: parent
        layer.enabled: true
        layer.smooth: true

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: root.c.skyTop }
                GradientStop { position: 0.42; color: root.c.skyMid }
                GradientStop { position: 0.66; color: root.c.skyHorizon }
            }
        }

        Item {
            id: world
            width: root.sc.width
            height: root.sc.height
            x: -root.sceneX * root.k
            transformOrigin: Item.TopLeft
            scale: root.k

            Layer { d: root.sc.stars; fill: Qt.rgba(1, 1, 1, 0.9); opacity: root.c.stars; visible: opacity > 0 }

            // Sun with a soft glow; hidden below the horizon.
            Item {
                visible: root.elevation > -3
                x: root.sun.x; y: root.sun.y
                opacity: Math.max(0.12, 1 - root.clouds * 0.9)
                Shape {
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeWidth: -1
                        strokeColor: "transparent"
                        fillGradient: RadialGradient {
                            centerX: 0; centerY: 0; centerRadius: 230
                            focalX: 0; focalY: 0
                            GradientStop { position: 0.0; color: root.c.sunGlow }
                            GradientStop { position: 0.35; color: Qt.rgba(root.c.sunGlow.r, root.c.sunGlow.g, root.c.sunGlow.b, root.c.sunGlow.a * 0.45) }
                            GradientStop { position: 1.0; color: Qt.rgba(root.c.sunGlow.r, root.c.sunGlow.g, root.c.sunGlow.b, 0) }
                        }
                        PathSvg { path: root.sc.glow }
                    }
                }
                Rectangle { width: 64; height: 64; radius: 32; x: -32; y: -32; color: root.c.sun }
            }

            // Moon with its phase: a lit disc partly covered by a sky-coloured one.
            Item {
                visible: root.moonUp && root.elevation < -2
                x: root.moon.x; y: root.moon.y
                opacity: Math.max(0.15, 1 - root.clouds * 0.85)
                Rectangle { width: 150; height: 150; radius: 75; x: -75; y: -75; color: Qt.rgba(0.85, 0.88, 1, 0.10) }
                Rectangle {
                    id: disc
                    width: 46; height: 46; radius: 23; x: -23; y: -23
                    color: "#eef0f4"
                    clip: true
                    Rectangle {
                        // shadow disc: offset by the phase (waxing: shadow on the left)
                        readonly property real p: root.moonPhase
                        width: parent.width; height: parent.height; radius: width / 2
                        // waxing: the shadow slides off to the left; waning: it comes in from the right
                        x: p < 0.5 ? -parent.width * 2 * p : parent.width * 2 * (1 - p)
                        color: root.c.skyTop
                        visible: Math.abs(p - 0.5) > 0.02
                    }
                }
            }

            Layer { d: root.sc.far; fill: root.c.far }
            Layer { d: root.sc.mid; fill: root.c.mid }
            Layer { d: root.sc.shikhan; fill: root.c.shikhan }
            Layer { d: root.sc.shikhanRock; fill: root.c.shikhanRock }
            Layer { d: root.sc.hills; fill: root.c.hills }
            Layer { d: root.sc.hillCrowns; fill: root.c.hillCrowns }
            Layer { d: root.sc.hillConifers; fill: root.c.hillConifers }
            Layer { d: root.sc.plain; fill: root.c.plain }
            Layer { d: root.sc.river; fill: root.c.river }
            Layer { d: root.sc.shimmer; fill: root.c.shimmer }
            Layer { d: root.sc.pines; fill: root.c.pines }
            Layer { d: root.sc.nearLeft; fill: root.c.near }
            Layer { d: root.sc.nearRight; fill: root.c.near }
            Layer { d: root.sc.horses; fill: root.c.horses }
            Layer { d: root.sc.yurt; fill: root.c.yurt }
            Layer { d: root.sc.yurtShade; fill: root.c.yurtShade }
            Layer { d: root.sc.yurtBand; fill: root.c.yurtBand }
            Layer { d: root.sc.smoke; fill: root.c.smoke; visible: root.precip !== "rain" }
            Layer { d: root.sc.yurtDoor; fill: root.c.yurtDoor }
            Layer { d: root.sc.yurtDoor; fill: "#ffb35a"; opacity: root.c.lamp; visible: opacity > 0 }
            Layer { d: root.sc.birchFallen; fill: root.c.birchFallen; visible: root.season === "autumn" && !root.snowGround }
            Layer { d: root.sc.birchBranches; fill: root.c.birchBranches }
            Layer { d: root.sc.birchTwigs; fill: root.c.birchTwigs }
            Layer { d: root.sc.birchTrunks; fill: root.c.birchTrunks }
            Layer { d: root.sc.birchMarks; fill: root.c.birchMarks }
            Item {
                // leaves: none in winter, sparse in early spring
                anchors.fill: parent
                visible: !root.snowGround && root.season !== "winter"
                Layer { d: root.sc.birchLeavesDark; fill: root.c.birchLeavesDark }
                Layer { d: root.sc.birchLeavesMid; fill: root.c.birchLeavesMid }
                Layer { d: root.sc.birchLeavesLight; fill: root.c.birchLeavesLight }
            }
            Layer { d: root.sc.grass; fill: root.c.grass }
        }

        // Overcast veil over the whole sky.
        Rectangle {
            anchors.fill: parent
            opacity: root.clouds * root.clouds * 0.55
            gradient: Gradient {
                GradientStop { position: 0.0; color: root.c.cloud }
                GradientStop { position: 0.62; color: Qt.rgba(root.c.cloud.r, root.c.cloud.g, root.c.cloud.b, 0.0) }
            }
        }

        // Fog: a band over the plain and the hills.
        Rectangle {
            anchors.fill: parent
            opacity: root.fog * 0.9
            visible: opacity > 0
            gradient: Gradient {
                GradientStop { position: 0.38; color: Qt.rgba(root.c.fog.r, root.c.fog.g, root.c.fog.b, 0) }
                GradientStop { position: 0.62; color: root.c.fog }
                GradientStop { position: 0.85; color: Qt.rgba(root.c.fog.r, root.c.fog.g, root.c.fog.b, 0.35) }
                GradientStop { position: 1.0; color: Qt.rgba(root.c.fog.r, root.c.fog.g, root.c.fog.b, 0.1) }
            }
        }
    }

    // Clouds: three flat sets that appear as cloudiness grows, drifting slowly.
    Item {
        id: cloudBand
        visible: root.clouds > 0.08
        width: root.sc.width * 2 * root.k
        height: parent.height
        x: -root.sceneX * root.k - drift * root.k
        property real drift: 0
        // A couple of pixels once a second: as smooth to the eye at this speed,
        // and the screen is redrawn once a second instead of 60 times.
        Timer {
            running: root.animate && cloudBand.visible
            interval: 1000
            repeat: true
            onTriggered: cloudBand.drift = (cloudBand.drift + root.sc.width / (40 * 60)) % root.sc.width
        }
        Repeater {
            model: 2
            Item {
                x: index * root.sc.width * root.k
                width: root.sc.width; height: root.sc.height
                transformOrigin: Item.TopLeft
                scale: root.k
                layer.enabled: true
                layer.smooth: true
                Item {
                    anchors.fill: parent
                    opacity: Math.min(1, (root.clouds - 0.08) / 0.2)
                    Layer { d: root.sc.cloudsAShade; fill: root.c.cloudShade }
                    Layer { d: root.sc.cloudsA; fill: root.c.cloud }
                }
                Item {
                    anchors.fill: parent
                    opacity: Math.max(0, Math.min(1, (root.clouds - 0.35) / 0.2))
                    visible: opacity > 0
                    Layer { d: root.sc.cloudsBShade; fill: root.c.cloudShade }
                    Layer { d: root.sc.cloudsB; fill: root.c.cloud }
                }
                Item {
                    anchors.fill: parent
                    opacity: Math.max(0, Math.min(1, (root.clouds - 0.6) / 0.2))
                    visible: opacity > 0
                    Layer { d: root.sc.cloudsCShade; fill: root.c.cloudShade }
                    Layer { d: root.sc.cloudsC; fill: root.c.cloud }
                }
            }
        }
    }

    // Rain and snow: a screen-sized tile in two depths, scrolled down.
    component Fall: Item {
        id: fall
        property string d
        property color tint
        property int period: 800
        property real depth: 1
        property real sway: 0
        property int frame: 33          // ms per frame: 30 fps for rain, slower for snow
        anchors.fill: parent
        property real t: 0
        Timer {
            running: root.animate && fall.visible
            interval: fall.frame
            repeat: true
            onTriggered: fall.t = (fall.t + fall.frame / fall.period) % 1
        }
        Repeater {
            model: 2
            Item {
                width: fall.width; height: fall.height
                y: (fall.t - index) * fall.height
                x: fall.sway * Math.sin((fall.t + index) * Math.PI * 2)
                Shape {
                    width: 1920; height: 1080
                    transformOrigin: Item.TopLeft
                    scale: fall.width / 1920 * fall.depth
                    ShapePath {
                        fillRule: ShapePath.WindingFill
                        strokeWidth: -1
                        strokeColor: "transparent"
                        fillColor: fall.tint
                        PathSvg { path: fall.d }
                    }
                }
            }
        }
    }

    Item {
        anchors.fill: parent
        visible: root.precip === "rain" || root.precip === "sleet"
        opacity: 0.45 + root.intensity * 0.55
        Fall { d: root.sc.rain; tint: root.c.rain; period: 900; depth: 1.4; opacity: 0.55 }
        Fall { d: root.sc.rain; tint: root.c.rain; period: 620; visible: root.intensity > 0.3 }
    }
    Item {
        anchors.fill: parent
        visible: root.precip === "snow" || root.precip === "sleet"
        opacity: 0.55 + root.intensity * 0.45
        Fall { d: root.sc.snow; tint: root.c.snow; period: 16000; depth: 1.5; sway: 18; frame: 50; opacity: 0.7 }
        Fall { d: root.sc.snow; tint: root.c.snow; period: 10000; sway: 26; frame: 50; visible: root.intensity > 0.3 }
    }

    // Lightning: a rare short flash.
    Rectangle {
        id: flash
        anchors.fill: parent
        color: "white"
        opacity: 0
        SequentialAnimation {
            id: flashAnim
            NumberAnimation { target: flash; property: "opacity"; to: 0.55; duration: 60 }
            NumberAnimation { target: flash; property: "opacity"; to: 0.1; duration: 90 }
            NumberAnimation { target: flash; property: "opacity"; to: 0.4; duration: 50 }
            NumberAnimation { target: flash; property: "opacity"; to: 0; duration: 400 }
        }
        Timer {
            running: root.thunder && root.animate
            repeat: true
            interval: 9000
            onTriggered: { interval = 7000 + Math.random() * 16000; flashAnim.start(); }
        }
    }
}
