import QtQuick
import QtQuick.Layouts
import QtQuick.LocalStorage
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import "../code/ics.js" as Ics

// Glass agenda card: upcoming events from iCal links (Google, Yandex, Nextcloud…).
PlasmoidItem {
    id: root

    Plasmoid.backgroundHints: PlasmaCore.Types.NoBackground
    preferredRepresentation: fullRepresentation

    readonly property var urls: Plasmoid.configuration.icsUrls.split(/\s+/).filter(u => /^(https?|webcal):\/\//.test(u))
    readonly property int days: Math.max(1, Plasmoid.configuration.days)
    readonly property var palette: ["#0a84ff", "#30d158", "#ff9f0a", "#bf5af2", "#ff375f", "#64d2ff"]
    readonly property color dim: Qt.rgba(1, 1, 1, 0.55)

    property var perCalendar: ({})  // url -> occurrences within the cache window
    property var failed: ({})       // url -> true
    readonly property bool anyFailed: urls.some(u => failed[u])
    property real updated: 0
    property real clock: Date.now()

    function dayStart(t) {
        const d = new Date(t);
        return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    }

    function fetchAll() {
        urls.forEach((url, i) => {
            const x = new XMLHttpRequest();
            x.onreadystatechange = function () {
                if (x.readyState !== XMLHttpRequest.DONE)
                    return;
                const f = Object.assign({}, failed);
                if (x.status !== 200) {
                    console.warn("agenda: HTTP", x.status, x.statusText);
                    f[url] = true;
                    failed = f;
                    return;
                }
                try {
                    const from = dayStart(Date.now()), to = from + 32 * 86400e3;
                    const p = Object.assign({}, perCalendar);
                    p[url] = Ics.collect(x.responseText, from, to, i);
                    perCalendar = p;
                    delete f[url];
                    failed = f;
                    updated = Date.now();
                    save();
                } catch (e) {
                    console.warn("agenda:", e);
                }
            };
            x.open("GET", url.replace(/^webcal:/, "https:"));
            x.send();
        });
    }

    // flat rows for the list: day headers followed by that day's events
    readonly property var rows: {
        const from = dayStart(clock), to = from + days * 86400e3, out = [];
        let all = [];
        urls.forEach(u => { if (perCalendar[u]) all = all.concat(perCalendar[u]); });
        all = all.filter(e => e.end > clock && e.t < to)
                 .sort((a, b) => (a.allDay === b.allDay ? 0 : a.allDay ? -1 : 1) || a.t - b.t);
        for (let d = from; d < to; d += 86400e3) {
            const next = new Date(new Date(d).getFullYear(), new Date(d).getMonth(), new Date(d).getDate() + 1).getTime();
            const list = all.filter(e => e.t < next && e.end > d).sort((a, b) => (b.allDay - a.allDay) || a.t - b.t);
            if (!list.length)
                continue;
            out.push({ header: true, t: d });
            list.forEach(e => out.push(Object.assign({ header: false, day: d }, e)));
        }
        return out;
    }

    function dayLabel(t) {
        const today = dayStart(clock);
        if (t === today)
            return "Сегодня";
        if (t === today + 86400e3 || dayStart(today + 36 * 3600e3) === t)
            return "Завтра";
        const s = Qt.locale("ru_RU").toString(new Date(t), "dddd, d MMMM");
        return s.charAt(0).toUpperCase() + s.slice(1);
    }
    function timeLabel(e) {
        if (e.allDay)
            return "весь день";
        const f = t => Qt.formatTime(new Date(t), "HH:mm");
        return e.end > e.t ? f(e.t) + "–" + f(e.end) : f(e.t);
    }

    // ---- cache ----
    function db() {
        const d = LocalStorage.openDatabaseSync("plasmaglass-agenda", "", "Agenda cache", 2000000);
        d.transaction(tx => tx.executeSql("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)"));
        return d;
    }
    function save() {
        db().transaction(tx => tx.executeSql("INSERT OR REPLACE INTO kv VALUES('events', ?)",
                                             [JSON.stringify({ perCalendar, updated })]));
    }
    Component.onCompleted: {
        db().readTransaction(tx => {
            const rs = tx.executeSql("SELECT v FROM kv WHERE k = 'events'");
            if (rs.rows.length) {
                const b = JSON.parse(rs.rows.item(0).v);
                perCalendar = b.perCalendar;
                updated = b.updated;
            }
        });
        fetchAll();
    }
    onUrlsChanged: {
        // forget calendars that were removed or edited (e.g. a half-pasted link)
        const f = {}, p = {};
        urls.forEach(u => { if (failed[u]) f[u] = true; if (perCalendar[u]) p[u] = perCalendar[u]; });
        failed = f;
        perCalendar = p;
        fetchAll();
    }

    Timer {
        interval: 15 * 60e3
        running: true
        repeat: true
        onTriggered: root.fetchAll()
    }
    Timer {
        interval: 60e3
        running: true
        repeat: true
        onTriggered: root.clock = Date.now()
    }

    fullRepresentation: Item {
        Layout.preferredWidth: 464
        Layout.preferredHeight: 300
        Layout.minimumWidth: 260
        Layout.minimumHeight: 160

        GlassCard {
            anchors.fill: parent
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 8

            RowLayout {
                Layout.fillWidth: true

                Text {
                    text: {
                        const s = Qt.locale("ru_RU").toString(new Date(root.clock), "dddd, d MMMM");
                        return s.charAt(0).toUpperCase() + s.slice(1);
                    }
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    color: root.dim
                }
                Item { Layout.fillWidth: true }
                Text {
                    visible: root.anyFailed
                    text: "нет связи"
                    font.pixelSize: 11
                    color: "#ff9f0a"
                }
            }

            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: root.rows.length > 0
                clip: true
                spacing: 2
                model: root.rows
                boundsBehavior: Flickable.StopAtBounds

                delegate: Item {
                    id: row
                    required property var modelData
                    required property int index
                    readonly property bool now: !modelData.header && !modelData.allDay
                                                && modelData.t <= root.clock && modelData.end > root.clock
                    width: ListView.view.width
                    height: modelData.header ? 24 : (modelData.location ? 38 : 26)

                    Text {
                        visible: row.modelData.header
                        anchors.left: parent.left
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 3
                        text: row.modelData.header ? root.dayLabel(row.modelData.t) : ""
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                        color: Qt.rgba(1, 1, 1, 0.45)
                    }

                    Rectangle {
                        visible: !row.modelData.header
                        anchors.fill: parent
                        radius: 6
                        color: row.now ? Qt.rgba(1, 1, 1, 0.08) : "transparent"
                    }
                    Rectangle {
                        visible: !row.modelData.header
                        x: 6
                        width: 3
                        radius: 1.5
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        anchors.margins: 5
                        color: root.palette[(row.modelData.calendar || 0) % root.palette.length]
                    }
                    Column {
                        visible: !row.modelData.header
                        anchors.left: parent.left
                        anchors.leftMargin: 16
                        anchors.right: parent.right
                        anchors.rightMargin: 6
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 1

                        RowLayout {
                            width: parent.width
                            spacing: 8

                            Text {
                                Layout.fillWidth: true
                                text: row.modelData.summary || ""
                                elide: Text.ElideRight
                                font.pixelSize: 13
                                color: "white"
                            }
                            Text {
                                text: row.now ? "сейчас" : (row.modelData.header ? "" : root.timeLabel(row.modelData))
                                font.pixelSize: 11
                                font.features: { "tnum": 1 }
                                color: row.now ? "#30d158" : root.dim
                            }
                        }
                        Text {
                            visible: !!row.modelData.location
                            width: parent.width
                            text: row.modelData.location || ""
                            elide: Text.ElideRight
                            font.pixelSize: 11
                            color: Qt.rgba(1, 1, 1, 0.45)
                        }
                    }
                }
            }

            // empty states
            ColumnLayout {
                visible: root.rows.length === 0
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 10

                Item { Layout.fillHeight: true }
                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    text: root.urls.length ? "Событий на " + root.days + " " + (root.days === 1 ? "день" : root.days < 5 ? "дня" : "дней") + " нет"
                                           : "Добавьте ссылку на календарь (iCal) — Google, Яндекс или Nextcloud"
                    font.pixelSize: 12
                    color: root.dim
                }
                Rectangle {
                    visible: root.urls.length === 0
                    Layout.alignment: Qt.AlignHCenter
                    implicitWidth: btn.implicitWidth + 24
                    implicitHeight: 26
                    radius: 7
                    color: area.containsMouse ? Qt.rgba(1, 1, 1, 0.18) : Qt.rgba(1, 1, 1, 0.12)

                    Text {
                        id: btn
                        anchors.centerIn: parent
                        text: "Настроить"
                        font.pixelSize: 12
                        color: "white"
                    }
                    MouseArea {
                        id: area
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: Plasmoid.internalAction("configure").trigger()
                    }
                }
                Item { Layout.fillHeight: true }
            }
        }
    }
}
