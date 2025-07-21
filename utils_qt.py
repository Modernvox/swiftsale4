from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QPixmap, QGraphicsOpacityEffect

def show_toast(parent, message: str, duration=3000, icon_path=None):
    """Show a temporary toast message over the parent window with optional icon."""
    toast = QWidget(parent)
    layout = QHBoxLayout()
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(10)

    if icon_path:
        icon_label = QLabel()
        pixmap = QPixmap(icon_path)
        if not pixmap.isNull():
            icon_label.setPixmap(pixmap.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            layout.addWidget(icon_label)

    text_label = QLabel(message)
    text_label.setStyleSheet("color: white; font-size: 12pt;")
    text_label.setFont(QFont("Segoe UI", 10))
    layout.addWidget(text_label)

    toast.setLayout(layout)
    toast.setStyleSheet("""
        QWidget {
            background-color: #444;
            border-radius: 8px;
        }
    """)

    toast.adjustSize()
    width = toast.width()
    height = toast.height()
    parent_center_x = parent.geometry().center().x()
    toast.move(parent_center_x - width // 2, parent.height() - height - 80)

    opacity = QGraphicsOpacityEffect()
    toast.setGraphicsEffect(opacity)
    animation = QPropertyAnimation(opacity, b"opacity")
    animation.setDuration(400)
    animation.setStartValue(0)
    animation.setEndValue(1)
    animation.setEasingCurve(QEasingCurve.InOutQuad)
    animation.start()

    toast.show()
    QTimer.singleShot(duration, toast.deleteLater)

    def fade_out():
        fade = QPropertyAnimation(opacity, b"opacity")
        fade.setDuration(600)
        fade.setStartValue(1)
        fade.setEndValue(0)
        fade.setEasingCurve(QEasingCurve.InOutQuad)
        fade.finished.connect(toast.hide)
        fade.start()

    QTimer.singleShot(duration, fade_out)
