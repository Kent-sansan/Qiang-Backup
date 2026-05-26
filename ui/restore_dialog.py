"""One-click restore dialog with per-file version selection."""

from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QScrollArea, QWidget, QMessageBox, QFrame,
    QButtonGroup, QRadioButton,
)
from PySide6.QtCore import Qt


class FileRestoreWidget(QWidget):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = item
        self._version_radios = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        top_row = QHBoxLayout()
        self._check = QCheckBox()
        self._check.setFixedWidth(30)
        top_row.addWidget(self._check, alignment=Qt.AlignTop)

        path_label = QLabel(item["source_path"])
        path_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        top_row.addWidget(path_label, 1)
        outer.addLayout(top_row)

        self._version_layout = QVBoxLayout()
        self._version_layout.setContentsMargins(30, 0, 0, 0)
        self._version_layout.setSpacing(2)

        self._radio_group = QButtonGroup(self)
        for i, ver in enumerate(item["versions"]):
            radio = QRadioButton()
            self._version_radios.append(radio)
            self._radio_group.addButton(radio, i)

            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(radio)
            try:
                dt = datetime.strptime(ver["timestamp"], "%Y%m%d_%H%M%S")
                label_text = dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                label_text = ver["timestamp"]

            ver_label = QLabel(label_text)
            ver_label.setStyleSheet("font-size: 12px;")
            row.addWidget(ver_label)

            if i == 0:
                suffix = " (最新)"
                latest_label = QLabel(suffix)
                latest_label.setStyleSheet("color: #3B82F6; font-size: 12px;")
                row.addWidget(latest_label)

            row.addStretch()
            self._version_layout.addLayout(row)

        if item["versions"]:
            self._version_radios[0].setChecked(True)

        outer.addLayout(self._version_layout)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(30, 0, 0, 0)
        select_latest_btn = QPushButton("选中最新")
        select_latest_btn.setFixedWidth(70)
        select_latest_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 2px 8px; border: 1px solid #ccc; "
            "border-radius: 3px; background: #f5f5f5; }"
            "QPushButton:hover { background: #e0e0e0; }"
        )
        select_latest_btn.clicked.connect(self._on_select_latest)
        bottom_row.addWidget(select_latest_btn)

        count_label = QLabel(f"共 {len(item['versions'])} 个版本")
        count_label.setStyleSheet("color: #888; font-size: 11px;")
        bottom_row.addWidget(count_label)
        bottom_row.addStretch()
        outer.addLayout(bottom_row)

    def _on_select_latest(self):
        if self._version_radios:
            self._version_radios[0].setChecked(True)

    def is_checked(self):
        return self._check.isChecked()

    def set_checked(self, checked):
        self._check.setChecked(checked)

    def selected_version(self):
        idx = self._radio_group.checkedId()
        if idx < 0 or idx >= len(self.item["versions"]):
            return None
        return self.item["versions"][idx]


class RestoreDialog(QDialog):
    def __init__(self, restorable, unmatched, backup_root, parent=None):
        super().__init__(parent)
        self.setWindowTitle("一键恢复")
        self.setMinimumSize(620, 450)
        self.resize(720, 560)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._restorable = restorable
        self._unmatched = unmatched
        self._backup_root = backup_root
        self._item_widgets = []

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        total_versions = sum(len(item["versions"]) for item in self._restorable)
        header = QLabel(
            f"发现 {len(self._restorable)} 个文件，{total_versions} 个备份版本可恢复\n"
            "选择要恢复的文件并指定版本："
        )
        header.setWordWrap(True)
        header.setStyleSheet("font-size: 14px; margin-bottom: 8px;")
        layout.addWidget(header)

        top_actions = QHBoxLayout()
        select_all_latest_btn = QPushButton("全选最新版本")
        select_all_latest_btn.setFixedWidth(110)
        select_all_latest_btn.setStyleSheet(
            "QPushButton { font-size: 12px; padding: 3px 12px; border: 1px solid #3B82F6; "
            "border-radius: 3px; color: #3B82F6; }"
            "QPushButton:hover { background: #EFF6FF; }"
        )
        select_all_latest_btn.clicked.connect(self._on_select_all_latest)
        top_actions.addWidget(select_all_latest_btn)
        top_actions.addStretch()
        layout.addLayout(top_actions)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(4)

        for item in self._restorable:
            item_widget = FileRestoreWidget(item)
            self._item_widgets.append(item_widget)
            container_layout.addWidget(item_widget)

            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet("color: #ddd;")
            container_layout.addWidget(sep)

        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        bottom = QHBoxLayout()

        select_all_btn = QPushButton("全选")
        select_all_btn.setFixedWidth(60)
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

        unmatched_count = len(self._unmatched)
        if unmatched_count > 0:
            unmatched_label = QLabel(f"匹配不到备份的文件: {unmatched_count} 个")
            unmatched_label.setStyleSheet("color: #888; font-size: 12px;")
            bottom.addWidget(unmatched_label)

            view_btn = QPushButton("查看")
            view_btn.setFixedWidth(50)
            view_btn.setStyleSheet(
                "QPushButton { font-size: 11px; padding: 2px 6px; border: 1px solid #ccc; "
                "border-radius: 3px; }"
                "QPushButton:hover { background: #e0e0e0; }"
            )
            view_btn.clicked.connect(self._on_view_unmatched)
            bottom.addWidget(view_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedWidth(80)
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)

        self._restore_btn = QPushButton("恢复选中")
        self._restore_btn.setFixedWidth(120)
        self._restore_btn.setStyleSheet(
            "QPushButton { background-color: #3B82F6; color: white; border: none; "
            "border-radius: 4px; padding: 6px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #2563EB; }"
        )
        self._restore_btn.clicked.connect(self._on_restore_selected)
        bottom.addWidget(self._restore_btn)

        layout.addLayout(bottom)

    def _on_select_all(self):
        for w in self._item_widgets:
            w.set_checked(True)

    def _on_deselect_all(self):
        for w in self._item_widgets:
            w.set_checked(False)

    def _on_select_all_latest(self):
        for w in self._item_widgets:
            w.set_checked(True)

    def _on_view_unmatched(self):
        text = "以下文件在备份目录中未找到对应的备份版本：\n\n"
        text += "\n".join(self._unmatched)
        QMessageBox.information(self, "未匹配文件列表", text)

    def _on_restore_selected(self):
        selected = [
            (w.item["source_path"], w.selected_version())
            for w in self._item_widgets
            if w.is_checked() and w.selected_version() is not None
        ]
        if not selected:
            QMessageBox.information(self, "提示", "未选中任何文件。")
            return

        reply = QMessageBox.question(
            self, "确认恢复",
            f"将用选中的备份版本覆盖 {len(selected)} 个源文件。\n\n"
            "此操作不可恢复，确认继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._selected_for_restore = selected
            self.accept()

    def get_selected_restore_list(self):
        return getattr(self, "_selected_for_restore", [])
