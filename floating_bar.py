import sys
from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtGui import QColor, QFont, QCursor


class FloatingMiniBar(QFrame):
    capture_requested = pyqtSignal()
    toggle_lang_requested = pyqtSignal()
    hide_requested = pyqtSignal()

    def __init__(self, current_lang_pair="EN ➔ RU"):
        super().__init__()
        self.drag_position = QPoint()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.setObjectName("MiniBar")
        self.setStyleSheet("""
            QFrame#MiniBar {
                background-color: #1e1e24;
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 22px;
            }
            QPushButton {
                background-color: transparent;
                color: #f4f4f5;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                font-weight: 600;
                border: none;
                border-radius: 16px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.12);
            }
            QPushButton#CaptureBtn {
                background-color: #2563eb;
                color: #ffffff;
            }
            QPushButton#CaptureBtn:hover {
                background-color: #1d4ed8;
            }
            QPushButton#CloseBtn {
                color: #a1a1aa;
                font-weight: bold;
                padding: 6px 10px;
            }
            QPushButton#CloseBtn:hover {
                background-color: rgba(239, 68, 68, 0.2);
                color: #ef4444;
            }
        """)

        # Shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 8, 5)
        layout.setSpacing(6)

        # Drag handle indicator
        self.lbl_drag = QLabel("⋮⋮")
        self.lbl_drag.setStyleSheet("color: #71717a; font-size: 14px; margin-right: 2px;")
        self.lbl_drag.setToolTip("Перетащите панель в любое место")
        layout.addWidget(self.lbl_drag)

        # Capture button
        self.btn_capture = QPushButton("📸 Перевести (Ctrl+Shift+S)")
        self.btn_capture.setObjectName("CaptureBtn")
        self.btn_capture.setToolTip("Выделить область (Ctrl+Shift+S или Alt+T)")
        self.btn_capture.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_capture.clicked.connect(self.capture_requested.emit)
        layout.addWidget(self.btn_capture)

        # Language toggle button
        self.btn_lang = QPushButton(current_lang_pair)
        self.btn_lang.setToolTip("Сменить направление перевода")
        self.btn_lang.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_lang.clicked.connect(self.toggle_lang_requested.emit)
        layout.addWidget(self.btn_lang)

        # Minimize to tray button
        self.btn_hide = QPushButton("—")
        self.btn_hide.setObjectName("CloseBtn")
        self.btn_hide.setToolTip("Свернуть в трей")
        self.btn_hide.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_hide.clicked.connect(self.hide_requested.emit)
        layout.addWidget(self.btn_hide)

        self.adjustSize()

    def update_lang_label(self, label: str):
        self.btn_lang.setText(label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and not self.drag_position.isNull():
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
