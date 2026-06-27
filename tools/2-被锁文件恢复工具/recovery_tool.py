"""被锁文件恢复工具 — 从 .cc 备份中恢复被锁的广联达工程文件"""

import sys
import re
import string
import shutil
import subprocess
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFileDialog, QTreeWidget, QTreeWidgetItem,
    QProgressBar, QMessageBox, QCheckBox, QMenu, QHeaderView
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor, QAction

LOCKED_HEADER = b'\x12\x44'
SCAN_PREFIXES = ('.gbq', '.gsh', '.gtj', '.gsc', '.gpv', '.gpb', '.gzb', '.gtb', '.gec', '.gepc', '.gpe', '.gbg')


def open_folder(file_path):
    """在资源管理器中打开文件所在目录并选中"""
    p = Path(file_path)
    if p.exists():
        subprocess.Popen(f'explorer /select,"{p}"')

LOCKED_HEADER = b'\x12\x44'
SCAN_PREFIXES = ('.gbq', '.gsh', '.gtj', '.gsc', '.gpv', '.gpb', '.gzb', '.gtb', '.gec', '.gepc', '.gpe', '.gbg')


class ScanThread(QThread):
    """全盘扫描被锁文件"""
    progress = Signal(str)
    file_found = Signal(str)
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.locked_files = []
        self.running = True

    def stop(self):
        self.running = False

    def _all_drives(self):
        for d in string.ascii_uppercase:
            p = Path(f"{d}:\\")
            if p.exists():
                yield p

    def _is_locked(self, path):
        try:
            with open(path, 'rb') as f:
                return f.read(2) == LOCKED_HEADER
        except OSError:
            return False

    def run(self):
        for drive in self._all_drives():
            if not self.running:
                break
            self.progress.emit(f"扫描 {drive} ...")
            try:
                for f in drive.rglob("*"):
                    if not self.running:
                        break
                    if any("$recycle.bin" in p.lower() for p in f.parts):
                        continue
                    if f.is_file() and any(f.suffix.lower().startswith(p) for p in SCAN_PREFIXES):
                        if self._is_locked(f):
                            self.locked_files.append(str(f))
                            self.file_found.emit(str(f))
            except (OSError, PermissionError):
                pass
        self.finished.emit()


class MatchThread(QThread):
    """按被锁文件名反向查找备份"""
    progress = Signal(str)
    result = Signal(str, str, str, str, bool)  # locked_name, locked_path, source, backup_path, is_locked

    def __init__(self, backup_root, locked_files):
        super().__init__()
        self.backup_root = Path(backup_root)
        self.locked_files = locked_files

    @staticmethod
    def parse_cc_name(filename):
        """解析 .cc 文件名，还原真实名称"""
        name = filename[:-3] if filename.endswith('.cc') else filename
        if '@' in name:
            name, _ = name.rsplit('@', 1)
        name = re.sub(r'\(\d+\)', '', name)
        return name.strip()

    def run(self):
        for i, locked_path in enumerate(self.locked_files):
            locked_name = Path(locked_path).name
            locked_stem = Path(locked_path).stem

            self.progress.emit(f"查找: {locked_name}")

            # 在备份目录中搜索同名 .cc 文件
            candidates = []
            for cc_file in self.backup_root.rglob("*.cc"):
                cc_name = cc_file.name
                try:
                    real_name = self.parse_cc_name(cc_name)
                except Exception:
                    continue

                real_stem = Path(real_name).stem

                # 名称完全匹配 或 stem 匹配
                if real_name != locked_name and real_stem.lower() != locked_stem.lower():
                    # 兼容空格差异
                    if re.sub(r'\s+', '', real_stem.lower()) != re.sub(r'\s+', '', locked_stem.lower()):
                        continue

                date_folder = cc_file.parent.name

                # .cc 即原文件改名，直接读文件头判断是否被锁
                is_locked = False
                try:
                    with open(cc_file, 'rb') as fh:
                        is_locked = fh.read(2) == LOCKED_HEADER
                except OSError:
                    continue

                candidates.append((date_folder, str(cc_file), is_locked))

            if candidates:
                candidates.sort(key=lambda c: c[0], reverse=True)
                for date_folder, cc_path, is_locked in candidates:
                    self.result.emit(locked_name, locked_path, date_folder, cc_path, is_locked)
            else:
                self.result.emit(locked_name, locked_path, "", "", None)  # None = 未找到


