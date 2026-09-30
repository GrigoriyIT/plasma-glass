import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import QtLocation
import QtPositioning
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

// Location page: search an address or click the map; the city name is filled in
// from reverse geocoding and can still be edited. Map tiles and geocoding: OpenStreetMap.
KCM.SimpleKCM {
    id: page

    property alias cfg_city: city.text
    property real cfg_latitude
    property real cfg_longitude
    // the config dialog also passes the defaults
    property string cfg_cityDefault
    property real cfg_latitudeDefault
    property real cfg_longitudeDefault

    readonly property string userAgent: "PlasmaGlass-weather/1.0 github.com/GrigoriyIT/plasma-glass"
    property var results: []
    property bool searching: false

    function nominatim(path, onOk) {
        const x = new XMLHttpRequest();
        x.onreadystatechange = function () {
            if (x.readyState !== XMLHttpRequest.DONE)
                return;
            page.searching = false;
            if (x.status === 200) {
                try { onOk(JSON.parse(x.responseText)); } catch (e) { console.warn("weather config:", e); }
            }
        };
        x.open("GET", "https://nominatim.openstreetmap.org/" + path + "&format=json&accept-language=ru");
        x.setRequestHeader("User-Agent", userAgent);
        page.searching = true;
        x.send();
    }

    function search() {
        if (query.text.trim().length < 2)
            return;
        nominatim("search?limit=5&q=" + encodeURIComponent(query.text.trim()), r => results = r);
    }

    function pick(lat, lon, name) {
        cfg_latitude = Math.round(lat * 10000) / 10000;
        cfg_longitude = Math.round(lon * 10000) / 10000;
        if (name) {
            city.text = name;
            return;
        }
        nominatim("reverse?zoom=10&lat=" + lat + "&lon=" + lon, r => {
            const a = r.address || {};
            const n = a.city || a.town || a.village || a.municipality || a.county || a.state;
            if (n)
                city.text = n;
        });
    }

    Kirigami.FormLayout {
        QQC2.TextField {
            id: city
            Kirigami.FormData.label: "Название на карточке:"
        }

        RowLayout {
            Kirigami.FormData.label: "Найти адрес:"
            Layout.fillWidth: true

            QQC2.TextField {
                id: query
                Layout.fillWidth: true
                Layout.minimumWidth: Kirigami.Units.gridUnit * 18
                placeholderText: "Уфа, проспект Октября 100"
                onAccepted: page.search()
            }
            QQC2.Button {
                icon.name: "search"
                text: "Найти"
                enabled: !page.searching
                onClicked: page.search()
            }
        }

        ColumnLayout {
            visible: page.results.length > 0
            Layout.fillWidth: true
            spacing: 0

            Repeater {
                model: page.results

                QQC2.ItemDelegate {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.maximumWidth: Kirigami.Units.gridUnit * 26
                    text: modelData.display_name
                    onClicked: {
                        const lat = parseFloat(modelData.lat), lon = parseFloat(modelData.lon);
                        view.map.center = QtPositioning.coordinate(lat, lon);
                        view.map.zoomLevel = 15;
                        page.pick(lat, lon, "");
                        page.results = [];
                    }
                }
            }
        }

        MapView {
            id: view
            Kirigami.FormData.label: "Точка на карте:"
            implicitWidth: Kirigami.Units.gridUnit * 26
            implicitHeight: Kirigami.Units.gridUnit * 18
            Layout.preferredWidth: implicitWidth
            Layout.preferredHeight: implicitHeight

            map.plugin: Plugin {
                name: "osm"
                PluginParameter { name: "osm.useragent"; value: page.userAgent }
            }
            map.center: QtPositioning.coordinate(page.cfg_latitude, page.cfg_longitude)
            map.zoomLevel: 14

            MapQuickItem {
                id: marker
                coordinate: QtPositioning.coordinate(page.cfg_latitude, page.cfg_longitude)
                anchorPoint.x: pin.width / 2
                anchorPoint.y: pin.height / 2
                sourceItem: Rectangle {
                    id: pin
                    width: 18
                    height: 18
                    radius: 9
                    color: "#0a84ff"
                    border.width: 3
                    border.color: "white"
                }
                Component.onCompleted: view.map.addMapItem(marker)
            }

            TapHandler {
                parent: view.map
                onTapped: eventPoint => {
                    const c = view.map.toCoordinate(eventPoint.position);
                    page.pick(c.latitude, c.longitude, "");
                }
            }
        }

        QQC2.Label {
            Kirigami.FormData.label: "Координаты:"
            text: page.cfg_latitude.toFixed(4) + ", " + page.cfg_longitude.toFixed(4)
            font.family: "monospace"
        }
        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 26
            wrapMode: Text.WordWrap
            opacity: 0.6
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            text: "Щёлкните по карте, чтобы поставить точку. Колесо — масштаб, перетаскивание — сдвиг. Карта © участники OpenStreetMap."
        }
    }
}
