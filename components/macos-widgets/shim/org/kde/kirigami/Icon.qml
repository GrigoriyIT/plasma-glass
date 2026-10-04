import QtQuick

// Icons by freedesktop name (weather-clear…) from the host's bundled set, or a URL.
Item {
    id: icon
    property var source
    property bool roundToIconSize: true
    property bool isMask: false
    property color color: "transparent"
    implicitWidth: 22
    implicitHeight: 22

    Image {
        anchors.fill: parent
        fillMode: Image.PreserveAspectFit
        smooth: true
        sourceSize: Qt.size(Math.max(1, width) * 2, Math.max(1, height) * 2)
        source: {
            const s = icon.source ? String(icon.source) : "";
            return !s ? "" : /^[a-z][a-z0-9+.-]*:/i.test(s) || s.startsWith("/") ? s : "image://icon/" + s;
        }
    }
}
