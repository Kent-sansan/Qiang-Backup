"""扫描 .cc 备份文件头，识别被锁文件 — GUI 版"""

import sys
from pathlib import Path
from collections import Counter

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFileDialog, QTreeWidget, QTreeWidgetItem,
    QProgressBar, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor

LOCKED = b'\x12\x44'


class ScanThread(QThread):
    progress = Signal(int, int)
    result = Signal(str, str, str)  # filepath, header_type, date_folder
    finished = Signal(object)      # Counter

    def __init__(self, root_dir):
        super().__init__()
        self.root = Path(root_dir)

    def run(self):
        files = list(self.root.rglob("*.cc"))
        total = len(files)
        counts = Counter()

        for i, f in enumerate(files, 1):
            try:
                with open(f, 'rb') as fh:
                    header = fh.read(2)
            except OSError:
                continue

            rel = str(f.relative_to(self.root))
            date_folder = f.parent.name

            if header == LOCKED:
                counts["被锁"] += 1
                self.result.emit(rel, "LOCKED", date_folder)
            elif header == b'\x50\x4b':
                counts["ZIP"] += 1
                self.result.emit(rel, "ZIP", date_folder)
            elif header == b'\x37\x7a':
                counts["7z"] += 1
                self.result.emit(rel, "7z", date_folder)
            else:
                counts["其他"] += 1
                self.result.emit(rel, header.hex(' '), date_folder)

            self.progress.emit(i, total)

        self.finished.emit(counts)


class CCScanner(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CC 文件头扫描工具")
        self.setMinimumSize(720, 520)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        title = QLabel("CC 文件头扫描工具")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("扫描备份目录中所有 .cc 文件的文件头，识别被锁文件（12 44 头）")
        desc.setStyleSheet("color: #666;")
        layout.addWidget(desc)

        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("扫描目录:"))
        self._path_edit = QLineEdit("D:\\AI工程备份")
        path_layout.addWidget(self._path_edit)
        browse_btn = QPushButton("浏览...")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)

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
        self._tree.setHeaderLabels(["文件路径", "备份来源", "文件头类型"])
        self._tree.setColumnWidth(0, 420)
        self._tree.setColumnWidth(1, 160)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        layout.addWidget(self._tree, 1)

        self._stats_label = QLabel("")
        self._stats_label.setStyleSheet("font-size: 13px;")
        layout.addWidget(self._stats_label)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "选择扫描目录")
        if folder:
            self._path_edit.setText(folder)

    def _scan(self):
        path = self._path_edit.text().strip()
        if not Path(path).exists():
            QMessageBox.warning(self, "提示", f"目录不存在:\n{path}")
            return

        self._tree.clear()
        self._scan_btn.setEnabled(False)
        self._progress.setVisible(True)

        self._thread = ScanThread(path)
        self._thread.progress.connect(self._on_progress)
        self._thread.result.connect(self._on_result)
        self._thread.finished.connect(self._on_finished)
        self._thread.start()

    def _on_progress(self, current, total):
        self._progress.setMaximum(total)
        self._progress.setValue(current)

    def _on_result(self, filepath, header_type, date_folder):
        item = QTreeWidgetItem([filepath, date_folder, header_type])
        if header_type == "LOCKED":
            for col in range(3):
                item.setForeground(col, QBrush(QColor("#E53E3E")))
                item.setBackground(col, QBrush(QColor("#FFF5F5")))
        elif header_type == "ZIP":
            item.setForeground(2, QBrush(QColor("#10B981")))
        elif header_type == "7z":
            item.setForeground(2, QBrush(QColor("#3B82F6")))
        self._tree.insertTopLevelItem(0, item)

    def _on_finished(self, counts):
        self._scan_btn.setEnabled(True)
        self._progress.setVisible(False)

        total = sum(counts.values())
        parts = []
        locked = counts.get("被锁", 0)
        if locked:
            parts.append(f"<span style='color:#E53E3E;font-weight:bold'>被锁: {locked}</span>")
        if counts.get("ZIP"):
            parts.append(f"<span style='color:#10B981'>ZIP: {counts['ZIP']}</span>")
        if counts.get("7z"):
            parts.append(f"<span style='color:#3B82F6'>7z: {counts['7z']}</span>")
        if counts.get("其他"):
            parts.append(f"其他: {counts['其他']}")
        parts.insert(0, f"共 {total} 个 .cc 文件")

        self._stats_label.setText(" | ".join(parts))

        if locked > 0:
            self._save_locked()
            QMessageBox.warning(
                self, "扫描完成",
                f"发现 {locked} 个被锁文件（头 12 44）。\n\n"
                f"文件列表已保存到 locked_cc_files.txt"
            )
        else:
            QMessageBox.information(self, "扫描完成", "未发现被锁文件，所有备份均正常。")

    def _save_locked(self):
        locked = []
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.text(2) == "LOCKED":
                locked.append(f"{item.text(0)}\t{item.text(1)}")
        if locked:
            with open("locked_cc_files.txt", "w") as f:
                f.write("\n".join(locked))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = CCScanner()
    window.show()
    sys.exit(app.exec())
