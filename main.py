import sys
import os
import time
import socket
import threading
import argparse
import atexit
import traceback
import ctypes
import ctypes.wintypes
from PIL import Image, ImageDraw

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import QAbstractNativeEventFilter, QObject, pyqtSignal, QTimer

from overlay import ScreenTranslatorOverlay
from single_instance import acquire_single_instance_lock

# Win32 Constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
WM_HOTKEY = 0x0312

HOTKEYS_CONFIG = [
    (2001, "Alt+Q", MOD_ALT, 0x51),
    (2002, "Ctrl+Shift+S", MOD_CONTROL | MOD_SHIFT, 0x53),
    (2003, "Alt+T", MOD_ALT, 0x54),
    (2004, "Alt+S", MOD_ALT, 0x53),
    (2005, "Alt+X", MOD_ALT, 0x58),
    (2006, "Ctrl+Shift+X", MOD_CONTROL | MOD_SHIFT, 0x58),
]

IPC_PORT = 29173
user32 = ctypes.windll.user32


def generate_tray_icon(path: str):
    """Generate crisp tray icon."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([4, 4, 60, 60], radius=14, fill="#2563EB")
    draw.line([16, 20, 48, 20], fill="#FFFFFF", width=6)
    draw.line([32, 20, 32, 50], fill="#FFFFFF", width=6)
    draw.ellipse([42, 42, 50, 50], fill="#60A5FA")
    img.save(path, format="PNG")


class HotkeyEventFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.registered_ids = {h[0] for h in HOTKEYS_CONFIG}

    def nativeEventFilter(self, eventType, message):
        if eventType in (b"windows_generic_MSG", "windows_generic_MSG"):
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam in self.registered_ids:
                    self.callback()
                    return True, 0
            except Exception:
                pass
        return False, 0


class TranslatorApp(QObject):
    trigger_overlay_signal = pyqtSignal()

    def __init__(self, target_lang="ru", source_lang="auto"):
        super().__init__()
        self.target_lang = target_lang
        self.source_lang = source_lang
        self.current_overlay = None
        self.registered_hotkey_ids = []

        self.trigger_overlay_signal.connect(self.launch_overlay)

        # 1. Start IPC Server for single instance control
        self.start_ipc_server()

        # 2. Setup Tray Icon
        icon_path = os.path.join(os.path.dirname(__file__), "tray_icon.png")
        if not os.path.exists(icon_path):
            generate_tray_icon(icon_path)

        self.tray = QSystemTrayIcon(QIcon(icon_path))
        self.tray.setToolTip("Экранный переводчик (Alt+Q / Ctrl+Shift+S / Alt+T)")

        menu = QMenu()
        act_capture = QAction("📸 Перевести область (Alt+Q / Ctrl+Shift+S / Alt+T)", menu)
        act_capture.triggered.connect(self.launch_overlay)
        menu.addAction(act_capture)

        menu.addSeparator()

        act_exit = QAction("❌ Выход", menu)
        act_exit.triggered.connect(QApplication.instance().quit)
        menu.addAction(act_exit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

        # 3. Register Win32 Global Hotkeys
        for hkid, name, mod, vk in HOTKEYS_CONFIG:
            ok = user32.RegisterHotKey(None, hkid, mod, vk)
            if ok:
                self.registered_hotkey_ids.append(hkid)

        self.native_filter = HotkeyEventFilter(self.on_hotkey_pressed)
        QApplication.instance().installNativeEventFilter(self.native_filter)

    def start_ipc_server(self):
        def server_loop():
            try:
                server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server_sock.bind(("127.0.0.1", IPC_PORT))
                server_sock.listen(5)
                while True:
                    conn, _ = server_sock.accept()
                    data = conn.recv(128)
                    conn.close()
                    if b"TRIGGER" in data:
                        self.trigger_overlay_signal.emit()
            except Exception:
                pass

        t = threading.Thread(target=server_loop, daemon=True)
        t.start()

    def on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.launch_overlay()

    def on_hotkey_pressed(self):
        self.trigger_overlay_signal.emit()

    def launch_overlay(self):
        if self.current_overlay is not None:
            return

        self.current_overlay = ScreenTranslatorOverlay(
            target_lang=self.target_lang,
            source_lang=self.source_lang,
        )
        self.current_overlay.closed.connect(self.on_overlay_closed)
        self.current_overlay.showFullScreen()

    def on_overlay_closed(self):
        if self.current_overlay:
            # Sync any language change back to app state
            self.target_lang = self.current_overlay.target_lang
            self.source_lang = self.current_overlay.source_lang
        self.current_overlay = None

    def cleanup(self):
        if self.tray is not None:
            self.tray.hide()
            self.tray = None
        for hkid in self.registered_hotkey_ids:
            try:
                user32.UnregisterHotKey(None, hkid)
            except Exception:
                pass


def log_unhandled_exception(exc_type, exc_val, exc_tb):
    log_path = os.path.join(os.path.dirname(__file__), "error.log")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n--- Exception at {time.ctime()} ---\n")
            traceback.print_exception(exc_type, exc_val, exc_tb, file=f)
    except Exception:
        pass


def main():
    sys.excepthook = log_unhandled_exception
    parser = argparse.ArgumentParser(description="Win+Shift+S Style Screen Translator")
    parser.add_argument("--now", action="store_true", help="Launch overlay immediately")
    args = parser.parse_args()

    # Enforce strict single-instance lock across the system
    if not acquire_single_instance_lock():
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    translator = TranslatorApp()
    atexit.register(translator.cleanup)

    if args.now:
        QTimer.singleShot(100, translator.launch_overlay)

    def on_exit():
        translator.cleanup()

    app.aboutToQuit.connect(on_exit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
