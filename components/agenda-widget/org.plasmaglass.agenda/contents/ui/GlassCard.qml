import QtQuick
import QtQuick.Effects
import org.kde.plasma.plasmoid

// Frosted glass like the dock: the wallpaper under the card, blurred and tinted,
// with a single thin light rim. Desktop widgets are drawn inside the desktop
// window, so KWin cannot blur behind them; the blur is made here from the
// containment's wallpaper item. Without a wallpaper item it falls back to a
// plain translucent card. (Same file in every Plasma Glass desktop widget.)
Item {
    id: card

    property real radius: 16
    readonly property Item backdrop: Plasmoid.containment ? Plasmoid.containment.wallpaperGraphicsObject : null
    property rect area: Qt.rect(0, 0, width, height)

    // where the card sits on the wallpaper; widgets only move in edit mode, so polling is enough
    function track() {
        if (!backdrop)
            return;
        const p = card.mapToItem(backdrop, 0, 0);
        const r = Qt.rect(Math.round(p.x), Math.round(p.y), Math.round(width), Math.round(height));
        if (r.x !== area.x || r.y !== area.y || r.width !== area.width || r.height !== area.height)
            area = r;
    }
    onWidthChanged: track()
    onHeightChanged: track()
    onBackdropChanged: track()
    Component.onCompleted: track()
    Timer {
        interval: 1000
        running: card.visible && card.backdrop !== null
        repeat: true
        onTriggered: card.track()
    }

    ShaderEffectSource {
        id: behind
        anchors.fill: parent
        sourceItem: card.backdrop
        sourceRect: card.area
        live: true
        visible: false
    }
    Item {
        id: shape
        anchors.fill: parent
        layer.enabled: true
        visible: false

        Rectangle {
            anchors.fill: parent
            radius: card.radius
            color: "black"
        }
    }
    MultiEffect {
        anchors.fill: parent
        visible: card.backdrop !== null
        source: behind
        blurEnabled: true
        blurMax: 64
        blur: 1.0
        saturation: 0.1
        maskEnabled: true
        maskSource: shape
    }

    // tint: keeps white text readable on light wallpapers
    Rectangle {
        anchors.fill: parent
        radius: card.radius
        color: Qt.rgba(0.09, 0.09, 0.10, card.backdrop ? 0.52 : 0.64)
    }
    // faint sheen on the upper half, as on the dock glass
    Rectangle {
        anchors.fill: parent
        radius: card.radius
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.07) }
            GradientStop { position: 0.45; color: Qt.rgba(1, 1, 1, 0.0) }
        }
    }
    // the one rim
    Rectangle {
        anchors.fill: parent
        radius: card.radius
        color: "transparent"
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.16)
    }
}
