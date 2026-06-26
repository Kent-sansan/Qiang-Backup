"""备份被锁文件自检工具 — GUI版"""

import sys
import tempfile
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFileDialog, QTreeWidget, QTreeWidgetItem,
    QProgressBar, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor

try:
    import py7zr
except ImportError:
    print("请先安装 py7zr：pip install py7zr")
    sys.exit(1)

LOCKED_HEADER = b'\x12\x44'


class ScanThread(QThread):
    progress = Signal(int, int)
    result = Signal(str, str, bool)
    finished = Signal(int, int, int)

    def __init__(self, backup_dir, password=""):
        super().__init__()
        self.backup_dir = Path(backup_dir)
        self.password = password or None

    def check_archive(self, archive_path):
        try:
            with py7zr.SevenZipFile(archive_path, 'r', password=self.password) as szf:
                file_list = szf.getnames()
                if not file_list:
                    return False
                with tempfile.TemporaryDirectory() as tmpdir:
                    szf.extractall(tmpdir)
                    for name in file_list:
                        extracted = Path(tmpdir) / name
                        if extracted.is_file():
                            with open(extracted, 'rb') as f:
                                header = f.read(2)
                            if header == LOCKED_HEADER:
                                return True
                return False
        except Exception:
            return None

    def run(self):
        archives = list(self.backup_dir.rglob("*.7z"))
        total = len(archives)
        locked_count = 0
        error_count = 0
        normal_count = 0

        for i, archive in enumerate(archives, 1):
            relpath = str(archive.relative_to(self.backup_dir))
            result = self.check_archive(archive)

            if result is True:
                self.result.emit(relpath, "⚠ 被锁文件", True)
                locked_count += 1
            elif result is False:
                self.result.emit(relpath, "✓ 正常", False)
                normal_count += 1
            else:
                self.result.emit(relpath, "✗ 读取错误", False)
                error_count += 1

            self.progress.emit(i, total)

        self.finished.emit(normal_count, locked_count, error_count)


class LockChecker(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("备份被锁文件自检工具")
        self.setMinimumSize(680, 480)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        title = QLabel("备份被锁文件自检工具")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("扫描备份目录中的所有 .7z 归档，检查是否混入了被锁文件。")
        desc.setStyleSheet("color: #666;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 备份目录
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("备份目录:"))
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("选择备份目录...")
        path_layout.addWidget(self._path_edit)
        browse_btn = QPushButton("浏览...")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)

        # 密码
        pwd_layout = QHBoxLayout()
        pwd_layout.addWidget(QLabel("加密密码:"))
        self._pwd_edit = QLineEdit()
        self._pwd_edit.setPlaceholderText("默认为 强哥备份")
        self._pwd_edit.setText("强哥备份")
        self._pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        pwd_layout.addWidget(self._pwd_edit)
        show_btn = QPushButton("显示")
        show_btn.setCheckable(True)
        show_btn.toggled.connect(lambda c: self._pwd_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if c else QLineEdit.EchoMode.Password
        ))
        pwd_layout.addWidget(show_btn)
        layout.addLayout(pwd_layout)

        # 按钮
        btn_layout = QHBoxLayout()
        self._scan_btn = QPushButton("开始扫描")
        self._scan_btn.setStyleSheet(
            "QPushButton { background-color: #3B82F6; color: white; padding: 8px 24px; "
            "font-size: 14px; font-weight: bold; border: none; border-radius: 4px; }"
            "QPushButton:hover { background-color: #2563EB; }"
            "QPushButton:disabled { background-color: #ccc; }"
        )
        self._scan_btn.clicked.connect(self._scan)
        btn_layout.addWidget(self._scan_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["备份文件", "状态"])
        self._tree.setColumnWidth(0, 480)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        layout.addWidget(self._tree, 1)

        self._stats_label = QLabel("")
        self._stats_label.setStyleSheet("font-size: 13px;")
        layout.addWidget(self._stats_label)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "选择备份目录")
        if folder:
            self._path_edit.setText(folder)

    def _scan(self):
        backup_dir = self._path_edit.text().strip()
        if not backup_dir:
            QMessageBox.warning(self, "提示", "请先选择备份目录。")
            return

        if not Path(backup_dir).exists():
            QMessageBox.warning(self, "提示", f"目录不存在:\n{backup_dir}")
            return

        self._tree.clear()
        self._scan_btn.setEnabled(False)
        self._progress.setVisible(True)

        self._thread = ScanThread(backup_dir, self._pwd_edit.text())
        self._thread.progress.connect(self._on_progress)
        self._thread.result.connect(self._on_result)
        self._thread.finished.connect(self._on_finished)
        self._thread.start()

    def _on_progress(self, current, total):
        self._progress.setMaximum(total)
        self._progress.setValue(current)

    def _on_result(self, archive_path, status_text, is_locked):
        item = QTreeWidgetItem([archive_path, status_text])
        if is_locked:
            for col in range(2):
                item.setForeground(col, QBrush(QColor("#E53E3E")))
                item.setBackground(col, QBrush(QColor("#FFF5F5")))
        self._tree.insertTopLevelItem(0, item)

    def _on_finished(self, normal, locked, errors):
        self._scan_btn.setEnabled(True)
        self._progress.setVisible(False)

        total = normal + locked + errors
        self._stats_label.setText(
            f"共 {total} 个归档 | 正常: {normal} | "
            f"<span style='color:#E53E3E;font-weight:bold'>被锁: {locked}</span> | 错误: {errors}"
        )

        if locked > 0:
            QMessageBox.warning(
                self, "扫描完成",
                f"发现 {locked} 个备份归档包含被锁文件！\n\n"
                "这些备份的内容可能是无用的锁定状态文件，恢复时请注意。"
            )
        elif errors > 0:
            QMessageBox.warning(
                self, "扫描完成",
                f"扫描完成，但 {errors} 个归档读取失败。\n"
                "请检查密码是否正确。"
            )
        else:
            QMessageBox.information(self, "扫描完成", "✓ 所有备份归档均正常，未发现被锁文件。")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = LockChecker()
    window.show()
    sys.exit(app.exec())
