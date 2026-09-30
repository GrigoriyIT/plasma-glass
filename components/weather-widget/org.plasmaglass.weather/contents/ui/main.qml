import QtQuick
import QtQuick.Layouts
import QtQuick.LocalStorage
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.kirigami as Kirigami

// Glass weather card: now, the next hours and the next days.
// Forecast: MET Norway locationforecast/2.0 (free, no key; requires an identifying User-Agent).
PlasmoidItem {
    id: root

    Plasmoid.backgroundHints: PlasmaCore.Types.NoBackground
    preferredRepresentation: fullRepresentation

    readonly property string place: Plasmoid.configuration.latitude.toFixed(4) + "," + Plasmoid.configuration.longitude.toFixed(4)
    property var series: []        // [{ t, temp, wind, hum, sym1, sym6 }]
    property real updated: 0
    property bool offline: false
    readonly property color dim: Qt.rgba(1, 1, 1, 0.55)

    function fetch() {
        const x = new XMLHttpRequest();
        x.onreadystatechange = function () {
            if (x.readyState !== XMLHttpRequest.DONE)
                return;
            if (x.status !== 200) {
                console.warn("weather: HTTP", x.status, x.statusText);
                offline = true;
                return;
            }
            try {
                const ts = JSON.parse(x.responseText).properties.timeseries;
                series = ts.map(e => {
                    const d = e.data, i = d.instant.details;
                    return {
                        t: Date.parse(e.time), temp: i.air_temperature, wind: i.wind_speed, hum: i.relative_humidity,
                        sym1: d.next_1_hours ? d.next_1_hours.summary.symbol_code : "",
                        sym6: d.next_6_hours ? d.next_6_hours.summary.symbol_code : ""
                    };
                });
                updated = Date.now();
                offline = false;
                save();
            } catch (e) {
                console.warn("weather:", e);
            }
        };
        x.open("GET", "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat="
               + Plasmoid.configuration.latitude.toFixed(4) + "&lon=" + Plasmoid.configuration.longitude.toFixed(4));
        x.setRequestHeader("User-Agent", "PlasmaGlass-weather/1.0 github.com/GrigoriyIT/plasma-glass");
        x.send();
    }

    // MET Norway symbol_code -> Breeze icon + Russian description
    function look(code) {
        const night = /_night$/.test(code), base = code.replace(/_(day|night|polartwilight)$/, "");
        const light = base.indexOf("light") === 0, heavy = base.indexOf("heavy") === 0;
        if (base === "clearsky")
            return { icon: night ? "weather-clear-night" : "weather-clear", text: "Ясно" };
        if (base === "fair")
            return { icon: night ? "weather-few-clouds-night" : "weather-few-clouds", text: "Малооблачно" };
        if (base === "partlycloudy")
            return { icon: night ? "weather-clouds-night" : "weather-clouds", text: "Переменная облачность" };
        if (base === "cloudy")
            return { icon: "weather-overcast", text: "Облачно" };
        if (base === "fog")
            return { icon: "weather-fog", text: "Туман" };
        if (base.indexOf("thunder") >= 0)
            return { icon: "weather-storm", text: "Гроза" };
        if (base.indexOf("sleet") >= 0)
            return { icon: "weather-snow-rain", text: "Мокрый снег" };
        if (base.indexOf("snow") >= 0)
            return { icon: base.indexOf("showers") >= 0 ? "weather-snow-scattered" : "weather-snow",
                     text: light ? "Небольшой снег" : heavy ? "Сильный снег" : "Снег" };
        if (base.indexOf("rainshowers") >= 0)
            return { icon: night ? "weather-showers-scattered-night" : "weather-showers-scattered-day", text: "Ливень" };
        if (base.indexOf("rain") >= 0)
            return { icon: light ? "weather-showers-scattered" : "weather-showers",
                     text: light ? "Небольшой дождь" : heavy ? "Сильный дождь" : "Дождь" };
        return { icon: "weather-none-available", text: "" };
    }

    function deg(v) {
        return (v < -0.5 ? "−" : "") + Math.abs(Math.round(v)) + "°";
    }

    readonly property var now: {
        const t = Date.now();
        let best = null;
        series.forEach(e => { if (!best || Math.abs(e.t - t) < Math.abs(best.t - t)) best = e; });
        return best;
    }
    // next hours: every 3 h starting from the next full hour
    readonly property var hours: {
        const out = [], t = Date.now();
        const future = series.filter(e => e.t > t && e.sym1);
        for (let i = 0; i < future.length && out.length < 8; i += 3)
            out.push(future[i]);
        return out;
    }
    // next 7 days: local-date min/max, icon from the 6-hour symbol around noon
    readonly property var days: {
        const by = {};
        series.forEach(e => {
            const k = Qt.formatDate(new Date(e.t), "yyyy-MM-dd");
            const d = by[k] = by[k] || { t: e.t, min: Infinity, max: -Infinity, sym: "", noon: Infinity };
            d.min = Math.min(d.min, e.temp);
            d.max = Math.max(d.max, e.temp);
            const dist = Math.abs(new Date(e.t).getHours() - 12);
            if (e.sym6 && dist < d.noon) { d.noon = dist; d.sym = e.sym6; }
        });
        return Object.keys(by).sort().map(k => by[k]).filter(d => d.sym).slice(0, 7);
    }

    // ---- cache ----
    function db() {
        const d = LocalStorage.openDatabaseSync("plasmaglass-weather", "", "Weather cache", 1000000);
        d.transaction(tx => tx.executeSql("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)"));
        return d;
    }
    function save() {
        db().transaction(tx => tx.executeSql("INSERT OR REPLACE INTO kv VALUES(?, ?)",
                                             [place, JSON.stringify({ series, updated })]));
    }
    function load() {
        db().readTransaction(tx => {
            const rs = tx.executeSql("SELECT v FROM kv WHERE k = ?", [place]);
            if (rs.rows.length) {
                const b = JSON.parse(rs.rows.item(0).v);
                series = b.series;
                updated = b.updated;
            } else {
                series = [];
                updated = 0;
            }
        });
    }

    onPlaceChanged: {
        load();
        fetch();
    }
    Component.onCompleted: {
        load();
        if (Date.now() - updated > 20 * 60e3)
            fetch();
    }
    Timer {
        interval: 30 * 60e3
        running: true
        repeat: true
        onTriggered: root.fetch()
    }
    // re-evaluate "now" / next hours between fetches
    Timer {
        interval: 5 * 60e3
        running: true
        repeat: true
        onTriggered: root.series = root.series.slice()
    }

    fullRepresentation: Item {
        Layout.preferredWidth: 464
        Layout.preferredHeight: 256
        Layout.minimumWidth: 280
        Layout.minimumHeight: 220

        GlassCard {
            anchors.fill: parent
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            anchors.topMargin: 12
            anchors.bottomMargin: 10
            spacing: 4

            RowLayout {
                Layout.fillWidth: true

                Text {
                    text: Plasmoid.configuration.city
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    color: root.dim
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: root.offline ? "нет связи" : root.updated ? "обновлено " + Qt.formatTime(new Date(root.updated), "HH:mm") : ""
                    font.pixelSize: 11
                    color: root.offline ? "#ff9f0a" : Qt.rgba(1, 1, 1, 0.45)
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 12

                Kirigami.Icon {
                    roundToIconSize: false
                    Layout.preferredWidth: 58
                    Layout.preferredHeight: 58
                    source: root.now ? root.look(root.now.sym1 || root.now.sym6).icon : "weather-none-available"
                }
                Text {
                    text: root.now ? root.deg(root.now.temp) : "—"
                    font.pixelSize: 50
                    font.weight: Font.Light
                    color: "white"
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Text {
                        Layout.fillWidth: true
                        text: root.now ? root.look(root.now.sym1 || root.now.sym6).text : ""
                        elide: Text.ElideRight
                        font.pixelSize: 15
                        color: "white"
                    }
                    Text {
                        Layout.fillWidth: true
                        text: root.now ? "ветер " + Math.round(root.now.wind) + " м/с · влажность " + Math.round(root.now.hum) + "%" : ""
                        elide: Text.ElideRight
                        font.pixelSize: 12
                        color: root.dim
                    }
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: Qt.rgba(1, 1, 1, 0.08) }

            RowLayout {
                Layout.fillWidth: true
                spacing: 0

                Repeater {
                    model: root.hours

                    Item {
                        id: hourCell
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        implicitHeight: hourCol.implicitHeight

                        ColumnLayout {
                            id: hourCol
                            anchors.horizontalCenter: parent.horizontalCenter
                            spacing: 1

                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: Qt.formatTime(new Date(hourCell.modelData.t), "HH")
                                font.pixelSize: 12
                                color: root.dim
                            }
                            Kirigami.Icon {
                                roundToIconSize: false
                                Layout.alignment: Qt.AlignHCenter
                                Layout.preferredWidth: 32
                                Layout.preferredHeight: 32
                                source: root.look(hourCell.modelData.sym1).icon
                            }
                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: root.deg(hourCell.modelData.temp)
                                font.pixelSize: 14
                                color: "white"
                            }
                        }
                    }
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: Qt.rgba(1, 1, 1, 0.08) }

            RowLayout {
                Layout.fillWidth: true
                spacing: 0

                Repeater {
                    model: root.days

                    Item {
                        id: dayCell
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        implicitHeight: dayCol.implicitHeight

                        ColumnLayout {
                            id: dayCol
                            anchors.horizontalCenter: parent.horizontalCenter
                            spacing: 1

                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: {
                                    if (dayCell.index === 0)
                                        return "Сегодня";
                                    const n = Qt.locale("ru_RU").dayName(new Date(dayCell.modelData.t).getDay(), Locale.ShortFormat);
                                    return n.charAt(0).toUpperCase() + n.slice(1);
                                }
                                font.pixelSize: 12
                                color: root.dim
                            }
                            Kirigami.Icon {
                                roundToIconSize: false
                                Layout.alignment: Qt.AlignHCenter
                                Layout.preferredWidth: 32
                                Layout.preferredHeight: 32
                                source: root.look(dayCell.modelData.sym).icon
                            }
                            Row {
                                Layout.alignment: Qt.AlignHCenter
                                spacing: 3
                                Text {
                                    text: root.deg(dayCell.modelData.max)
                                    font.pixelSize: 14
                                    color: "white"
                                }
                                Text {
                                    text: root.deg(dayCell.modelData.min)
                                    font.pixelSize: 14
                                    color: root.dim
                                }
                            }
                        }
                    }
                }
            }

            Item { Layout.fillHeight: true }
        }
    }
}
