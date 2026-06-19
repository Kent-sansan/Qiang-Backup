"""File utility functions for context menu operations."""

import subprocess
from pathlib import Path

from PySide6.QtWidgets import QMenu, QWidget
from PySide6.QtGui import QAction


def open_folder(path):
    """Open the folder containing the specified file in Windows Explorer."""
    try:
        path = Path(path)
        if path.exists():
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            subprocess.Popen(f'explorer "{path.parent}"')
    except Exception:
        pass


def create_file_context_menu(widget, source_path, backup_path=None):
    """Create a context menu for file items with options to open source/backup directories.
    
    Args:
        widget: The parent widget for the menu
        source_path: Path to the source file
        backup_path: Path to the backup file (optional)
    
    Returns:
        QMenu: The created context menu
    """
    menu = QMenu(widget)
    
    source_action = QAction("打开源文件所在目录", menu)
    source_action.triggered.connect(lambda: open_folder(source_path))
    menu.addAction(source_action)
    
    if backup_path:
        backup_action = QAction("打开备份文件所在目录", menu)
        backup_action.triggered.connect(lambda: open_folder(backup_path))
        menu.addAction(backup_action)
    
    return menu
