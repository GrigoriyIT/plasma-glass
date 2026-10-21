import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Kirigami.FormLayout {
    id: page

    property real cfg_Latitude
    property real cfg_Longitude
    property alias cfg_Animate: animate.checked
    property alias cfg_VerticalPosition: position.value
    property alias cfg_ShowDate: showDate.checked
    property alias cfg_ClockEverywhere: everywhere.checked

    // Spin boxes work in integers: degrees x 10000.
    component Coord: QQC2.SpinBox {
        stepSize: 100
        editable: true
        textFromValue: (v, locale) => (v / 10000).toFixed(4)
        valueFromText: (t, locale) => Math.round(Number(t.replace(",", ".")) * 10000)
    }

    Coord {
        Kirigami.FormData.label: i18n("Широта:")
        from: -900000; to: 900000
        value: Math.round(page.cfg_Latitude * 10000)
        onValueModified: page.cfg_Latitude = value / 10000
    }
    Coord {
        Kirigami.FormData.label: i18n("Долгота:")
        from: -1800000; to: 1800000
        value: Math.round(page.cfg_Longitude * 10000)
        onValueModified: page.cfg_Longitude = value / 10000
    }
    QQC2.Label {
        text: i18n("Солнце, луна и погода берутся для этой точки (по умолчанию Уфа).")
        font: Kirigami.Theme.smallFont
        opacity: 0.7
    }

    QQC2.CheckBox {
        id: animate
        Kirigami.FormData.label: i18n("Анимация:")
        text: i18n("Падающий дождь и снег, плывущие облака")
    }

    Item { Kirigami.FormData.isSection: true }

    QQC2.SpinBox {
        id: position
        Kirigami.FormData.label: i18n("Часы по вертикали, %:")
        from: 5; to: 95
    }
    QQC2.CheckBox {
        id: showDate
        Kirigami.FormData.label: i18n("Дата:")
        text: i18n("Показывать день недели и число")
    }
    QQC2.CheckBox {
        id: everywhere
        Kirigami.FormData.label: i18n("Панорама:")
        text: i18n("Часы на каждом экране, а не только на среднем")
    }
}
