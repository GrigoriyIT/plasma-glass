import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import QtQuick.Dialogs
import org.kde.kirigami as Kirigami

Kirigami.FormLayout {
    id: page

    property alias cfg_Image: imagePath.text
    property alias cfg_VerticalPosition: position.value
    property alias cfg_ShowDate: showDate.checked
    property string cfg_ClockFont
    property int cfg_ClockWeight

    readonly property var weights: [
        { text: "Сверхтонкий (Thin)", value: 100 },
        { text: "Ультратонкий (Ultralight)", value: 200 },
        { text: "Тонкий (Light)", value: 300 },
        { text: "Обычный (Regular)", value: 400 },
        { text: "Средний (Medium)", value: 500 },
        { text: "Полужирный (Semibold)", value: 600 }
    ]

    RowLayout {
        Kirigami.FormData.label: "Картинка:"
        QQC2.TextField {
            id: imagePath
            Layout.preferredWidth: Kirigami.Units.gridUnit * 20
        }
        QQC2.Button {
            icon.name: "document-open"
            text: "Выбрать…"
            onClicked: fileDialog.open()
        }
    }

    RowLayout {
        Kirigami.FormData.label: "Положение часов:"
        QQC2.Slider {
            id: position
            from: 10; to: 90; stepSize: 1
            Layout.preferredWidth: Kirigami.Units.gridUnit * 14
        }
        QQC2.Label { text: position.value === 50 ? "по центру" : position.value + "% от верха" }
    }

    QQC2.ComboBox {
        Kirigami.FormData.label: "Шрифт часов:"
        model: ["SF Pro Rounded", "SF Pro Display"]
        currentIndex: Math.max(0, model.indexOf(page.cfg_ClockFont))
        onActivated: page.cfg_ClockFont = currentText
    }

    QQC2.ComboBox {
        Kirigami.FormData.label: "Толщина:"
        model: page.weights
        textRole: "text"
        valueRole: "value"
        currentIndex: Math.max(0, page.weights.findIndex(w => w.value === page.cfg_ClockWeight))
        onActivated: page.cfg_ClockWeight = currentValue
    }

    QQC2.CheckBox {
        id: showDate
        text: "Показывать дату"
    }

    FileDialog {
        id: fileDialog
        title: "Выберите картинку"
        nameFilters: ["Изображения (*.png *.jpg *.jpeg *.webp *.avif *.jxl *.bmp)"]
        onAccepted: imagePath.text = selectedFile
    }
}
