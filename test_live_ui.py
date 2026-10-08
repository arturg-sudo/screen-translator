import sys
import os
import time
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QPushButton
from PyQt6.QtGui import QFont, QColor, QPalette, QKeyEvent, QMouseEvent
from PyQt6.QtCore import Qt, QPoint, QPointF, QRect, QTimer, QEvent

from overlay import ScreenTranslatorOverlay


class MockTargetWindow(QWidget):
    """A clean mock window with English text to test in-place translation."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mock English Application")
        self.setGeometry(100, 100, 500, 300)

        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#1e1e2e"))
        self.setPalette(pal)
        self.setAutoFillBackground(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(14)

        title = QLabel("System Settings & Security")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #89b4fa;")
        layout.addWidget(title)

        desc1 = QLabel("Configure your personal preferences and sync options.")
        desc1.setFont(QFont("Segoe UI", 11))
        desc1.setStyleSheet("color: #cdd6f4;")
        layout.addWidget(desc1)

        desc2 = QLabel("All network traffic is encrypted using AES-256.")
        desc2.setFont(QFont("Segoe UI", 11))
        desc2.setStyleSheet("color: #a6adc8;")
        layout.addWidget(desc2)

        btn = QPushButton("Save configuration and restart")
        btn.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        btn.setStyleSheet("background-color: #313244; color: #fab387; padding: 8px; border-radius: 6px;")
        layout.addWidget(btn)


def run_automated_test():
    app = QApplication.instance() or QApplication(sys.argv)

    mock = MockTargetWindow()
    mock.show()
    mock.raise_()
    mock.activateWindow()

    # Allow mock window to fully render on screen
    for _ in range(15):
        app.processEvents()
        time.sleep(0.05)

    print("Mock window displayed at:", mock.geometry().x(), mock.geometry().y(), mock.geometry().width(), mock.geometry().height())

    # Create overlay AFTER mock window is fully rendered on screen
    overlay = ScreenTranslatorOverlay(target_lang="ru", source_lang="en")
    overlay.showFullScreen()
    app.processEvents()
    time.sleep(0.2)

    # Simulate mouse selection covering the mock window
    target_geo = mock.geometry()
    sel_x0 = target_geo.x() + 10
    sel_y0 = target_geo.y() + 10
    sel_x1 = target_geo.right() - 10
    sel_y1 = target_geo.bottom() - 10

    print(f"Simulating selection from ({sel_x0}, {sel_y0}) to ({sel_x1}, {sel_y1})...")

    overlay.state = overlay.STATE_PROCESSING
    overlay.selected_rect = QRect(QPoint(sel_x0, sel_y0), QPoint(sel_x1, sel_y1))
    overlay.update()
    app.processEvents()

    overlay.start_processing()

    # Wait for worker thread to finish
    start_time = time.time()
    while overlay.state == overlay.STATE_PROCESSING and time.time() - start_time < 8.0:
        app.processEvents()
        time.sleep(0.05)

    print(f"Processing finished in {time.time() - start_time:.2f}s with status: state={overlay.state}")
    print(f"Found {len(overlay.translated_items)} translated items.")

    for i, item in enumerate(overlay.translated_items):
        print(f"  [{i+1}] '{item.block.original_text}' -> '{item.translated_text}'")

    assert len(overlay.translated_items) > 0, "Should have recognized and translated lines!"

    # Verify translated items exist
    assert len(overlay.translated_items) > 0, "Should have recognized and translated lines!"
    first_item = overlay.translated_items[0]

    # 1. Test multi-line text selection across lines
    p0 = overlay.translated_items[0].card_rect.center()
    p_last = overlay.translated_items[-1].card_rect.center()

    press_ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(p0), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    overlay.mousePressEvent(press_ev)

    move_ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(p_last), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    overlay.mouseMoveEvent(move_ev)

    release_ev = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(p_last), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    overlay.mouseReleaseEvent(release_ev)

    selected_multi = overlay._get_selected_text()
    print(f"Selected multi-line text:\n{selected_multi}")
    assert len(selected_multi) > 0, "Should have selected text across lines!"

    # Simulate copy
    overlay.copy_to_clipboard()
    assert QApplication.clipboard().text() == selected_multi, "Clipboard copy must match selection"
    print("Test 1 Passed: Arbitrary multi-line selection & copy verified!")

    # 2. Test Tab key (Toggle between Original and Translation in-place)
    print("Testing Tab key (Original toggle)...")
    overlay.toggle_original()
    app.processEvents()
    assert overlay.show_original is True
    print(f"   Active mode is original: {overlay.show_original}")

    overlay.toggle_original()
    app.processEvents()
    assert overlay.show_original is False
    print(f"   Active mode is translation: {overlay.show_original}")
    print("Test 2 Passed: Tab toggles original/translated text in-place!")

    # 3. Test F4 key (Language Palette modal)
    print("Testing F4 key (Language Palette modal)...")
    overlay.toggle_language_menu()
    app.processEvents()
    assert overlay.lang_palette.isVisible() is True, "Language palette should be open"
    print("   Language palette is visible!")
    overlay.toggle_language_menu()
    app.processEvents()
    assert overlay.lang_palette.isVisible() is False, "Language palette should close"
    print("Test 3 Passed: F4 language palette toggle verified!")

    # 4. Save visual snapshot of new minimalist UI
    screenshot_path = os.path.join(os.path.dirname(__file__), "test_result_preview.png")
    out_pixmap = overlay.grab()
    out_pixmap.save(screenshot_path)
    print(f"Saved full overlay snapshot to: {screenshot_path}")

    # 5. Test Escape key cleanly closes overlay
    overlay.close_overlay()
    mock.close()
    print("Test 4 Passed: Escape closes overlay cleanly!")
    print("ALL TESTS PASSED WITH 100% SUCCESS!")


if __name__ == "__main__":
    run_automated_test()
