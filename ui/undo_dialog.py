"""Undo backup dialog for selecting and deleting backup batches."""

from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QScrollArea, QWidget, QMessageBox, QFrame,
)
from PySide6.QtCore import Qt


class BatchItemWidget(QWidget):
    def __init__(self, batch, parent=None):
        super().__init__(parent)
        self.batch = batch
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        self._check = QCheckBox()
        self._check.setFixedWidth(30)
        layout.addWidget(self._check, alignment=Qt.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        batch_id = batch["batch_id"]
        try:
            ts_str = batch_id.replace("batch_", "")
            dt = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            display_time = dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            display_time = batch_id

        time_label = QLabel(f"备份时间: {display_time}")
        time_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        text_layout.addWidget(time_label)

        count_label = QLabel(f"文件数量: {batch['count']} 个")
        count_label.setStyleSheet("color: #666; font-size: 12px;")
        text_layout.addWidget(count_label)

        files_text = "\n".join(batch["files"][:5])
        if batch["count"] > 5:
            files_text += f"\n... 还有 {batch['count'] - 5} 个文件"
        files_label = QLabel(files_text)
        files_label.setStyleSheet("color: #888; font-size: 11px;")
        files_label.setWordWrap(True)
        text_layout.addWidget(files_label)

        layout.addLayout(text_layout, 1)

    def is_checked(self):
        return self._check.isChecked()

    def set_checked(self, checked):
        self._check.setChecked(checked)


class UndoDialog(QDialog):
    def __init__(self, batches, parent=None):
        super().__init__(parent)
        self.setWindowTitle("撤销备份")
        self.setMinimumSize(580, 400)
        self.resize(680, 500)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._batches = batches
        self._item_widgets = []

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        header = QLabel(
            f"发现 {len(self._batches)} 个备份批次。\n"
            "选择要撤销的批次（将删除该批次的所有备份文件）："
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

        for batch in self._batches:
            item_widget = BatchItemWidget(batch)
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

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedWidth(80)
        cancel_btn.clicked.connect(self.reject)
        bottom_layout.addWidget(cancel_btn)

        delete_btn = QPushButton("撤销选中")
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
        selected = [w.batch for w in self._item_widgets if w.is_checked()]
        if not selected:
            QMessageBox.information(self, "提示", "未选中任何批次。")
            return

        total_files = sum(b["count"] for b in selected)

        reply = QMessageBox.question(
            self, "确认撤销",
            f"将删除 {len(selected)} 个批次的 {total_files} 个备份文件。\n\n"
            "此操作不可恢复，确认撤销？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._selected_batches = selected
            self.accept()

    def get_selected_batches(self):
        return getattr(self, "_selected_batches", [])
