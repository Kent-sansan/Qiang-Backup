"""Windows registry auto-start management."""

import sys
import os
from pathlib import Path

AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
ENTRY_NAME = "QiangGeBackup"


def _get_exe_path():
    if getattr(sys, "frozen", False):
        return sys.executable
    else:
        pythonw = Path(os.path.dirname(sys.executable)) / "pythonw.exe"
        main_script = Path(__file__).resolve().parent.parent / "main.py"
        return f'"{pythonw}" "{main_script}"'


def set_autostart(enabled):
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        )
    except FileNotFoundError:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY)
        winreg.CloseKey(key)
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        )
    try:
        if enabled:
            winreg.SetValueEx(key, ENTRY_NAME, 0, winreg.REG_SZ, _get_exe_path())
        else:
            try:
                winreg.DeleteValue(key, ENTRY_NAME)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def is_autostart_enabled():
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_READ
        )
        try:
            winreg.QueryValueEx(key, ENTRY_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except FileNotFoundError:
        return False
