pragma Singleton
import QtQuick

QtObject {
    readonly property font defaultFont: Qt.font({ pointSize: 13 })
    readonly property font smallFont: Qt.font({ pointSize: 11 })
    readonly property color textColor: "white"
}
