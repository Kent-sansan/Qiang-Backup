"""Dialog for viewing changed files with two tabs: unbacked + locked."""

import ctypes
import ctypes.wintypes
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QScrollArea, QWidget, QMessageBox, QFrame,
    QTabWidget, QLineEdit,
)
from PySide6.QtCore import Qt, Signal

from utils.file_utils import create_file_context_menu


# Windows Shell API — 发送到回收站
class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.wintypes.HWND),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.c_bool),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]

FO_DELETE = 0x0003
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004


def _send_to_recycle_bin(file_path):
    try:
        shfileop = SHFILEOPSTRUCTW()
        shfileop.hwnd = 0
        shfileop.wFunc = FO_DELETE
        shfileop.pFrom = str(file_path) + '\0'
        shfileop.pTo = None
        shfileop.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(shfileop))
        return result == 0
    except Exception as e:
        print(f"发送到回收站失败 {file_path}: {e}")
        return False


class FileItemWidget(QWidget):
    """未备份文件项控件"""
    check_changed = Signal()

    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.setStyleSheet(
            "FileItemWidget { border-bottom: 1px solid #ddd; padding-bottom: 4px; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        top_row = QHBoxLayout()
        self._check = QCheckBox()
        self._check.setFixedWidth(30)
        self._check.stateChanged.connect(self.check_changed.emit)
        top_row.addWidget(self._check, alignment=Qt.AlignTop)

        path_label = QLabel(file_path)
        path_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        path_label.setWordWrap(True)
        top_row.addWidget(path_label, 1)
        outer.addLayout(top_row)

    def is_checked(self):
        return self._check.isChecked()

    def set_checked(self, checked):
        self._check.setChecked(checked)


class LockedFileItemWidget(QWidget):
    """被锁定文件项控件"""
    check_changed = Signal()

    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.setStyleSheet(
            "LockedFileItemWidget { border-bottom: 1px solid #ddd; padding-bottom: 4px; "
            "background-color: #FFF5F5; }"
        )
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        top_row = QHBoxLayout()
        self._check = QCheckBox()
        self._check.setFixedWidth(30)
        self._check.stateChanged.connect(self.check_changed.emit)
        top_row.addWidget(self._check, alignment=Qt.AlignTop)

        lock_label = QLabel("🔒")
        lock_label.setStyleSheet("font-size: 14px;")
        top_row.addWidget(lock_label)

        path_label = QLabel(file_path)
        path_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #E53E3E;")
        path_label.setWordWrap(True)
        top_row.addWidget(path_label, 1)
        outer.addLayout(top_row)

        status_label = QLabel("被锁定 — 无法备份")
        status_label.setStyleSheet("color: #E53E3E; font-size: 12px;")
        outer.addWidget(status_label)

    def _show_context_menu(self, position):
        menu = create_file_context_menu(self, self.file_path)
        menu.exec_(self.mapToGlobal(position))

    def is_checked(self):
        return self._check.isChecked()

    def set_checked(self, checked):
        self._check.setChecked(checked)


class ChangeFilesDialog(QDialog):
    backup_selected_signal = Signal(list)

    def __init__(self, changed_files, unbacked_files, backup_root,
                 locked_files=None, parent=None, title="文件查看"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(620, 450)
        self.resize(720, 560)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._unbacked_files = unbacked_files
        self._locked_files = locked_files or []
        self._backup_root = backup_root
        self._unbacked_widgets = []
        self._locked_widgets = []

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self._tab_widget = QTabWidget()
        layout.addWidget(self._tab_widget)

        # Tab 1: 未备份文件
        unbacked_tab = self._build_unbacked_tab()
        self._tab_widget.addTab(unbacked_tab, f"未备份文件 ({len(self._unbacked_files)})")

        # Tab 2: 被锁定文件
        if self._locked_files:
            locked_tab = self._build_locked_tab()
            self._tab_widget.addTab(locked_tab, f"被锁定文件 ({len(self._locked_files)})")

        bottom = QHBoxLayout()

        select_all_btn = QPushButton("全选当前页")
        select_all_btn.setFixedWidth(90)
        select_all_btn.setStyleSheet(
            "QPushButton { font-size: 12px; padding: 3px 10px; border: 1px solid #ccc; "
            "border-radius: 3px; }"
            "QPushButton:hover { background: #e0e0e0; }"
        )
        select_all_btn.clicked.connect(self._on_select_all)
        bottom.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("取消全选")
        deselect_all_btn.setFixedWidth(80)
        deselect_all_btn.setStyleSheet(
            "QPushButton { font-size: 12px; padding: 3px 10px; border: 1px solid #ccc; "
            "border-radius: 3px; }"
            "QPushButton:hover { background: #e0e0e0; }"
        )
        deselect_all_btn.clicked.connect(self._on_deselect_all)
        bottom.addWidget(deselect_all_btn)

        bottom.addStretch()

        self._stats_label = QLabel()
        self._stats_label.setStyleSheet("color: #666; font-size: 12px;")
        bottom.addWidget(self._stats_label)

        close_btn = QPushButton("关闭")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.reject)
        bottom.addWidget(close_btn)

        # 备份按钮（仅在未备份标签页显示）
        self._backup_btn = QPushButton("备份选中")
        self._backup_btn.setFixedWidth(100)
        self._backup_btn.setStyleSheet(
            "QPushButton { background-color: #10B981; color: white; border: none; "
            "border-radius: 4px; padding: 6px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #059669; }"
        )
        self._backup_btn.clicked.connect(self._on_backup_selected)
        bottom.addWidget(self._backup_btn)

        # 移至回收站按钮（仅在被锁文件标签页显示）
        self._recycle_btn = QPushButton("移至回收站")
        self._recycle_btn.setFixedWidth(120)
        self._recycle_btn.setStyleSheet(
            "QPushButton { background-color: #E53E3E; color: white; border: none; "
            "border-radius: 4px; padding: 6px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #DC2626; }"
        )
        self._recycle_btn.clicked.connect(self._on_recycle_selected)
        self._recycle_btn.setVisible(False)
        bottom.addWidget(self._recycle_btn)

        layout.addLayout(bottom)

        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        self._update_stats()

    def _build_unbacked_tab(self):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)

        search_layout = QHBoxLayout()
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("搜索文件...")
        search_edit.setStyleSheet(
            "QLineEdit { padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; "
            "font-size: 13px; }"
            "QLineEdit:focus { border-color: #3B82F6; }"
        )
        search_edit.textChanged.connect(lambda text: self._apply_filter(text, self._unbacked_widgets))
        search_layout.addWidget(search_edit)
        tab_layout.addLayout(search_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        for file_path in self._unbacked_files:
            item_widget = FileItemWidget(file_path)
            item_widget.check_changed.connect(self._update_stats)
            self._unbacked_widgets.append(item_widget)
            container_layout.addWidget(item_widget)

        container_layout.addStretch()
        scroll.setWidget(container)
        tab_layout.addWidget(scroll, 1)

        return tab

    def _build_locked_tab(self):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)

        warning_label = QLabel("⚠ 以下文件被其他程序锁定，无法备份。可以选择后移至回收站。")
        warning_label.setStyleSheet(
            "color: #E53E3E; font-size: 12px; padding: 8px; "
            "background-color: #FFF5F5; border-bottom: 1px solid #E53E3E;"
        )
        warning_label.setWordWrap(True)
        tab_layout.addWidget(warning_label)

        search_layout = QHBoxLayout()
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("搜索被锁定文件...")
        search_edit.setStyleSheet(
            "QLineEdit { padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; "
            "font-size: 13px; }"
            "QLineEdit:focus { border-color: #E53E3E; }"
        )
        search_edit.textChanged.connect(lambda text: self._apply_filter(text, self._locked_widgets))
        search_layout.addWidget(search_edit)
        tab_layout.addLayout(search_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        for file_path in self._locked_files:
            item_widget = LockedFileItemWidget(file_path)
            item_widget.check_changed.connect(self._update_stats)
            self._locked_widgets.append(item_widget)
            container_layout.addWidget(item_widget)

        container_layout.addStretch()
        scroll.setWidget(container)
        tab_layout.addWidget(scroll, 1)

        return tab

    def _apply_filter(self, keyword, widgets):
        keyword = keyword.lower()
        for w in widgets:
            match = not keyword or keyword in w.file_path.lower()
            w.setVisible(match)
        self._update_stats()

    def _on_tab_changed(self, index):
        """标签页切换时更新按钮显示"""
        is_locked_tab = (index == 1 and len(self._locked_files) > 0)
        self._recycle_btn.setVisible(is_locked_tab)
        self._backup_btn.setVisible(not is_locked_tab)
        self._update_stats()

    def _update_stats(self):
        current_tab = self._tab_widget.currentIndex()
        if current_tab == 0:
            widgets = self._unbacked_widgets
            label = "未备份文件"
        else:
            widgets = self._locked_widgets
            label = "被锁定文件"

        visible = sum(1 for w in widgets if w.isVisible())
        selected = sum(1 for w in widgets if w.isVisible() and w.is_checked())
        total = len(widgets)

        if visible == total:
            self._stats_label.setText(f"{label}: 已选 {selected} / 共 {total} 个文件")
        else:
            self._stats_label.setText(f"{label}: 已选 {selected} / 共 {visible} 个文件（筛选自 {total} 个）")

    def _on_select_all(self):
        current_tab = self._tab_widget.currentIndex()
        widgets = self._unbacked_widgets if current_tab == 0 else self._locked_widgets
        for w in widgets:
            if w.isVisible():
                w.set_checked(True)
        self._update_stats()

    def _on_deselect_all(self):
        current_tab = self._tab_widget.currentIndex()
        widgets = self._unbacked_widgets if current_tab == 0 else self._locked_widgets
        for w in widgets:
            if w.isVisible():
                w.set_checked(False)
        self._update_stats()

    def _on_backup_selected(self):
        selected = []
        for w in self._unbacked_widgets:
            if w.is_checked():
                selected.append(w.file_path)

        if not selected:
            QMessageBox.information(self, "提示", "未选中任何文件。")
            return

        reply = QMessageBox.question(
            self, "确认备份",
            f"将备份 {len(selected)} 个文件。\n\n确认继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.backup_selected_signal.emit(selected)
            self.accept()

    def _on_recycle_selected(self):
        """将选中的被锁定文件移至回收站"""
        selected = []
        for w in self._locked_widgets:
            if w.is_checked():
                selected.append(w.file_path)

        if not selected:
            QMessageBox.information(self, "提示", "未选中任何文件。")
            return

        reply = QMessageBox.question(
            self, "确认移至回收站",
            f"将把 {len(selected)} 个被锁文件移至回收站。\n\n确认继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            success_count = 0
            for file_path in selected:
                if _send_to_recycle_bin(file_path):
                    success_count += 1
                    for w in self._locked_widgets:
                        if w.file_path == file_path:
                            w.setParent(None)
                            self._locked_widgets.remove(w)
                            break
            
            QMessageBox.information(self, "操作完成", f"已成功将 {success_count} 个文件移至回收站。")
            self._update_stats()

    def get_selected_restore_list(self):
        return []
