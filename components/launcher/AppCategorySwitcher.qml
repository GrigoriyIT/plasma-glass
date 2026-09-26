import QtQuick
import QtQuick.Controls

// Category sidebar: a vertical list on the left of the app grid, so every
// category name is visible and readable in full.
Item {
    id: scrollview

    property alias model: categorySwitcher.model
    property alias currentIndex: categorySwitcher.currentIndex

    signal categorySwitched(int index)

    ListView {
        id: categorySwitcher
        spacing: 2
        orientation: ListView.Vertical
        interactive: contentHeight > height
        boundsBehavior: Flickable.StopAtBounds
        flickDeceleration: 1500
        clip: true
        highlightMoveDuration: 50
        anchors.fill: parent

        delegate: CategoryPill {
            id: del
            required property var model
            required property var index
            width: categorySwitcher.width
            selected: categorySwitcher.currentIndex == index
            text: model.name

            // Emit on click only: currentIndex also moves when the
            // category list rebuilds, and that must not switch views.
            onClicked: {
                categorySwitcher.currentIndex = index
                scrollview.categorySwitched(model.modelIndex)
            }
        }

        WheelHandler {
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            onWheel: (event) => categorySwitcher.flick(0, event.angleDelta.y * 15)
        }
    }
}
