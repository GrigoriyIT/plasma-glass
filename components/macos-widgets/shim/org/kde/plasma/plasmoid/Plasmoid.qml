pragma Singleton
import QtQuick

// macOS stand-in for Plasma's Plasmoid: the widget's settings come from the host
// (glasswidgets.py) as "host"; there is no containment, the window itself is blurred.
QtObject {
    readonly property QtObject configuration: host.config
    readonly property var containment: null
    readonly property bool systemBlur: true          // GlassCard: the OS blurs behind the card
    // the system Calendar for the agenda: events from host.calendarEvents (PyQt6 slots of
    // a class with signals return nothing to QML), access and changes from hostCalendar
    readonly property QtObject systemCalendar: hostCalendar ? calendar : null
    property QtObject calendar: QtObject {
        readonly property string access: hostCalendar ? hostCalendar.access : ""
        signal changed()
        function events(from, to) { return host.calendarEvents(from, to); }
    }
    property Connections calendarLink: Connections {
        target: hostCalendar
        ignoreUnknownSignals: true
        function onChanged() { calendar.changed(); }
    }
    function internalAction(name) {
        return { trigger: function () { host.action(name); } };
    }
}
