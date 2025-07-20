from PySide6.QtWidgets import QLabel, QGraphicsOpacityEffect
from PySide6.QtCore import QTimer, Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPixmap, QFont

def show_toast(parent, message: str, duration=3000, icon_path=None):
    """Show a temporary toast message over the parent window."""
    toast = QLabel(parent)
    toast.setText(message)
    toast.setStyleSheet("""
        QLabel {
            background-color: #444;
            color: white;
            padding: 10px 16px;
            border-radius: 8px;
            font-size: 12pt;
        }
    """)
    toast.setFont(QFont("Segoe UI", 10))
    toast.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    if icon_path:
        icon = QPixmap(icon_path)
        if not icon.isNull():
            toast.setPixmap(icon.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            toast.setText(f"  {message}")
            toast.setStyleSheet("""
                QLabel {
                    background-color: #444;
                    color: white;
                    padding: 10px 16px;
                    border-radius: 8px;
                    font-size: 12pt;
                    qproperty-alignment: AlignLeft | AlignVCenter;
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

    def fade_out():
        fade = QPropertyAnimation(opacity, b"opacity")
        fade.setDuration(600)
        fade.setStartValue(1)
        fade.setEndValue(0)
        fade.setEasingCurve(QEasingCurve.InOutQuad)
        fade.finished.connect(toast.hide)
        fade.start()

    QTimer.singleShot(duration, fade_out)
