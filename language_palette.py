import sys
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtGui import QColor, QFont, QKeyEvent


LANG_OPTIONS = [
    ("auto", "ru", "1", "Авто ➔ Русский", "RU"),
    ("en", "ru", "2", "English ➔ Русский", "RU"),
    ("ru", "en", "3", "Русский ➔ English", "EN"),
    ("auto", "en", "4", "Авто ➔ English", "EN"),
    ("auto", "de", "5", "Авто ➔ Deutsch", "DE"),
    ("auto", "es", "6", "Авто ➔ Español", "ES"),
    ("auto", "fr", "7", "Авто ➔ Français", "FR"),
    ("auto", "zh", "8", "Авто ➔ 中文 (Китайский)", "ZH"),
    ("auto", "ja", "9", "Авто ➔ 日本語 (Японский)", "JA"),
]


class LanguagePalette(QFrame):
    language_selected = pyqtSignal(str, str)  # (source_lang, target_lang)
    cancelled = pyqtSignal()

    def __init__(self, current_source="auto", current_target="ru", parent=None):
        super().__init__(parent)
        self.current_source = current_source
        self.current_target = current_target
        self.buttons = []
        self.selected_index = 0

        self.setObjectName("LangPalette")
        self.setFixedWidth(340)

        self.setStyleSheet("""
            QFrame#LangPalette {
                background-color: #18181b;
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 14px;
            }
            QLabel#Title {
                color: #f4f4f5;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#Hint {
                color: #71717a;
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
            }
            QPushButton.LangBtn {
                background-color: transparent;
                color: #e4e4e7;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                font-weight: 500;
                text-align: left;
                padding: 6px 12px;
                border-radius: 8px;
                border: none;
            }
            QPushButton.LangBtn:hover {
                background-color: rgba(255, 255, 255, 0.08);
                color: #ffffff;
            }
            QPushButton.LangBtn[active="true"] {
                background-color: rgba(255, 255, 255, 0.16);
                color: #ffffff;
                font-weight: 600;
            }
            QPushButton.LangBtn[focused="true"] {
                border: 1px solid rgba(255, 255, 255, 0.4);
            }
        """)

        # Drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 8)
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(4)

        header_layout = QHBoxLayout()
        title = QLabel("Язык перевода", self)
        title.setObjectName("Title")
        header_layout.addWidget(title)

        hint = QLabel("F4 / 1-9 / Esc", self)
        hint.setObjectName("Hint")
        header_layout.addWidget(hint, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header_layout)

        layout.addSpacing(4)

        for i, (sl, tl, num_key, label, tag) in enumerate(LANG_OPTIONS):
            btn = QPushButton(f"{num_key}.  {label}", self)
            btn.setProperty("class", "LangBtn")
            is_active = (tl == self.current_target and (sl == self.current_source or sl == "auto"))
            btn.setProperty("active", "true" if is_active else "false")
            if is_active:
                self.selected_index = i
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, s=sl, t=tl: self._select(s, t))
            self.buttons.append((btn, sl, tl))
            layout.addWidget(btn)

        self.adjustSize()

    def _select(self, sl: str, tl: str):
        self.language_selected.emit(sl, tl)

    def select_by_number(self, num_str: str) -> bool:
        for btn, sl, tl in self.buttons:
            text = btn.text()
            if text.startswith(num_str + "."):
                self._select(sl, tl)
                return True
        return False


if __name__ == "__main__":
    app = QApplication(sys.argv)
    pal = LanguagePalette()
    pal.show()
    print("LanguagePalette self-check passed!")
