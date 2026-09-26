import QtQuick
import org.kde.kirigami as Kirigami

Text {
    id: pill

    property bool selected: false
    signal clicked

    topPadding: 7
    bottomPadding: topPadding
    leftPadding: 10
    rightPadding: 8
    font.pointSize: 10
    font.weight: selected ? Font.DemiBold : Font.Normal
    horizontalAlignment: Text.AlignLeft
    elide: Text.ElideRight

    color: main.textColor
    opacity: selected ? 1.0 : (hover.hovered ? 0.9 : 0.72)

    Rectangle {
        anchors.fill: parent
        z: -1
        radius: 6
        color: pill.selected ? Qt.rgba(1, 1, 1, main.isDarkTheme ? 0.14 : 0.55)
             : hover.hovered ? Qt.rgba(1, 1, 1, main.isDarkTheme ? 0.06 : 0.3)
             : "transparent"
    }

    HoverHandler { id: hover }

    MouseArea {
        anchors.fill: pill
        onClicked: pill.clicked();
    }
}