class RecoveryDialog(QWidget):
    """恢复工具主界面"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("被锁文件恢复工具")
        self.setMinimumSize(780, 560)
        self._locked_files = []
        self._match_data = {}  # {locked_path: [(source, path, is_locked)]}
        self._scan_thread = None
        self._match_thread = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        title = QLabel("被锁文件恢复工具")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("全盘扫描被锁文件 → 按文件名反向查找备份匹配")
        desc.setStyleSheet("color: #666;")
        layout.addWidget(desc)

        # 备份路径
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("AI工程备份目录:"))
        self._path_edit = QLineEdit("D:\\AI工程备份")
        path_layout.addWidget(self._path_edit)
        browse_btn = QPushButton("浏览...")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)

        # 按钮行
        btn_layout = QHBoxLayout()

        self._scan_btn = QPushButton("1. 全盘扫描被锁文件")
        self._scan_btn.setStyleSheet(
            "QPushButton { background-color: #3B82F6; color: white; padding: 6px 16px; "
            "font-weight: bold; border: none; border-radius: 4px; }"
            "QPushButton:hover { background-color: #2563EB; }"
            "QPushButton:disabled { background-color: #ccc; }"
        )
        self._scan_btn.clicked.connect(self._start_scan)
        btn_layout.addWidget(self._scan_btn)

        self._match_btn = QPushButton("2. 查找匹配备份")
        self._match_btn.setStyleSheet(
            "QPushButton { background-color: #10B981; color: white; padding: 6px 16px; "
            "font-weight: bold; border: none; border-radius: 4px; }"
            "QPushButton:hover { background-color: #059669; }"
            "QPushButton:disabled { background-color: #ccc; }"
        )
        self._match_btn.clicked.connect(self._start_match)
        self._match_btn.setEnabled(False)
        btn_layout.addWidget(self._match_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 状态
        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet("color: #666;")
        layout.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # 结果树
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["被锁文件 / 可恢复版本", "备份来源", "状态"])
        self._tree.setColumnWidth(0, 420)
        self._tree.setColumnWidth(1, 180)
        self._tree.setRootIsDecorated(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        layout.addWidget(self._tree, 1)

        # 底部操作
        bottom = QHBoxLayout()
        self._select_all_cb = QCheckBox("全选可恢复文件")
        self._select_all_cb.stateChanged.connect(self._on_select_all)
        bottom.addWidget(self._select_all_cb)
        bottom.addStretch()

        self._stats_label = QLabel("")
        self._stats_label.setStyleSheet("color: #666;")
        bottom.addWidget(self._stats_label)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        bottom.addWidget(close_btn)

        self._restore_btn = QPushButton("恢复选中")
        self._restore_btn.setStyleSheet(
            "QPushButton { background-color: #3B82F6; color: white; padding: 6px 16px; "
            "font-weight: bold; border: none; border-radius: 4px; }"
            "QPushButton:hover { background-color: #2563EB; }"
            "QPushButton:disabled { background-color: #ccc; }"
        )
        self._restore_btn.clicked.connect(self._on_restore)
        self._restore_btn.setEnabled(False)
        bottom.addWidget(self._restore_btn)

        layout.addLayout(bottom)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "选择 AI工程备份 目录")
        if folder:
            self._path_edit.setText(folder)

    def _start_scan(self):
        self._scan_btn.setEnabled(False)
        self._status_label.setText("全盘扫描中...")
        self._status_label.setStyleSheet("color: #3B82F6; font-weight: bold;")
        self._progress.setVisible(True)
        self._tree.clear()

        self._scan_thread = ScanThread()
        self._scan_thread.progress.connect(lambda m: self._status_label.setText(m))
        self._scan_thread.file_found.connect(lambda f: self._status_label.setText(f"发现: ...{f[-60:]}"))
        self._scan_thread.finished.connect(self._on_scan_done)
        self._scan_thread.start()

    def _on_scan_done(self):
        self._locked_files = self._scan_thread.locked_files
        self._scan_btn.setEnabled(True)
        self._progress.setVisible(False)

        n = len(self._locked_files)
        self._status_label.setText(f"扫描完成：发现 {n} 个被锁文件")
        self._status_label.setStyleSheet(f"color: {'#E53E3E' if n > 0 else '#10B981'}; font-weight: bold;")
        self._match_btn.setEnabled(n > 0)

    def _start_match(self):
        backup_dir = self._path_edit.text().strip()
        if not Path(backup_dir).exists():
            QMessageBox.warning(self, "提示", f"备份目录不存在:\n{backup_dir}")
            return

        self._match_btn.setEnabled(False)
        self._status_label.setText("查找匹配备份中...")
        self._progress.setVisible(True)
        self._tree.clear()
        self._restore_btn.setEnabled(False)
        self._match_data = {}

        self._match_thread = MatchThread(backup_dir, self._locked_files)
        self._match_thread.progress.connect(lambda m: self._status_label.setText(m))
        self._match_thread.result.connect(self._on_match_result)
        self._match_thread.finished.connect(self._on_match_done)
        self._match_thread.start()

    def _on_match_result(self, locked_name, locked_path, source, backup_path, is_locked):
        self._match_data.setdefault(locked_path, []).append((source, backup_path, is_locked))

    def _on_match_done(self):
        self._match_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._build_tree()
        self._update_stats()

    def _build_tree(self):
        self._tree.clear()
        matched = 0

        for locked_path in self._locked_files:
            locked_name = Path(locked_path).name

            root = QTreeWidgetItem([locked_name, locked_path, "🔒 被锁"])
            root.setData(0, Qt.UserRole, locked_path)
            root.setData(1, Qt.UserRole, locked_path)  # 源文件路径供右键使用
            root.setForeground(0, QBrush(QColor("#E53E3E")))
            root.setForeground(1, QBrush(QColor("#666")))

            candidates = self._match_data.get(locked_path, [])

            if not candidates:
                child = QTreeWidgetItem(["", "", "✗ 未找到备份"])
                child.setForeground(2, QBrush(QColor("#888")))
                root.addChild(child)
                root.setDisabled(True)
            else:
                candidates.sort(key=lambda c: c[0] if c[0] else "", reverse=True)
                has_viable = False
                for source, backup_path, is_locked in candidates:
                    if is_locked is None and not backup_path:
                        continue
                    # 修复空白来源：回退用父目录名
                    if not source:
                        source = Path(backup_path).parent.name if backup_path else "未知"
                    if is_locked:
                        status = "✗ 备份亦被锁"
                        color = QColor("#E53E3E")
                    else:
                        status = "✓ 可恢复"
                        color = QColor("#10B981")
                        has_viable = True

                    child = QTreeWidgetItem(["", source, status])
                    child.setForeground(2, QBrush(color))
                    child.setData(1, Qt.UserRole, backup_path)  # 备份路径供右键使用
                    if not is_locked:
                        child.setData(0, Qt.UserRole, backup_path)
                        child.setCheckState(0, Qt.CheckState.Unchecked)
                    else:
                        child.setDisabled(True)
                    root.addChild(child)

            root.setExpanded(True)
            self._tree.addTopLevelItem(root)
            if candidates and has_viable:
                matched += 1

            self._tree.addTopLevelItem(root)

        n = len(self._locked_files)
        self._status_label.setText(f"匹配完成：{matched} 个可恢复，{n - matched} 个无可用备份")
        self._status_label.setStyleSheet("color: #3B82F6; font-weight: bold;")
        self._restore_btn.setEnabled(matched > 0)

    def _update_stats(self):
        total = self._tree.topLevelItemCount()
        selected = 0
        for i in range(total):
            root = self._tree.topLevelItem(i)
            for j in range(root.childCount()):
                child = root.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    selected += 1
        self._stats_label.setText(f"已选 {selected} / 共 {total} 个文件")

    def _on_select_all(self, state):
        checked = state == Qt.CheckState.Checked.value
        for i in range(self._tree.topLevelItemCount()):
            root = self._tree.topLevelItem(i)
            for j in range(root.childCount()):
                child = root.child(j)
                if child.text(2) == "✓ 可恢复":
                    child.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._update_stats()

    def _on_tree_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if not item:
            return
        parent = item.parent()
        menu = QMenu(self)

        # 子节点（备份版本）：可打开备份文件目录
        backup_path = item.data(1, Qt.UserRole)
        if backup_path:
            menu.addAction(QAction("打开备份文件目录", self, triggered=lambda: open_folder(backup_path)))

        # 根节点或子节点：可打开源文件目录
        if parent:
            src_path = parent.data(1, Qt.UserRole)
        else:
            src_path = item.data(1, Qt.UserRole)
        if src_path:
            menu.addAction(QAction("打开源文件目录", self, triggered=lambda: open_folder(src_path)))

        if not menu.isEmpty():
            menu.exec_(self._tree.viewport().mapToGlobal(pos))

    def _on_restore(self):
        selected = []
        for i in range(self._tree.topLevelItemCount()):
            root = self._tree.topLevelItem(i)
            locked_path = root.data(0, Qt.UserRole)
            for j in range(root.childCount()):
                child = root.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    backup_path = child.data(0, Qt.UserRole)
                    if backup_path:
                        selected.append((locked_path, backup_path, child.text(1)))

        if not selected:
            QMessageBox.information(self, "提示", "未选中任何文件。")
            return

        reply = QMessageBox.question(
            self, "确认恢复",
            f"将用选中的备份版本覆盖 {len(selected)} 个被锁文件。\n\n确认继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        restored = 0
        for locked_path, backup_path, date_folder in selected:
            try:
                shutil.copy2(backup_path, locked_path)
                restored += 1
            except Exception as e:
                QMessageBox.warning(self, "恢复失败", f"{Path(locked_path).name}: {e}")

        QMessageBox.information(self, "完成", f"已恢复 {restored} 个文件。")
        self._update_stats()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = RecoveryDialog()
    window.show()
    sys.exit(app.exec())
