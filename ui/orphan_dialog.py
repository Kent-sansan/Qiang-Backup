"""Orphan backup cleanup dialog."""

from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QScrollArea, QWidget, QMessageBox, QFrame,
)
from PySide6.QtCore import Qt


class OrphanItemWidget(QWidget):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = item
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        self._check = QCheckBox()
        self._check.setFixedWidth(30)
        layout.addWidget(self._check, alignment=Qt.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        path_label = QLabel(f"{item['relative_dir']}/{item['original_name']}")
        path_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        text_layout.addWidget(path_label)

        archive_dir = item["versions"][0]["path"].parent
        backup_label = QLabel(f"备份位置: {archive_dir}")
        backup_label.setStyleSheet("color: #666; font-size: 12px;")
        text_layout.addWidget(backup_label)

        ts_list = []
        for v in item["versions"]:
            try:
                dt = datetime.strptime(v["timestamp"], "%Y%m%d_%H%M%S")
                ts_list.append(dt.strftime("%Y-%m-%d %H:%M"))
            except ValueError:
                ts_list.append(v["timestamp"])
        versions_label = QLabel(
            f"历史版本 ({item['version_count']}份): {', '.join(ts_list)}"
        )
        versions_label.setStyleSheet("color: #888; font-size: 12px;")
        versions_label.setWordWrap(True)
        text_layout.addWidget(versions_label)

        layout.addLayout(text_layout, 1)

    def is_checked(self):
        return self._check.isChecked()

    def set_checked(self, checked):
        self._check.setChecked(checked)


class OrphanDialog(QDialog):
    def __init__(self, orphans, parent=None):
        super().__init__(parent)
        self.setWindowTitle("孤儿备份清理")
        self.setMinimumSize(580, 400)
        self.resize(680, 500)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._orphans = orphans
        self._item_widgets = []

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        header = QLabel(
            f"检测到 {len(self._orphans)} 个文件的备份，其源文件已不存在。\n"
            "这些备份可能不再需要，请选择是否删除："
        )
        header.setWordWrap(True)
        header.setStyleSheet("font-size: 14px; margin-bottom: 8px;")
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(4)

        for orphan in self._orphans:
            item_widget = OrphanItemWidget(orphan)
            self._item_widgets.append(item_widget)
            container_layout.addWidget(item_widget)

            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet("color: #ddd;")
            container_layout.addWidget(sep)

        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        bottom_layout = QHBoxLayout()

        select_all_btn = QPushButton("全选")
        select_all_btn.setFixedWidth(60)
        select_all_btn.setStyleSheet(
            "QPushButton { font-size: 12px; padding: 3px 10px; border: 1px solid #ccc; "
            "border-radius: 3px; }"
            "QPushButton:hover { background: #e0e0e0; }"
        )
        select_all_btn.clicked.connect(self._on_select_all)
        bottom_layout.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("取消全选")
        deselect_all_btn.setFixedWidth(80)
        deselect_all_btn.setStyleSheet(
            "QPushButton { font-size: 12px; padding: 3px 10px; border: 1px solid #ccc; "
            "border-radius: 3px; }"
            "QPushButton:hover { background: #e0e0e0; }"
        )
        deselect_all_btn.clicked.connect(self._on_deselect_all)
        bottom_layout.addWidget(deselect_all_btn)

        bottom_layout.addStretch()

        keep_btn = QPushButton("全部保留")
        keep_btn.setFixedWidth(100)
        keep_btn.clicked.connect(self.reject)
        bottom_layout.addWidget(keep_btn)

        delete_btn = QPushButton("删除选中")
        delete_btn.setFixedWidth(100)
        delete_btn.setStyleSheet(
            "QPushButton { background-color: #E53E3E; color: white; border: none; "
            "border-radius: 4px; padding: 6px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #C53030; }"
        )
        delete_btn.clicked.connect(self._on_delete_selected)
        bottom_layout.addWidget(delete_btn)

        layout.addLayout(bottom_layout)

    def _on_select_all(self):
        for w in self._item_widgets:
            w.set_checked(True)

    def _on_deselect_all(self):
        for w in self._item_widgets:
            w.set_checked(False)

    def _on_delete_selected(self):
        selected = [w.item for w in self._item_widgets if w.is_checked()]
        if not selected:
            QMessageBox.information(self, "提示", "未选中任何文件。")
            return

        total_versions = sum(item["version_count"] for item in selected)

        reply = QMessageBox.question(
            self, "确认删除",
            f"将删除 {len(selected)} 个文件的 {total_versions} 个备份版本。\n\n"
            "此操作不可恢复，确认删除？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.accept()

    def get_selected(self):
        return [w.item for w in self._item_widgets if w.is_checked()]
