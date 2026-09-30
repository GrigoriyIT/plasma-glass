import QtQuick
import QtQuick.Layouts

// One instrument: title, last price, change, line chart with an optional
// dashed CBR reference line, and a footnote. Hover the chart to read a point.
// A sharp move (see main.qml alertFor) adds a coloured badge and a glowing rim
// that pulses for the first three minutes.
Item {
    id: tile

    property var ins
    property var series: null      // { points: [{t, v}], base, secid }
    property var ref: null         // CBR value per point, or null
    property var cbrInfo: null     // { today, next, nextDate }
    property string expiry: ""
    property var alert: null       // { dir, kind, text } while the move is sharp
    property string customNote: ""
    property bool compact: false   // narrow tile: percent change only
    property string range: "day"
    property bool rightEdge: false
    property bool bottomEdge: false
    property int hover: -1

    readonly property var pts: series ? series.points : []
    readonly property real last: pts.length ? pts[pts.length - 1].v : NaN
    readonly property real change: series ? last - series.base : NaN
    readonly property color up: "#5ee07a"
    readonly property color down: "#ff6b62"
    readonly property color dim: Qt.rgba(1, 1, 1, 0.55)
    readonly property color alertColor: alert && alert.dir > 0 ? up : down
    readonly property string alertKey: alert ? alert.kind + alert.dir : ""
    property bool pulsing: false

    onAlertKeyChanged: {
        pulsing = alertKey !== "";
        if (pulsing)
            pulseEnd.restart();
    }
    Timer {
        id: pulseEnd
        interval: 180000
        onTriggered: tile.pulsing = false
    }

    function fmt(v, dec) {
        return isNaN(v) ? "—" : Number(v).toLocaleString(Qt.locale("ru_RU"), "f", dec === undefined ? ins.decimals : dec);
    }
    function signed(v, dec) {
        return (v > 0 ? "+" : v < 0 ? "−" : "") + fmt(Math.abs(v), dec);
    }
    function when(t) {
        const d = new Date(t);
        return range === "day" ? Qt.formatTime(d, "HH:mm")
             : range === "week" ? Qt.formatDateTime(d, "ddd HH:mm")
             : range === "month" ? Qt.formatDate(d, "dd.MM")
             : Qt.formatDate(d, "dd.MM.yy");
    }
    function shortDate(iso) {
        return iso ? iso.slice(8, 10) + "." + iso.slice(5, 7) : "";
    }
    function note() {
        if (hover >= 0 && ref && !isNaN(ref[hover]))
            return ins.derived ? "Минэк $" + fmt(ref[hover]) + " · оценка " + signed(pts[hover].v - ref[hover])
                               : "ЦБ " + fmt(ref[hover]) + " · рынок " + signed(pts[hover].v - ref[hover]);
        if (customNote)
            return customNote;
        if (ins.asset && series && series.secid === "BR")
            return "ближайший фьючерс, склейка контрактов";
        if (ins.asset)
            return (series ? "фьючерс " + series.secid : "фьючерс") + (expiry ? " · до " + shortDate(expiry) : "");
        if (!ins.cbrCode)
            return "фьючерс " + ins.secid;
        if (!cbrInfo)
            return "ЦБ —";
        let s = "ЦБ " + fmt(cbrInfo.today);
        if (!isNaN(cbrInfo.next))
            s += "  ·  " + shortDate(cbrInfo.nextDate) + " → " + fmt(cbrInfo.next) + (cbrInfo.next > cbrInfo.today ? " ↑" : cbrInfo.next < cbrInfo.today ? " ↓" : "");
        return s;
    }

    onPtsChanged: chart.requestPaint()
    onRefChanged: chart.requestPaint()
    onHoverChanged: chart.requestPaint()

    Rectangle {
        visible: tile.rightEdge
        width: 1
        anchors { right: parent.right; top: parent.top; bottom: parent.bottom; topMargin: 8; bottomMargin: 8 }
        color: Qt.rgba(1, 1, 1, 0.08)
    }
    Rectangle {
        visible: tile.bottomEdge
        height: 1
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; leftMargin: 8; rightMargin: 8 }
        color: Qt.rgba(1, 1, 1, 0.08)
    }

    // sharp-move rim: tinted glass plus a coloured outline
    Rectangle {
        id: glow
        anchors.fill: parent
        anchors.margins: 3
        radius: 8
        visible: tile.alert !== null
        color: Qt.rgba(tile.alertColor.r, tile.alertColor.g, tile.alertColor.b, 0.07)
        border.width: 1.5
        border.color: tile.alertColor
        opacity: 0.45

        SequentialAnimation on opacity {
            running: tile.pulsing && glow.visible
            loops: Animation.Infinite
            onRunningChanged: if (!running) glow.opacity = 0.45
            NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutSine }
            NumberAnimation { to: 0.25; duration: 700; easing.type: Easing.InOutSine }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 0

        RowLayout {
            Layout.fillWidth: true

            Text {
                Layout.fillWidth: tile.alert !== null
                Layout.maximumWidth: implicitWidth
                text: tile.ins.title
                elide: Text.ElideRight
                font.pixelSize: 15
                font.weight: Font.DemiBold
                color: tile.dim
            }
            Rectangle {
                visible: tile.alert !== null
                Layout.leftMargin: 4
                implicitWidth: badge.implicitWidth + 10
                implicitHeight: badge.implicitHeight + 2
                radius: 4
                color: Qt.rgba(tile.alertColor.r, tile.alertColor.g, tile.alertColor.b, 0.22)

                Text {
                    id: badge
                    anchors.centerIn: parent
                    text: tile.alert ? (tile.alert.dir > 0 ? "▲ " : "▼ ") + tile.alert.text : ""
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    font.features: { "tnum": 1 }
                    color: tile.alertColor
                }
            }
            Item { Layout.fillWidth: true }
            Text {
                text: tile.hover >= 0 ? tile.when(tile.pts[tile.hover].t)
                    : isNaN(tile.change) ? ""
                    : tile.compact || tile.alert ? tile.signed(tile.change / tile.series.base * 100, 2) + "%"
                    : tile.signed(tile.change) + "  " + tile.signed(tile.change / tile.series.base * 100, 2) + "%"
                font.pixelSize: 15
                font.features: { "tnum": 1 }
                color: tile.hover >= 0 || !(tile.change) ? tile.dim : tile.change > 0 ? tile.up : tile.down
            }
        }

        Row {
            spacing: 4

            Text {
                id: valueText
                text: tile.ins.prefix + tile.fmt(tile.hover >= 0 ? tile.pts[tile.hover].v : tile.last)
                font.pixelSize: 30
                font.weight: Font.Light
                font.features: { "tnum": 1 }
                color: "white"
            }
            Text {
                visible: !!tile.ins.suffix
                anchors.baseline: valueText.baseline
                text: tile.ins.suffix || ""
                font.pixelSize: 14
                color: tile.dim
            }
        }

        Canvas {
            id: chart
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.topMargin: 4
            Layout.bottomMargin: 4

            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()

            onPaint: {
                const ctx = getContext("2d");
                ctx.reset();
                const p = tile.pts, n = p.length, ref = tile.ref;
                if (n < 2)
                    return;
                let lo = Infinity, hi = -Infinity;
                for (let i = 0; i < n; i++) {
                    lo = Math.min(lo, p[i].v); hi = Math.max(hi, p[i].v);
                    if (ref && !isNaN(ref[i])) { lo = Math.min(lo, ref[i]); hi = Math.max(hi, ref[i]); }
                }
                const span = (hi - lo) || Math.abs(hi) * 0.001 || 1;
                lo -= span * 0.08; hi += span * 0.08;
                const w = width, h = height;
                const x = i => 1 + i * (w - 5) / (n - 1);
                const y = v => h - 2 - (v - lo) / (hi - lo) * (h - 4);

                // area under the line
                ctx.beginPath();
                ctx.moveTo(x(0), y(p[0].v));
                for (let i = 1; i < n; i++) ctx.lineTo(x(i), y(p[i].v));
                ctx.lineTo(x(n - 1), h);
                ctx.lineTo(x(0), h);
                ctx.closePath();
                const g = ctx.createLinearGradient(0, 0, 0, h);
                g.addColorStop(0, "rgba(255,255,255,0.16)");
                g.addColorStop(1, "rgba(255,255,255,0)");
                ctx.fillStyle = g;
                ctx.fill();

                // CBR reference, stepped and dashed
                if (ref) {
                    ctx.save();
                    ctx.setLineDash([3, 3]);
                    ctx.lineWidth = 1;
                    ctx.strokeStyle = "rgba(255,255,255,0.45)";
                    ctx.beginPath();
                    let open = false;
                    for (let i = 0; i < n; i++) {
                        if (isNaN(ref[i])) { open = false; continue; }
                        if (!open) { ctx.moveTo(x(i), y(ref[i])); open = true; }
                        else { ctx.lineTo(x(i), y(ref[i - 1])); ctx.lineTo(x(i), y(ref[i])); }
                    }
                    ctx.stroke();
                    ctx.restore();
                }

                // price line
                ctx.beginPath();
                ctx.moveTo(x(0), y(p[0].v));
                for (let i = 1; i < n; i++) ctx.lineTo(x(i), y(p[i].v));
                ctx.lineWidth = 1.5;
                ctx.lineJoin = "round";
                ctx.strokeStyle = "rgba(255,255,255,0.9)";
                ctx.stroke();

                // last point, coloured by direction
                const c = tile.change > 0 ? tile.up : tile.change < 0 ? tile.down : "white";
                ctx.fillStyle = String(c);
                ctx.beginPath();
                ctx.arc(x(n - 1), y(p[n - 1].v), 2.5, 0, 2 * Math.PI);
                ctx.fill();

                if (tile.hover >= 0 && tile.hover < n) {
                    const hx = x(tile.hover);
                    ctx.strokeStyle = "rgba(255,255,255,0.3)";
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    ctx.moveTo(hx, 0);
                    ctx.lineTo(hx, h);
                    ctx.stroke();
                    ctx.fillStyle = "white";
                    ctx.beginPath();
                    ctx.arc(hx, y(p[tile.hover].v), 3, 0, 2 * Math.PI);
                    ctx.fill();
                }
            }

            Text {
                anchors.centerIn: parent
                visible: tile.pts.length < 2
                text: "загрузка…"
                font.pixelSize: 13
                color: tile.dim
            }

            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                onPositionChanged: mouse => {
                    const n = tile.pts.length;
                    tile.hover = n < 2 ? -1 : Math.max(0, Math.min(n - 1, Math.round((mouse.x - 1) / (width - 5) * (n - 1))));
                }
                onExited: tile.hover = -1
            }
        }

        Text {
            Layout.fillWidth: true
            text: tile.note()
            elide: Text.ElideRight
            font.pixelSize: 13
            font.features: { "tnum": 1 }
            color: tile.dim
        }
    }
}
