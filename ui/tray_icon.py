"""System tray icon for Qiang Backup."""

import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QObject, Signal


def _find_icon():
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent
    icon = base / "icon.ico"
    if icon.exists():
        return str(icon)
    return None


class TrayIcon(QObject):
    show_window_signal = Signal()
    manual_backup_signal = Signal()
    start_monitor_signal = Signal()
    stop_monitor_signal = Signal()
    quit_signal = Signal()
    autostart_toggled_signal = Signal(bool)

    def __init__(self, icon_path=None):
        super().__init__()
        resolved = icon_path or _find_icon()
        self._icon = QIcon(resolved) if resolved else QIcon()
        self._tray = QSystemTrayIcon(self._icon)
        self._tray.setToolTip("Qiang Backup")
        self._tray.activated.connect(self._on_activated)

        self._last_message_time = 0
        self._last_message_key = ""

        self._menu = None
        self._show_action = None
        self._backup_action = None
        self._start_action = None
        self._stop_action = None
        self._autostart_action = None
        self._quit_action = None
        self._build_menu()

    def _build_menu(self):
        self._menu = QMenu()

        self._show_action = QAction("显示主窗口", self._menu)
        self._show_action.triggered.connect(self.show_window_signal.emit)
        self._menu.addAction(self._show_action)
        self._menu.addSeparator()

        self._backup_action = QAction("手动备份", self._menu)
        self._backup_action.triggered.connect(self.manual_backup_signal.emit)
        self._menu.addAction(self._backup_action)
        self._menu.addSeparator()

        self._start_action = QAction("开始监控", self._menu)
        self._start_action.triggered.connect(self.start_monitor_signal.emit)
        self._menu.addAction(self._start_action)

        self._stop_action = QAction("停止监控", self._menu)
        self._stop_action.triggered.connect(self.stop_monitor_signal.emit)
        self._menu.addAction(self._stop_action)
        self._menu.addSeparator()

        self._autostart_action = QAction("开机自启", self._menu)
        self._autostart_action.setCheckable(True)
        self._autostart_action.triggered.connect(
            lambda checked: self.autostart_toggled_signal.emit(checked)
        )
        self._menu.addAction(self._autostart_action)
        self._menu.addSeparator()

        self._quit_action = QAction("退出", self._menu)
        self._quit_action.triggered.connect(self.quit_signal.emit)
        self._menu.addAction(self._quit_action)

        self._tray.setContextMenu(self._menu)

    def set_autostart_checked(self, checked):
        self._autostart_action.setChecked(checked)

    def set_monitoring_active(self, active):
        self._start_action.setEnabled(not active)
        self._stop_action.setEnabled(active)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_window_signal.emit()

    def show(self):
        self._tray.setContextMenu(self._menu)
        self._tray.show()

    def hide(self):
        self._tray.hide()

    def show_message(self, title, message, icon=QSystemTrayIcon.Information):
        key = f"{title}|{message}"
        now = time.monotonic()
        if key == self._last_message_key and now - self._last_message_time < 5:
            return
        self._last_message_key = key
        self._last_message_time = now
        self._tray.showMessage(title, message, icon, 3000)
