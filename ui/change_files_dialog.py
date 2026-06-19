"""Dialog for viewing and restoring changed/unbacked files."""

from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QScrollArea, QWidget, QMessageBox, QFrame,
    QButtonGroup, QRadioButton, QLineEdit, QComboBox, QTabWidget,
)
from PySide6.QtCore import Qt, Signal

from utils.file_utils import create_file_context_menu


class ChangeFileItemWidget(QWidget):
    check_changed = Signal()

    def __init__(self, file_path, versions=None, is_unbacked=False, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.versions = versions or []
        self.is_unbacked = is_unbacked
        self._version_radios = []

        self.setStyleSheet(
            "ChangeFileItemWidget { border-bottom: 1px solid #ddd; padding-bottom: 4px; }"
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

        path_label = QLabel(file_path)
        path_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        path_label.setWordWrap(True)
        top_row.addWidget(path_label, 1)
        outer.addLayout(top_row)

        if is_unbacked:
            status_label = QLabel("未备份")
            status_label.setStyleSheet("color: #E53E3E; font-size: 12px;")
            outer.addWidget(status_label)
        elif versions:
            self._version_layout = QVBoxLayout()
            self._version_layout.setContentsMargins(30, 0, 0, 0)
            self._version_layout.setSpacing(2)

            self._radio_group = QButtonGroup(self)
            for i, ver in enumerate(versions):
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

            if versions:
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

            count_label = QLabel(f"共 {len(versions)} 个版本")
            count_label.setStyleSheet("color: #888; font-size: 11px;")
            bottom_row.addWidget(count_label)
            bottom_row.addStretch()
            outer.addLayout(bottom_row)

    def _show_context_menu(self, position):
        """Show context menu with options to open source/backup directories."""
        backup_path = None
        if self.versions:
            backup_path = self.versions[0].get("path")
        
        menu = create_file_context_menu(self, self.file_path, backup_path)
        menu.exec_(self.mapToGlobal(position))

    def _on_select_latest(self):
        if self._version_radios:
            self._version_radios[0].setChecked(True)

    def is_checked(self):
        return self._check.isChecked()

    def set_checked(self, checked):
        self._check.setChecked(checked)

    def selected_version(self):
        if not self.versions:
            return None
        idx = self._radio_group.checkedId()
        if idx < 0 or idx >= len(self.versions):
            return None
        return self.versions[idx]


class ChangeFilesDialog(QDialog):
    backup_selected_signal = Signal(list)

    def __init__(self, changed_files, unbacked_files, backup_root, parent=None, title="文件查看"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(620, 450)
        self.resize(720, 560)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._changed_files = changed_files
        self._unbacked_files = unbacked_files
        self._backup_root = backup_root
        self._changed_widgets = []
        self._unbacked_widgets = []

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self._tab_widget = QTabWidget()
        layout.addWidget(self._tab_widget)

        changed_tab = self._build_changed_tab()
        self._tab_widget.addTab(changed_tab, f"变动文件 ({len(self._changed_files)})")

        unbacked_tab = self._build_unbacked_tab()
        self._tab_widget.addTab(unbacked_tab, f"未备份文件 ({len(self._unbacked_files)})")

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

        self._backup_btn = QPushButton("备份选中")
        self._backup_btn.setFixedWidth(100)
        self._backup_btn.setStyleSheet(
            "QPushButton { background-color: #10B981; color: white; border: none; "
            "border-radius: 4px; padding: 6px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #059669; }"
        )
        self._backup_btn.clicked.connect(self._on_backup_selected)
        bottom.addWidget(self._backup_btn)

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

        self._tab_widget.currentChanged.connect(self._update_stats)
        self._update_stats()

    def _build_changed_tab(self):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)

        search_layout = QHBoxLayout()
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("搜索变动文件...")
        search_edit.setStyleSheet(
            "QLineEdit { padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; "
            "font-size: 13px; }"
            "QLineEdit:focus { border-color: #3B82F6; }"
        )
        search_edit.textChanged.connect(lambda text: self._apply_filter(text, self._changed_widgets))
        search_layout.addWidget(search_edit)
        tab_layout.addLayout(search_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        for file_path, versions in self._changed_files:
            item_widget = ChangeFileItemWidget(file_path, versions, is_unbacked=False)
            item_widget.check_changed.connect(self._update_stats)
            self._changed_widgets.append(item_widget)
            container_layout.addWidget(item_widget)

        container_layout.addStretch()
        scroll.setWidget(container)
        tab_layout.addWidget(scroll, 1)

        return tab

    def _build_unbacked_tab(self):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)

        search_layout = QHBoxLayout()
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("搜索未备份文件...")
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
            item_widget = ChangeFileItemWidget(file_path, is_unbacked=True)
            item_widget.check_changed.connect(self._update_stats)
            self._unbacked_widgets.append(item_widget)
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

    def _update_stats(self):
        current_tab = self._tab_widget.currentIndex()
        if current_tab == 0:
            widgets = self._changed_widgets
            label = "变动文件"
        else:
            widgets = self._unbacked_widgets
            label = "未备份文件"

        visible = sum(1 for w in widgets if w.isVisible())
        selected = sum(1 for w in widgets if w.isVisible() and w.is_checked())
        total = len(widgets)

        if visible == total:
            self._stats_label.setText(f"{label}: 已选 {selected} / 共 {total} 个文件")
        else:
            self._stats_label.setText(f"{label}: 已选 {selected} / 共 {visible} 个文件（筛选自 {total} 个）")

    def _on_select_all(self):
        current_tab = self._tab_widget.currentIndex()
        widgets = self._changed_widgets if current_tab == 0 else self._unbacked_widgets
        for w in widgets:
            if w.isVisible():
                w.set_checked(True)
        self._update_stats()

    def _on_deselect_all(self):
        current_tab = self._tab_widget.currentIndex()
        widgets = self._changed_widgets if current_tab == 0 else self._unbacked_widgets
        for w in widgets:
            if w.isVisible():
                w.set_checked(False)
        self._update_stats()

    def _on_restore_selected(self):
        selected = []
        for w in self._changed_widgets:
            if w.is_checked() and not w.is_unbacked:
                version = w.selected_version()
                if version:
                    selected.append((w.file_path, version))

        if not selected:
            QMessageBox.information(self, "提示", "未选中任何可恢复的变动文件。")
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

    def _on_backup_selected(self):
        selected = []
        for w in self._changed_widgets + self._unbacked_widgets:
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

    def get_selected_restore_list(self):
        return getattr(self, "_selected_for_restore", [])
