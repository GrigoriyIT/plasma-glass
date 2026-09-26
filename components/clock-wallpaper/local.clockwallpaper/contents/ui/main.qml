import QtQuick
import QtQuick.Effects
import org.kde.plasma.plasmoid

WallpaperItem {
    id: root

    property date now: new Date()

    Image {
        id: background
        anchors.fill: parent
        source: root.configuration.Image
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        sourceSize.width: root.width * Screen.devicePixelRatio
        sourceSize.height: root.height * Screen.devicePixelRatio
        onStatusChanged: root.loading = (status === Image.Loading)
    }

    Column {
        id: clock
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
            font.family: "SF Pro Display"
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

    // Fire right after each minute boundary instead of every second, so the
    // wallpaper repaints (and wakes the GPU) only once a minute.
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

    // Catch up after suspend/resume, when the timer may have been frozen.
    Connections {
        target: Qt.application
        function onStateChanged() {
            root.now = new Date();
            minuteTimer.triggered();
        }
    }
}
