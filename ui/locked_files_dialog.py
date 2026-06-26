"""Dialog for displaying detected locked files."""

import ctypes
import ctypes.wintypes
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QScrollArea, QWidget, QMessageBox, QFrame,
)
from PySide6.QtCore import Qt, Signal


# Windows Shell API 结构体（用于发送到回收站）
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
FOF_ALLOWUNDO = 0x0040  # 允许撤销（发送到回收站）
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004


def _send_to_recycle_bin(file_path):
    """发送文件到回收站
    
    Args:
        file_path: 文件路径
        
    Returns:
        bool: 是否成功
    """
    try:
        shfileop = SHFILEOPSTRUCTW()
        shfileop.hwnd = 0
        shfileop.wFunc = FO_DELETE
        shfileop.pFrom = str(file_path) + '\0'  # 双null结尾
        shfileop.pTo = None
        shfileop.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
        
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(shfileop))
        return result == 0
    except Exception as e:
        print(f"发送到回收站失败 {file_path}: {e}")
        return False


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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        top_row = QHBoxLayout()
        self._check = QCheckBox()
        self._check.setFixedWidth(30)
        self._check.stateChanged.connect(self.check_changed.emit)
        top_row.addWidget(self._check, alignment=Qt.AlignTop)

        # 锁定图标
        lock_label = QLabel("🔒")
        lock_label.setStyleSheet("font-size: 14px;")
        top_row.addWidget(lock_label)

        # 文件路径
        path_label = QLabel(file_path)
        path_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #E53E3E;")
        path_label.setWordWrap(True)
        top_row.addWidget(path_label, 1)
        outer.addLayout(top_row)

        # 状态标签
        status_label = QLabel("疑似被锁 - 文件头异常（非标准格式签名），可能是广联达加密锁定导致")
        status_label.setStyleSheet("color: #E53E3E; font-size: 12px;")
        status_label.setWordWrap(True)
        outer.addWidget(status_label)

    def is_checked(self):
        return self._check.isChecked()

    def set_checked(self, checked):
        self._check.setChecked(checked)


class LockedFilesDialog(QDialog):
    """被锁文件对话框"""

    def __init__(self, locked_files, parent=None):
        super().__init__(parent)
        self.setWindowTitle("全盘扫描被锁文件")
        self.setMinimumSize(600, 400)
        self.resize(700, 500)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._locked_files = locked_files or []
        self._locked_widgets = []

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 警告信息
        warning_label = QLabel(
            f"检测到 {len(self._locked_files)} 个疑似被锁文件。\n"
            "这些文件的文件头异常（非标准格式签名），可能是广联达加密锁定导致。\n"
            "被锁文件无法正常打开，备份无意义。"
        )
        warning_label.setStyleSheet(
            "color: #E53E3E; font-size: 12px; padding: 10px; "
            "background-color: #FFF5F5; border: 1px solid #E53E3E; border-radius: 4px;"
        )
        warning_label.setWordWrap(True)
        layout.addWidget(warning_label)

        # 文件列表
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
        layout.addWidget(scroll, 1)

        # 底部按钮
        bottom = QHBoxLayout()

        select_all_btn = QPushButton("全选")
        select_all_btn.setFixedWidth(80)
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

        self._recycle_btn = QPushButton("移入回收站")
        self._recycle_btn.setFixedWidth(120)
        self._recycle_btn.setStyleSheet(
            "QPushButton { background-color: #E53E3E; color: white; border: none; "
            "border-radius: 4px; padding: 6px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #DC2626; }"
        )
        self._recycle_btn.clicked.connect(self._on_recycle_selected)
        bottom.addWidget(self._recycle_btn)

        layout.addLayout(bottom)

        self._update_stats()

    def _update_stats(self):
        selected = sum(1 for w in self._locked_widgets if w.is_checked())
        total = len(self._locked_widgets)
        self._stats_label.setText(f"已选 {selected} / 共 {total} 个文件")

    def _on_select_all(self):
        for w in self._locked_widgets:
            w.set_checked(True)
        self._update_stats()

    def _on_deselect_all(self):
        for w in self._locked_widgets:
            w.set_checked(False)
        self._update_stats()

    def _on_recycle_selected(self):
        """将选中的被锁定文件移入回收站"""
        selected = []
        for w in self._locked_widgets:
            if w.is_checked():
                selected.append(w.file_path)

        if not selected:
            QMessageBox.information(self, "提示", "未选中任何文件。")
            return

        reply = QMessageBox.question(
            self, "确认移入回收站",
            f"将把 {len(selected)} 个被锁文件移入回收站。\n\n确认继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            success_count = 0
            failed_count = 0
            
            for file_path in selected:
                if _send_to_recycle_bin(file_path):
                    success_count += 1
                    # 从列表中移除
                    for w in self._locked_widgets:
                        if w.file_path == file_path:
                            w.setParent(None)
                            self._locked_widgets.remove(w)
                            break
                else:
                    failed_count += 1
            
            if failed_count > 0:
                QMessageBox.warning(
                    self, "操作完成",
                    f"成功移入回收站: {success_count} 个文件\n"
                    f"失败: {failed_count} 个文件"
                )
            else:
                QMessageBox.information(
                    self, "操作完成",
                    f"已成功将 {success_count} 个文件移入回收站。"
                )
            
            self._update_stats()
