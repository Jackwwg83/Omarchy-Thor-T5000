// Minimal Quickshell panel for Gate 0b: proves a Qt Quick layer-shell client renders.
import Quickshell
import QtQuick

PanelWindow {
    anchors { top: true; left: true; right: true }
    implicitHeight: 40
    color: "#1e1e2e"

    Text {
        anchors.centerIn: parent
        text: "RaytoneOS · Gate 0b · Quickshell on Jetson Thor"
        color: "#cdd6f4"
        font.pixelSize: 18
    }
}
