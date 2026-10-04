import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import "../code/workcal.js" as Work

KCM.SimpleKCM {
    property alias cfg_icsUrls: urls.text
    property alias cfg_days: days.value
    // the config dialog also passes the defaults
    property string cfg_icsUrlsDefault
    property int cfg_daysDefault
    property string cfg_region
    property string cfg_regionDefault

    Kirigami.FormLayout {
        QQC2.TextArea {
            id: urls
            Kirigami.FormData.label: "Ссылки iCal:"
            Layout.fillWidth: true
            Layout.minimumWidth: Kirigami.Units.gridUnit * 24
            implicitHeight: Kirigami.Units.gridUnit * 5
            placeholderText: "https://calendar.google.com/calendar/ical/…/basic.ics"
            wrapMode: TextEdit.WrapAnywhere
        }
        QQC2.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            wrapMode: Text.WordWrap
            opacity: 0.7
            text: "По одной ссылке на строку.\n"
                + "Google: Настройки календаря → Интеграция календаря → «Закрытый адрес в формате iCal».\n"
                + "Яндекс: Настройки календаря → Экспорт → ссылка iCal."
        }
        QQC2.ComboBox {
            id: regionBox
            Kirigami.FormData.label: "Производственный календарь:"
            readonly property var regions: Work.regionNames()
            model: regions.map(r => r.code ? r.name : "Россия (" + r.name + ")")
            currentIndex: Math.max(0, regions.findIndex(r => r.code === cfg_region))
            onActivated: index => cfg_region = regions[index].code
        }
        QQC2.SpinBox {
            id: days
            Kirigami.FormData.label: "Дней вперёд:"
            from: 1
            to: 31
        }
    }
}
