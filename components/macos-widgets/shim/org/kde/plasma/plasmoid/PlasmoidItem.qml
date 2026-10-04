import QtQuick

// The widget's root: shows its full representation over the whole window.
Item {
    property Component fullRepresentation
    property Component compactRepresentation
    property var preferredRepresentation
    property string toolTipMainText
    property string toolTipSubText

    Loader {
        anchors.fill: parent
        sourceComponent: parent.fullRepresentation
    }
}
