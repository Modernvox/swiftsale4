# utils_qt.py  — headless-safe utilities
# Pure-Python helpers are import-safe on servers. GUI (Qt) bits are lazy-imported.

from __future__ import annotations

import os
import re
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# Windows-invalid filename characters + control chars
_INVALID = r'[<>:"/\\|?*\x00-\x1F]'

__all__ = [
    "sanitize_filename",
    "safe_default_csv_path",
    "show_toast",
]

def sanitize_filename(name: str, *, default_ext: str = ".csv") -> str:
    """
    Replace Windows-invalid chars and trim trailing spaces/dots.
    Ensures file has `default_ext` if none is present.
    """
    name = re.sub(_INVALID, "_", (name or "")).rstrip(" .")
    root, ext = os.path.splitext(name)
    if not ext:
        name = root + default_ext
    return name

def safe_default_csv_path(stem: str = "bidders_export") -> str:
    """
    Build a Windows-safe default CSV path in %LOCALAPPDATA%/SwiftSaleApp.
    """
    base_dir = os.path.join(
        os.getenv("LOCALAPPDATA", os.path.expanduser("~")),
        "SwiftSaleApp"
    )
    os.makedirs(base_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")  # NO colons/spaces
    filename = sanitize_filename(f"{stem}_{ts}.csv")
    return os.path.join(base_dir, filename)

def _import_qt():
    """
    Lazy-import the Qt pieces only when needed. If unavailable (e.g., on Render),
    return None and callers can no-op gracefully.
    """
    # Optional kill-switch for headless environments
    if os.getenv("HEADLESS", "").lower() in {"1", "true", "yes", "on"}:
        return None

    try:
        from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QGraphicsOpacityEffect
        from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
        from PySide6.QtGui import QPixmap, QFont
        return {
            "QWidget": QWidget,
            "QLabel": QLabel,
            "QHBoxLayout": QHBoxLayout,
            "QGraphicsOpacityEffect": QGraphicsOpacityEffect,
            "Qt": Qt,
            "QTimer": QTimer,
            "QPropertyAnimation": QPropertyAnimation,
            "QEasingCurve": QEasingCurve,
            "QPixmap": QPixmap,
            "QFont": QFont,
        }
    except Exception as e:
        # Don’t crash on servers — just log once and let GUI calls no-op.
        logger.debug("Qt not available for show_toast (this is fine on servers): %s", e)
        return None

def show_toast(parent, message: str, duration: int = 3000, icon_path: str | None = None):
    """
    Show a temporary toast message over the parent window with optional icon.
    - If Qt is unavailable (e.g., headless server), this is a no-op.
    """
    qt = _import_qt()
    if not qt:
        # No-op in headless environments
        return

    QWidget = qt["QWidget"]
    QLabel = qt["QLabel"]
    QHBoxLayout = qt["QHBoxLayout"]
    QGraphicsOpacityEffect = qt["QGraphicsOpacityEffect"]
    Qt = qt["Qt"]
    QTimer = qt["QTimer"]
    QPropertyAnimation = qt["QPropertyAnimation"]
    QEasingCurve = qt["QEasingCurve"]
    QPixmap = qt["QPixmap"]
    QFont = qt["QFont"]

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
    try:
        parent_center_x = parent.geometry().center().x()
        x = parent_center_x - width // 2
        y = parent.height() - height - 80
        toast.move(x, y)
    except Exception:
        # If parent has no geometry yet, just show without positioning
        pass

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
