import QtQuick

// A macOS notification through the host.
QtObject {
    property string componentName
    property string eventId
    property string iconName
    property string title
    property string text
    function sendEvent() {
        host.notify(title, text);
    }
}
