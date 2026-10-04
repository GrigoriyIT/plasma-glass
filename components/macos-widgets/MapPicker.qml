import QtQuick
import QtQuick.Controls

// A small OpenStreetMap: drag to pan, wheel to zoom, click to put the point.
// Tiles come from the host's "tile" image provider (it sends the User-Agent the
// OSM tile policy asks for and caches them). `picker` is the host object.
Rectangle {
    id: map
    width: 760
    height: 560
    color: "#1c1c1e"

    property int zoom: 15
    property real centerX: lon2x(picker.lon, zoom)     // world pixels at this zoom
    property real centerY: lat2y(picker.lat, zoom)
    property real pinLat: picker.lat
    property real pinLon: picker.lon
    readonly property int tiles: Math.pow(2, zoom)

    function lon2x(lon, z) { return (lon + 180) / 360 * 256 * Math.pow(2, z); }
    function lat2y(lat, z) {
        const r = lat * Math.PI / 180;
        return (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * 256 * Math.pow(2, z);
    }
    function x2lon(x, z) { return x / (256 * Math.pow(2, z)) * 360 - 180; }
    function y2lat(y, z) {
        const n = Math.PI - 2 * Math.PI * y / (256 * Math.pow(2, z));
        return 180 / Math.PI * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
    }
    function setZoom(z, px, py) {   // keep the point under the cursor where it is
        z = Math.max(3, Math.min(18, z));
        if (z === zoom)
            return;
        const lon = x2lon(centerX - width / 2 + px, zoom), lat = y2lat(centerY - height / 2 + py, zoom);
        zoom = z;
        centerX = lon2x(lon, z) - px + width / 2;
        centerY = lat2y(lat, z) - py + height / 2;
    }

    readonly property var visibleTiles: {
        const x0 = Math.floor((centerX - width / 2) / 256), x1 = Math.floor((centerX + width / 2) / 256);
        const y0 = Math.max(0, Math.floor((centerY - height / 2) / 256));
        const y1 = Math.min(tiles - 1, Math.floor((centerY + height / 2) / 256));
        const out = [];
        for (let y = y0; y <= y1; y++)
            for (let x = x0; x <= x1; x++)
                out.push({ x: x, y: y });
        return out;
    }

    Item {
        anchors.fill: parent
        clip: true

        Repeater {
            model: map.visibleTiles
            Image {
                required property var modelData
                x: modelData.x * 256 - (map.centerX - map.width / 2)
                y: modelData.y * 256 - (map.centerY - map.height / 2)
                width: 256
                height: 256
                asynchronous: true
                cache: true
                source: "image://tile/" + map.zoom + "/" + (((modelData.x % map.tiles) + map.tiles) % map.tiles) + "/" + modelData.y
            }
        }

        // the point
        Item {
            x: map.lon2x(map.pinLon, map.zoom) - (map.centerX - map.width / 2)
            y: map.lat2y(map.pinLat, map.zoom) - (map.centerY - map.height / 2)
            Rectangle {
                x: -9; y: -9; width: 18; height: 18; radius: 9
                color: "#ff375f"
                border.color: "white"
                border.width: 3
            }
        }

        MouseArea {
            anchors.fill: parent
            property real px; property real py; property bool moved
            onPressed: m => { px = m.x; py = m.y; moved = false; }
            onPositionChanged: m => {
                if (Math.abs(m.x - px) + Math.abs(m.y - py) > 3)
                    moved = true;
                map.centerX -= m.x - px;
                map.centerY -= m.y - py;
                px = m.x; py = m.y;
            }
            onReleased: m => {
                if (moved)
                    return;
                map.pinLon = map.x2lon(map.centerX - map.width / 2 + m.x, map.zoom);
                map.pinLat = map.y2lat(map.centerY - map.height / 2 + m.y, map.zoom);
            }
            onWheel: w => map.setZoom(map.zoom + (w.angleDelta.y > 0 ? 1 : -1), w.x, w.y)
        }
    }

    Text {
        anchors.right: parent.right
        anchors.bottom: bar.top
        anchors.margins: 4
        text: "© OpenStreetMap"
        font.pixelSize: 10
        color: "#333"
    }

    Rectangle {
        id: bar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 48
        color: "#2c2c2e"

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 14
            anchors.verticalCenter: parent.verticalCenter
            text: "Нажмите на карту, чтобы выбрать точку · " + map.pinLat.toFixed(5) + ", " + map.pinLon.toFixed(5)
            color: "white"
            font.pixelSize: 13
        }
        Row {
            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            Button { text: "Отмена"; onClicked: picker.cancel() }
            Button { text: "Готово"; highlighted: true; onClicked: picker.accept(map.pinLat, map.pinLon) }
        }
    }
}
