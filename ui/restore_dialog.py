"""One-click restore dialog with per-file version selection."""

from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QScrollArea, QWidget, QMessageBox, QFrame,
    QButtonGroup, QRadioButton, QLineEdit, QComboBox, QTabWidget,
)
from PySide6.QtCore import Qt, Signal

from utils.file_utils import create_file_context_menu


class FileRestoreWidget(QWidget):
    check_changed = Signal()

    def __init__(self, item, backup_root, parent=None):
        super().__init__(parent)
        self.item = item
        self.backup_root = backup_root
        self._version_radios = []

        self.setStyleSheet(
            "FileRestoreWidget { border-bottom: 1px solid #ddd; padding-bottom: 4px; }"
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

    def _show_context_menu(self, position):
        """Show context menu with options to open source/backup directories."""
        source_path = self.item["source_path"]
        backup_path = None
        if self.item["versions"]:
            backup_path = self.item["versions"][0]["path"]
        
        menu = create_file_context_menu(self, source_path, backup_path)
        menu.exec_(self.mapToGlobal(position))

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


class LockedFileRestoreWidget(QWidget):
    """被锁文件恢复控件"""
    check_changed = Signal()

    def __init__(self, item, backup_root, parent=None):
        super().__init__(parent)
        self.item = item
        self.backup_root = backup_root
        self._version_radios = []

        self.setStyleSheet(
            "LockedFileRestoreWidget { border-bottom: 1px solid #ddd; padding-bottom: 4px; "
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
        path_label = QLabel(item["source_path"])
        path_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #E53E3E;")
        path_label.setWordWrap(True)
        top_row.addWidget(path_label, 1)
        outer.addLayout(top_row)

        # 疑似被锁标签
        locked_label = QLabel("疑似被锁")
        locked_label.setStyleSheet("color: #E53E3E; font-size: 12px; font-weight: bold;")
        outer.addWidget(locked_label)

        # 版本选择
        if item.get("versions"):
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

    def is_checked(self):
        return self._check.isChecked()

    def set_checked(self, checked):
        self._check.setChecked(checked)

    def selected_version(self):
        if not self._version_radios:
            return None
        idx = self._radio_group.checkedId()
        if idx < 0 or idx >= len(self.item.get("versions", [])):
            return None
        return self.item["versions"][idx]


class RestoreDialog(QDialog):
    def __init__(self, restorable, unmatched, backup_root, locked_files=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("一键恢复")
        self.setMinimumSize(620, 450)
        self.resize(720, 560)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._restorable = restorable
        self._unmatched = unmatched
        self._locked_files = locked_files or []
        self._backup_root = backup_root
        self._item_widgets = []
        self._locked_item_widgets = []

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self._tab_widget = QTabWidget()
        layout.addWidget(self._tab_widget)

        # Tab 1: 备份恢复
        backup_tab = self._build_backup_tab()
        self._tab_widget.addTab(backup_tab, f"备份恢复 ({len(self._restorable)})")

        # Tab 2: 被锁文件恢复
        if self._locked_files:
            locked_tab = self._build_locked_tab()
            self._tab_widget.addTab(locked_tab, f"被锁文件恢复 ({len(self._locked_files)})")

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

        self._stats_label = QLabel()
        self._stats_label.setStyleSheet("color: #666; font-size: 12px;")
        bottom.addWidget(self._stats_label)

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

        self._tab_widget.currentChanged.connect(self._update_stats)
        self._update_stats()

    def _build_backup_tab(self):
        """构建备份恢复标签页"""
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)

        # 搜索框
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索文件名或路径...")
        self._search_edit.setStyleSheet(
            "QLineEdit { padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; "
            "font-size: 13px; }"
            "QLineEdit:focus { border-color: #3B82F6; }"
        )
        self._search_edit.textChanged.connect(self._apply_filter)
        tab_layout.addWidget(self._search_edit)

        # 过滤和排序
        filter_row = QHBoxLayout()

        filter_row.addWidget(QLabel("文件类型:"))
        self._type_combo = QComboBox()
        self._type_combo.setMinimumWidth(140)
        self._type_combo.addItem("全部")
        ext_counts = {}
        for item in self._restorable:
            ext = Path(item["original_name"]).suffix
            if ext:
                ext_counts[ext] = ext_counts.get(ext, 0) + 1
        for ext, count in sorted(ext_counts.items(), key=lambda x: -x[1]):
            self._type_combo.addItem(f"{ext} ({count})")
        self._type_combo.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self._type_combo)

        filter_row.addSpacing(20)

        filter_row.addWidget(QLabel("排序:"))
        self._sort_combo = QComboBox()
        self._sort_combo.setMinimumWidth(140)
        self._sort_combo.addItems(["时间 降序（新→旧）", "时间 升序（旧→新）"])
        self._sort_combo.currentIndexChanged.connect(self._apply_sort)
        filter_row.addWidget(self._sort_combo)

        filter_row.addStretch()
        tab_layout.addLayout(filter_row)

        # 文件列表
        self._container_layout = QVBoxLayout()
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(0)

        for item in self._restorable:
            item_widget = FileRestoreWidget(item, self._backup_root)
            item_widget.check_changed.connect(self._update_stats)
            self._item_widgets.append(item_widget)
            self._container_layout.addWidget(item_widget)

        self._container_layout.addStretch()

        container = QWidget()
        container.setLayout(self._container_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(container)
        tab_layout.addWidget(scroll, 1)

        # 全选最新版本按钮
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
        tab_layout.addLayout(top_actions)

        return tab

    def _build_locked_tab(self):
        """构建被锁文件恢复标签页"""
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)

        # 说明信息
        info_label = QLabel(
            f"已扫描到被锁文件，并可从备份中恢复：\n"
            f"发现 {len(self._locked_files)} 个文件"
        )
        info_label.setStyleSheet(
            "color: #E53E3E; font-size: 12px; padding: 10px; "
            "background-color: #FFF5F5; border-bottom: 1px solid #E53E3E;"
        )
        info_label.setWordWrap(True)
        tab_layout.addWidget(info_label)

        # 文件列表
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        for item in self._locked_files:
            item_widget = LockedFileRestoreWidget(item, self._backup_root)
            item_widget.check_changed.connect(self._update_stats)
            self._locked_item_widgets.append(item_widget)
            container_layout.addWidget(item_widget)

        container_layout.addStretch()
        scroll.setWidget(container)
        tab_layout.addWidget(scroll, 1)

        return tab

    def _apply_filter(self):
        keyword = self._search_edit.text().lower()
        ext_text = self._type_combo.currentText()
        ext = None if ext_text == "全部" else ext_text.split(" ")[0]

        for w in self._item_widgets:
            name = w.item["original_name"].lower()
            path = w.item["source_path"].lower()
            match_ext = ext is None or name.endswith(ext.lower())
            match_search = not keyword or keyword in name or keyword in path
            w.setVisible(match_ext and match_search)

        self._apply_sort()
        self._update_stats()

    def _apply_sort(self):
        mode = self._sort_combo.currentText()
        reverse = "降序" in mode

        def sort_key(w):
            versions = w.item["versions"]
            if versions:
                return versions[0]["timestamp"]
            return ""

        visible_widgets = [w for w in self._item_widgets if w.isVisible()]
        hidden_widgets = [w for w in self._item_widgets if not w.isVisible()]

        visible_widgets.sort(key=sort_key, reverse=reverse)

        while self._container_layout.count():
            item = self._container_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        for w in visible_widgets:
            self._container_layout.addWidget(w)
        for w in hidden_widgets:
            self._container_layout.addWidget(w)
        self._container_layout.addStretch()

    def _update_stats(self):
        current_tab = self._tab_widget.currentIndex()
        if current_tab == 0:
            widgets = self._item_widgets
            label = "备份恢复"
        else:
            widgets = self._locked_item_widgets
            label = "被锁文件恢复"

        visible = sum(1 for w in widgets if w.isVisible())
        selected = sum(1 for w in widgets if w.isVisible() and w.is_checked())
        total = len(widgets)

        if visible == total:
            self._stats_label.setText(f"{label}: 已选 {selected} / 共 {total} 个文件")
        else:
            self._stats_label.setText(f"{label}: 已选 {selected} / 共 {visible} 个文件（筛选自 {total} 个）")

    def _on_select_all(self):
        current_tab = self._tab_widget.currentIndex()
        if current_tab == 0:
            widgets = self._item_widgets
        else:
            widgets = self._locked_item_widgets
        
        for w in widgets:
            if w.isVisible():
                w.set_checked(True)
        self._update_stats()

    def _on_deselect_all(self):
        current_tab = self._tab_widget.currentIndex()
        if current_tab == 0:
            widgets = self._item_widgets
        else:
            widgets = self._locked_item_widgets
        
        for w in widgets:
            if w.isVisible():
                w.set_checked(False)
        self._update_stats()

    def _on_select_all_latest(self):
        for w in self._item_widgets:
            if w.isVisible():
                w.set_checked(True)

    def _on_restore_selected(self):
        selected = []
        
        # 从备份恢复标签页获取选中项
        for w in self._item_widgets:
            if w.is_checked() and w.selected_version() is not None:
                selected.append((w.item["source_path"], w.selected_version()))
        
        # 从被锁文件恢复标签页获取选中项
        for w in self._locked_item_widgets:
            if w.is_checked() and w.selected_version() is not None:
                selected.append((w.item["source_path"], w.selected_version()))

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
