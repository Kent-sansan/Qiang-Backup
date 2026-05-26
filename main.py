"""Qiang Backup -- encrypted file backup tool for engineering software."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QSharedMemory
from PySide6.QtWidgets import QApplication, QMessageBox
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("强哥备份工具")
    app.setOrganizationName("QiangGe")

    lock = QSharedMemory("QiangGeBackupTool_SingleInstance")
    if not lock.create(1):
        QMessageBox.warning(None, "强哥备份", "程序已在运行中。")
        sys.exit(0)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
