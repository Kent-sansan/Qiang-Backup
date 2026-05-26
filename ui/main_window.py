"""Main window for Qiang Backup."""

import os
import sys
import time
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLineEdit, QListWidget, QTextEdit, QPlainTextEdit,
    QLabel, QSpinBox, QCheckBox, QFileDialog, QMessageBox,
    QProgressDialog, QStatusBar, QSystemTrayIcon, QDialog,
    QApplication,
)
from PySide6.QtCore import Qt, QThreadPool, Signal, QObject, QRunnable, QMutex
from PySide6.QtGui import QFont, QCloseEvent, QIcon

from ui.tray_icon import TrayIcon
from engine.config import load_config, save_config
from engine.change_detector import get_dirty_files
from engine.backup_engine import backup_folder
from engine.restore_engine import find_restorable_files, restore_single_file
from engine.file_watcher import FileWatcher
from engine.reconciliation import (
    find_orphaned_backups, check_backup_integrity,
    delete_orphan_versions, delete_corrupted_backups,
)
from engine.backup_log import log_scan
from utils.autostart import set_autostart


class LogSignals(QObject):
    log_signal = Signal(str)
    status_signal = Signal(str)


class ScanSignals(QObject):
    progress = Signal(str)
    file_count = Signal(int)
    finished = Signal(object, float)


class ScanWorker(QRunnable):
    def __init__(self, source_folders, backup_root, extensions, signals):
        super().__init__()
        self.source_folders = source_folders
        self.backup_root = backup_root
        self.extensions = extensions
        self.signals = signals
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        results = {}
        total = 0
        file_counter = [0]
        start = time.monotonic()

        def on_file(f):
            file_counter[0] += 1
            if file_counter[0] % 5 == 0:
                self.signals.file_count.emit(file_counter[0])

        try:
            for folder in self.source_folders:
                if self._cancelled:
                    break
                self.signals.progress.emit(f"正在扫描 {folder}...")
                dirty = get_dirty_files(folder, self.backup_root, self.extensions, progress_cb=on_file)
                if self._cancelled:
                    break
                if dirty:
                    results[folder] = dirty
                    total += len(dirty)
        except Exception:
            pass
        elapsed = time.monotonic() - start
        if not self._cancelled:
            self.signals.finished.emit(results, elapsed)


class BackupWorker(QRunnable):
    def __init__(self, folder, backup_root, extensions, password,
                 files, max_versions, signals, on_folder_done=None):
        super().__init__()
        self.folder = folder
        self.backup_root = backup_root
        self.extensions = extensions
        self.password = password
        self.files = files
        self.max_versions = max_versions
        self.signals = signals
        self._on_folder_done = on_folder_done

    def run(self):
        try:
            def on_progress(i, total, fname):
                self.signals.status_signal.emit(f"备份: {i}/{total} — {fname}")

            def on_file_done(ok, filepath):
                if ok:
                    self.signals.log_signal.emit(f"  ✅ {filepath}")
                else:
                    self.signals.log_signal.emit(f"  ❌ {filepath}")

            success, total_files = backup_folder(
                Path(self.folder), Path(self.backup_root), self.extensions,
                self.password, files=self.files, max_versions=self.max_versions,
                progress_cb=on_progress, file_done_cb=on_file_done,
            )
            self.signals.status_signal.emit("就绪")
        finally:
            if self._on_folder_done:
                self._on_folder_done()


class OrphanScanSignals(QObject):
    result = Signal(object)


class OrphanScanWorker(QRunnable):
    def __init__(self, source_folders, backup_root, extensions, signals):
        super().__init__()
        self.source_folders = source_folders
        self.backup_root = backup_root
        self.extensions = extensions
        self.signals = signals
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            orphans = find_orphaned_backups(
                self.source_folders, self.backup_root, self.extensions
            )
        except Exception:
            orphans = []
        if not self._cancelled:
            self.signals.result.emit(orphans)


class RestoreScanSignals(QObject):
    result = Signal(object, object)


class RestoreScanWorker(QRunnable):
    def __init__(self, source_folders, backup_root, extensions, signals):
        super().__init__()
        self.source_folders = source_folders
        self.backup_root = backup_root
        self.extensions = extensions
        self.signals = signals

    def run(self):
        try:
            restorable, unmatched = find_restorable_files(
                self.source_folders, self.backup_root, self.extensions
            )
            self.signals.result.emit(restorable, unmatched)
        except Exception:
            self.signals.result.emit([], [])


class RestoreTaskSignals(QObject):
    log = Signal(str)
    status = Signal(str)
    finished = Signal(int, int)


class RestoreTaskWorker(QRunnable):
    def __init__(self, selected, password, signals):
        super().__init__()
        self.selected = selected
        self.password = password
        self.signals = signals

    def run(self):
        success = 0
        failed = 0
        total = len(self.selected)
        for i, (source_path, version) in enumerate(self.selected, 1):
            archive = version["path"]
            fname = Path(source_path).name
            self.signals.status.emit(f"恢复: {i}/{total} — {fname}")
            if restore_single_file(archive, source_path, self.password):
                self.signals.log.emit(f"✅ 已恢复: {source_path} ← {version['timestamp']}")
                success += 1
            else:
                self.signals.log.emit(f"❌ 恢复失败: {source_path}")
                failed += 1
        self.signals.finished.emit(success, failed)


class IntegrityScanSignals(QObject):
    result = Signal(object)


class IntegrityScanWorker(QRunnable):
    def __init__(self, backup_root, extensions, password, signals):
        super().__init__()
        self.backup_root = backup_root
        self.extensions = extensions
        self.password = password
        self.signals = signals
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            corrupted = check_backup_integrity(
                self.backup_root, self.extensions, self.password
            )
        except Exception:
            corrupted = []
        if not self._cancelled:
            self.signals.result.emit(corrupted)


class MainWindow(QMainWindow):
    _show_complete_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("强哥备份工具")
        self.resize(680, 560)
        self.setMinimumSize(600, 480)

        if getattr(sys, "frozen", False):
            icon_path = Path(sys._MEIPASS) / "icon.ico"
        else:
            icon_path = Path(__file__).resolve().parent.parent / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._signals = LogSignals()
        self._signals.log_signal.connect(self._append_log)
        self._signals.status_signal.connect(self._set_status)

        self._show_complete_signal.connect(
            lambda msg: QMessageBox.information(self, "完成", msg)
        )

        self._config = load_config()
        self._watcher = FileWatcher()
        self._threadpool = QThreadPool()
        self._threadpool.setMaxThreadCount(4)
        self._manual_pending = 0
        self._manual_total = 0
        self._manual_scan_running = False
        self._orphan_scan_running = False
        self._integrity_scan_running = False
        self._restoring = False
        self._quitting = False
        self._restore_msg_shown = False
        self._autostart_syncing = False
        self._orphan_dialog = None
        self._integrity_dialog = None
        self._restore_progress = None

        self._tray = TrayIcon()
        self._setup_tray_signals()

        self._build_ui()
        self._load_config_to_ui()

        source_folders = self._config.get("source_folders", [])
        backup_root = self._config.get("backup_root", "")
        extensions = self._config.get("extensions", [])
        valid = [f for f in source_folders if Path(f).exists()]

        if valid and backup_root and extensions:
            self._show_startup_load(valid, backup_root, extensions)
        else:
            self._finish_startup()

    def _show_startup_load(self, valid, backup_root, extensions):
        dlg = QDialog(self)
        dlg.setWindowTitle("强哥备份 — 启动中")
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        dlg.setFixedSize(380, 140)

        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.addWidget(QLabel("正在扫描文件变更，请稍候…"))

        count_label = QLabel("已扫描 0 个文件")
        dlg_layout.addWidget(count_label)

        quit_btn = QPushButton("关闭程序")
        quit_btn.clicked.connect(lambda: (QApplication.instance().quit(), os._exit(0)))
        dlg_layout.addWidget(quit_btn)

        scan_signals = ScanSignals()

        def on_count(n):
            count_label.setText(f"已扫描 {n} 个文件")

        def on_finished(results, elapsed):
            dlg.accept()
            self._on_startup_scan_done(results, elapsed)
            self._finish_startup()

        scan_signals.file_count.connect(on_count)
        scan_signals.finished.connect(on_finished)

        worker = ScanWorker(valid, backup_root, extensions, scan_signals)
        self._threadpool.start(worker)
        dlg.show()

    def _finish_startup(self):
        self._tray.show()

        if self._config.get("autostart", False):
            set_autostart(True)

        self.show()
        self.show_and_focus()

    def _setup_tray_signals(self):
        self._tray.show_window_signal.connect(self.show_and_focus)
        self._tray.manual_backup_signal.connect(self._on_manual_backup)
        self._tray.start_monitor_signal.connect(self._on_start_monitor)
        self._tray.stop_monitor_signal.connect(self._on_stop_monitor)
        self._tray.quit_signal.connect(self._on_quit)
        self._tray.autostart_toggled_signal.connect(self._on_autostart_toggled)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        settings_box = QGroupBox("设置")
        settings_layout = QVBoxLayout(settings_box)

        src_layout = QHBoxLayout()
        src_layout.addWidget(QLabel("源文件夹:"))
        self._source_list = QListWidget()
        self._source_list.setMaximumHeight(80)
        src_layout.addWidget(self._source_list, 1)
        btn_layout = QVBoxLayout()
        self._btn_add_src = QPushButton("添加")
        self._btn_del_src = QPushButton("删除")
        self._btn_add_src.clicked.connect(self._on_add_source)
        self._btn_del_src.clicked.connect(self._on_del_source)
        btn_layout.addWidget(self._btn_add_src)
        btn_layout.addWidget(self._btn_del_src)
        btn_layout.addStretch()
        src_layout.addLayout(btn_layout)
        settings_layout.addLayout(src_layout)

        root_layout = QHBoxLayout()
        root_layout.addWidget(QLabel("备份路径:"))
        self._backup_root_edit = QLineEdit()
        root_layout.addWidget(self._backup_root_edit, 1)
        self._btn_browse_root = QPushButton("浏览")
        self._btn_browse_root.clicked.connect(self._on_browse_root)
        root_layout.addWidget(self._btn_browse_root)
        settings_layout.addLayout(root_layout)

        ext_layout = QHBoxLayout()
        ext_layout.addWidget(QLabel("文件扩展名:"))
        self._ext_edit = QPlainTextEdit()
        self._ext_edit.setMaximumHeight(80)
        ext_layout.addWidget(self._ext_edit, 1)
        settings_layout.addLayout(ext_layout)

        pwd_layout = QHBoxLayout()
        pwd_layout.addWidget(QLabel("加密密码:"))
        self._pwd_edit = QLineEdit()
        self._pwd_edit.setEchoMode(QLineEdit.Password)
        pwd_layout.addWidget(self._pwd_edit, 1)
        self._btn_show_pwd = QPushButton("显示")
        self._btn_show_pwd.setCheckable(True)
        self._btn_show_pwd.toggled.connect(self._on_toggle_password)
        pwd_layout.addWidget(self._btn_show_pwd)
        settings_layout.addLayout(pwd_layout)

        adv_layout = QHBoxLayout()
        adv_layout.addWidget(QLabel("防抖(秒):"))
        self._debounce_spin = QSpinBox()
        self._debounce_spin.setRange(1, 60)
        adv_layout.addWidget(self._debounce_spin)
        adv_layout.addWidget(QLabel("版本上限:"))
        self._max_versions_spin = QSpinBox()
        self._max_versions_spin.setRange(1, 99)
        adv_layout.addWidget(self._max_versions_spin)
        adv_layout.addWidget(QLabel("异常阈值:"))
        self._anomaly_threshold_spin = QSpinBox()
        self._anomaly_threshold_spin.setRange(1, 999)
        self._anomaly_threshold_spin.setToolTip("同时变动文件数超过此值将暂停监控")
        adv_layout.addWidget(self._anomaly_threshold_spin)
        adv_layout.addStretch()
        self._autostart_check = QCheckBox("开机自启")
        self._autostart_check.stateChanged.connect(self._on_ui_autostart_changed)
        adv_layout.addWidget(self._autostart_check)
        settings_layout.addLayout(adv_layout)

        action_layout = QHBoxLayout()
        self._btn_save = QPushButton("保存配置")
        self._btn_save.clicked.connect(self._on_save_config)
        action_layout.addWidget(self._btn_save)

        self._btn_manual = QPushButton("手动备份")
        self._btn_manual.clicked.connect(self._on_manual_backup)
        action_layout.addWidget(self._btn_manual)

        self._btn_restore = QPushButton("一键恢复")
        self._btn_restore.clicked.connect(self._on_one_click_restore)
        action_layout.addWidget(self._btn_restore)

        self._btn_start = QPushButton("开始监控")
        self._btn_start.clicked.connect(self._on_start_monitor)
        action_layout.addWidget(self._btn_start)

        self._btn_stop = QPushButton("停止监控")
        self._btn_stop.clicked.connect(self._on_stop_monitor)
        action_layout.addWidget(self._btn_stop)

        self._btn_orphan = QPushButton("孤儿清理")
        self._btn_orphan.clicked.connect(self._on_orphan_cleanup)
        action_layout.addWidget(self._btn_orphan)

        self._btn_integrity = QPushButton("完整性检查")
        self._btn_integrity.clicked.connect(self._on_integrity_check)
        action_layout.addWidget(self._btn_integrity)

        settings_layout.addLayout(action_layout)
        main_layout.addWidget(settings_box)

        log_box = QGroupBox("备份日志")
        log_layout = QVBoxLayout(log_box)
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self._log_text)
        main_layout.addWidget(log_box, 1)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_label = QLabel("就绪")
        self._monitor_label = QLabel("⚪ 已停止")
        self._status_bar.addWidget(self._status_label, 1)
        self._status_bar.addPermanentWidget(self._monitor_label)

    def _load_config_to_ui(self):
        self._source_list.clear()
        for f in self._config.get("source_folders", []):
            self._source_list.addItem(f)
        self._backup_root_edit.setText(self._config.get("backup_root", "D:/强哥备份"))
        self._ext_edit.setPlainText(", ".join(self._config.get("extensions", [])))
        self._pwd_edit.setText(self._config.get("password", ""))
        self._debounce_spin.setValue(self._config.get("debounce_seconds", 3))
        self._max_versions_spin.setValue(self._config.get("max_versions", 5))
        self._anomaly_threshold_spin.setValue(self._config.get("anomaly_threshold", 3))
        self._autostart_check.setChecked(self._config.get("autostart", False))
        self._tray.set_autostart_checked(self._config.get("autostart", False))

    def _collect_config_from_ui(self):
        return {
            "config_version": 2,
            "source_folders": [
                self._source_list.item(i).text()
                for i in range(self._source_list.count())
            ],
            "backup_root": self._backup_root_edit.text().strip(),
            "extensions": [
                e.strip()
                for e in self._ext_edit.toPlainText().replace("\n", ",").split(",")
                if e.strip()
            ],
            "password": self._pwd_edit.text(),
            "debounce_seconds": self._debounce_spin.value(),
            "max_versions": self._max_versions_spin.value(),
            "anomaly_threshold": self._anomaly_threshold_spin.value(),
            "autostart": self._autostart_check.isChecked(),
            "monitor_was_running": self._watcher.is_running(),
        }

    def _on_startup_scan_done(self, results, elapsed):
        total = sum(len(v) for v in results.values())
        log_scan(0, total, elapsed)
        if total > 0:
            self._log(f"发现 {total} 个文件变更 (耗时 {elapsed:.1f}s)")
            self._tray.show_message(
                "启动扫描", f"发现 {total} 个文件变更，可执行手动备份",
                QSystemTrayIcon.Information,
            )
        else:
            self._log(f"未发现文件变更 (耗时 {elapsed:.1f}s)")

        self._start_orphan_check()

        if self._config.get("monitor_was_running", False):
            self._on_start_monitor()

    def _start_orphan_check(self):
        if self._orphan_scan_running:
            return
        cfg = self._config
        valid = [f for f in cfg.get("source_folders", []) if Path(f).exists()]
        if not valid or not cfg.get("backup_root") or not cfg.get("extensions"):
            return

        self._orphan_scan_running = True
        orphan_signals = OrphanScanSignals()
        orphan_signals.result.connect(self._on_orphan_scan_done)
        self._threadpool.start(OrphanScanWorker(
            valid, cfg["backup_root"], cfg["extensions"], orphan_signals
        ))

    def _on_orphan_scan_done(self, orphans):
        self._orphan_scan_running = False
        if orphans:
            self._log(f"发现 {len(orphans)} 个孤儿备份")
            self._tray.show_message(
                "孤儿备份", f"发现 {len(orphans)} 个孤儿备份，可执行孤儿清理",
                QSystemTrayIcon.Information,
            )

    # --- Manual backup ---
    def _on_manual_backup(self):
        if self._manual_scan_running:
            self._log("正在扫描中，请等待...")
            return

        cfg = self._collect_config_from_ui()
        save_config(cfg)
        self._config = cfg

        valid_folders = [f for f in cfg["source_folders"] if Path(f).exists()]
        if not valid_folders:
            QMessageBox.information(self, "提示", "没有有效的源文件夹。")
            return

        self._manual_scan_running = True

        progress = QProgressDialog("正在扫描文件变更...", "取消", 0, 0, self)
        progress.setWindowTitle("扫描中")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.resize(440, 120)
        self._center_progress(progress)
        progress.show()

        scan_signals = ScanSignals()
        worker = ScanWorker(valid_folders, cfg["backup_root"], cfg["extensions"], scan_signals)
        worker_holder = [worker]

        def on_progress(msg):
            progress.setLabelText(msg)

        def on_finished(results, _elapsed):
            progress.close()
            self._manual_scan_running = False
            self._process_scan_results(cfg, results)

        def on_cancelled():
            worker_holder[0].cancel()
            self._manual_scan_running = False

        scan_signals.progress.connect(on_progress)
        scan_signals.finished.connect(on_finished)
        progress.canceled.connect(on_cancelled)
        self._threadpool.start(worker)

    def _process_scan_results(self, cfg, results):
        if not results:
            QMessageBox.information(self, "提示", "没有检测到变动的文件。")
            self._log("── 手动备份：无变动文件 ──")
            return

        total_files = sum(len(v) for v in results.values())
        total_size = 0
        for folder, files in results.items():
            for f in files:
                try:
                    total_size += f.stat().st_size
                except OSError:
                    pass

        size_mb = total_size / (1024 * 1024) if total_size > 0 else 0
        est_seconds = total_size / (10 * 1024 * 1024) if total_size > 0 else 0
        est_str = f"{int(est_seconds)} 秒" if est_seconds < 60 else f"{est_seconds / 60:.1f} 分钟"

        msg = (f"检测到 {total_files} 个变动文件\n"
               f"总大小: {size_mb:.1f} MB\n"
               f"预计耗时: {est_str}\n\n"
               f"是否开始备份？")

        reply = QMessageBox.question(self, "确认备份", msg,
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply != QMessageBox.Yes:
            self._log("── 手动备份：用户取消 ──")
            return

        pending_count = len(results)
        self._manual_pending = pending_count
        self._manual_total = pending_count

        for folder, dirty in results.items():
            self._log(f"备份: {folder} ({len(dirty)} 个文件)")

            def make_on_done():
                def on_one_done():
                    self._manual_pending -= 1
                    if self._manual_pending <= 0:
                        self._log("── 手动备份完成 ──")
                        self._show_complete_signal.emit(
                            f"手动备份已完成，共处理 {self._manual_total} 个文件夹。"
                        )
                return on_one_done

            worker = BackupWorker(
                folder, cfg["backup_root"], cfg["extensions"], cfg["password"],
                files=[str(f) for f in dirty],
                max_versions=cfg.get("max_versions", 5),
                signals=self._signals,
                on_folder_done=make_on_done(),
            )
            self._threadpool.start(worker)

    # --- Restore ---
    def _on_one_click_restore(self):
        if getattr(self, '_restore_scan_running', False):
            return

        cfg = self._config
        valid = [f for f in cfg.get("source_folders", []) if Path(f).exists()]
        if not valid or not cfg.get("backup_root"):
            QMessageBox.warning(self, "提示", "请先设置源文件夹和备份路径。")
            return

        self._restore_scan_running = True

        progress = QProgressDialog("正在扫描可恢复文件...", "", 0, 0, self)
        progress.setWindowTitle("一键恢复")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.resize(400, 100)
        self._center_progress(progress)
        progress.show()

        scan_signals = RestoreScanSignals()
        scan_signals.result.connect(self._on_restore_scan_done)

        self._restore_progress = progress
        self._restore_cfg = {
            "password": cfg.get("password", ""),
            "backup_root": cfg.get("backup_root", ""),
        }

        self._threadpool.start(RestoreScanWorker(
            valid, cfg["backup_root"], cfg["extensions"], scan_signals
        ))

    def _on_restore_scan_done(self, restorable, unmatched):
        self._restore_scan_running = False
        if self._restore_progress:
            try:
                self._restore_progress.close()
            except Exception:
                pass
            self._restore_progress = None

        if not restorable:
            QMessageBox.information(self, "一键恢复", "未发现可恢复的文件。")
            return

        from ui.restore_dialog import RestoreDialog
        dialog = RestoreDialog(restorable, unmatched, self._restore_cfg["backup_root"], self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._log("── 一键恢复：用户取消 ──")
            return

        selected = dialog.get_selected_restore_list()
        if not selected:
            return

        self._log("正在恢复文件...")
        task_signals = RestoreTaskSignals()
        task_signals.log.connect(self._log)
        task_signals.status.connect(self._set_status)
        task_signals.finished.connect(self._on_restore_task_done)
        self._restoring = True
        self._threadpool.start(RestoreTaskWorker(
            selected, self._restore_cfg["password"], task_signals
        ))

    def _on_restore_task_done(self, success, failed):
        self._restoring = False
        self._log(f"── 一键恢复完成：{success} 成功, {failed} 失败 ──")
        if success > 0:
            self._tray.show_message("一键恢复", f"已恢复 {success} 个文件")

    # --- Monitor ---
    def _on_start_monitor(self):
        if self._watcher.is_running():
            return

        cfg = self._collect_config_from_ui()
        save_config(cfg)
        self._config = cfg

        existing = [f for f in cfg["source_folders"] if Path(f).exists()]
        if not existing:
            QMessageBox.warning(self, "无法启动", "没有有效的源文件夹。")
            return

        def on_folder_changed(folder_paths):
            if self._restoring:
                return

            config_roots = [Path(f) for f in existing]
            seen = set()
            dirty_by_root = {}

            for fp in folder_paths:
                fp_path = Path(fp)
                src_root = None
                for cr in config_roots:
                    try:
                        fp_path.relative_to(cr)
                        src_root = str(cr)
                        break
                    except ValueError:
                        continue
                if src_root is None:
                    src_root = str(fp_path)

                dirty = get_dirty_files(str(fp), cfg["backup_root"], cfg["extensions"], source_root=src_root)
                for f in dirty:
                    if str(f) not in seen:
                        seen.add(str(f))
                        dirty_by_root.setdefault(src_root, []).append(f)

            if not dirty_by_root:
                return

            total_dirty = len(seen)
            threshold = cfg.get("anomaly_threshold", 3)
            if total_dirty >= threshold:
                self._log(f"异常检测：{total_dirty} 个文件同时变动，监控已暂停")
                self._tray.show_message(
                    "异常检测",
                    f"发现 {total_dirty} 个文件变更，监控已暂停",
                    QSystemTrayIcon.Warning,
                )
                self._on_stop_monitor()
                return

            for src_root, dirty in dirty_by_root.items():
                self._log(f"监控: {src_root} ({len(dirty)} 个变更)")

                worker = BackupWorker(
                    src_root, cfg["backup_root"], cfg["extensions"],
                    cfg["password"], files=[str(f) for f in dirty],
                    max_versions=cfg.get("max_versions", 5),
                    signals=self._signals,
                )
                self._threadpool.start(worker)

        self._watcher.start(
            existing, cfg["extensions"], on_folder_changed,
            cfg.get("debounce_seconds", 3), max_debounce_seconds=30,
        )
        self._monitor_label.setText("🟢 监控运行中")
        self._tray.set_monitoring_active(True)
        self._log("🟢 文件监控已启动")
        self._tray.show_message("强哥备份", "文件监控已启动")

    def _on_stop_monitor(self):
        if not self._watcher.is_running():
            return
        self._watcher.stop()
        self._monitor_label.setText("⚪ 已停止")
        self._tray.set_monitoring_active(False)
        self._log("🔴 文件监控已停止")

    # --- Orphan cleanup ---
    def _on_orphan_cleanup(self):
        if self._orphan_scan_running:
            return

        cfg = self._config
        valid = [f for f in cfg.get("source_folders", []) if Path(f).exists()]
        backup_root = cfg.get("backup_root", "")
        if not valid or not backup_root:
            QMessageBox.warning(self, "提示", "请先设置源文件夹和备份路径。")
            return
        if not Path(backup_root).exists():
            QMessageBox.warning(self, "提示", f"备份目录不存在或无法访问:\n{backup_root}")
            return

        self._orphan_scan_running = True

        progress = QProgressDialog("正在扫描孤儿备份...", "取消", 0, 0, self)
        progress.setWindowTitle("孤儿清理")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.resize(400, 100)
        self._center_progress(progress)
        progress.show()

        orphan_signals = OrphanScanSignals()
        worker = OrphanScanWorker(
            valid, cfg["backup_root"], cfg["extensions"], orphan_signals
        )

        def on_cancelled():
            worker.cancel()
            self._orphan_scan_running = False
            try:
                progress.close()
            except Exception:
                pass

        def on_done(orphans):
            self._orphan_scan_running = False
            try:
                progress.close()
            except Exception:
                pass
            if not orphans:
                QMessageBox.information(self, "孤儿清理", "未发现孤儿备份。")
                return

            from ui.orphan_dialog import OrphanDialog
            self._orphan_dialog = OrphanDialog(orphans, self)
            if self._orphan_dialog.exec() == QDialog.DialogCode.Accepted:
                selected = self._orphan_dialog.get_selected()
                if selected:
                    deleted = delete_orphan_versions(selected, cfg["backup_root"])
                    self._log(f"已删除 {deleted} 个孤儿备份")
                    QMessageBox.information(self, "完成", f"已删除 {deleted} 个备份文件。")
            self._orphan_dialog = None

        orphan_signals.result.connect(on_done)
        progress.canceled.connect(on_cancelled)
        self._threadpool.start(worker)

    # --- Integrity check ---
    def _on_integrity_check(self):
        if self._integrity_scan_running:
            return

        cfg = self._config
        backup_root = cfg.get("backup_root", "")
        if not backup_root:
            QMessageBox.warning(self, "提示", "请先设置备份路径。")
            return
        if not Path(backup_root).exists():
            QMessageBox.warning(self, "提示", f"备份目录不存在或无法访问:\n{backup_root}")
            return

        self._integrity_scan_running = True

        progress = QProgressDialog("正在检查备份完整性...", "取消", 0, 0, self)
        progress.setWindowTitle("完整性检查")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.resize(400, 100)
        self._center_progress(progress)
        progress.show()

        integrity_signals = IntegrityScanSignals()
        worker = IntegrityScanWorker(
            cfg["backup_root"], cfg["extensions"], cfg.get("password", ""),
            integrity_signals,
        )

        def on_cancelled():
            worker.cancel()
            self._integrity_scan_running = False
            try:
                progress.close()
            except Exception:
                pass

        def on_done(corrupted):
            self._integrity_scan_running = False
            try:
                progress.close()
            except Exception:
                pass
            if not corrupted:
                backup_path = Path(backup_root)
                has_archives = backup_path.exists() and any(backup_path.rglob("*.7z"))
                if has_archives:
                    QMessageBox.information(self, "完整性检查", "所有备份文件完好。")
                else:
                    QMessageBox.information(self, "完整性检查", "备份目录中没有存档文件。")
                return

            from ui.integrity_dialog import IntegrityDialog
            self._integrity_dialog = IntegrityDialog(
                corrupted, cfg["backup_root"], self
            )
            if self._integrity_dialog.exec() == QDialog.DialogCode.Accepted:
                selected = self._integrity_dialog.get_selected()
                if selected:
                    deleted = delete_corrupted_backups(selected, cfg["backup_root"])
                    self._log(f"已删除 {deleted} 个损坏的备份")
                    QMessageBox.information(self, "完成", f"已删除 {deleted} 个损坏文件。")
            self._integrity_dialog = None

        integrity_signals.result.connect(on_done)
        progress.canceled.connect(on_cancelled)
        self._threadpool.start(worker)

    # --- Config save ---
    def _on_save_config(self):
        self._config = self._collect_config_from_ui()
        if not self._config["password"]:
            QMessageBox.warning(self, "安全提示", "加密密码为空，备份文件将无法加密保护。")
        save_config(self._config)
        set_autostart(self._config["autostart"])
        self._log("✅ 配置已保存")
        self._tray.set_autostart_checked(self._config["autostart"])

    # --- UI helpers ---
    def _on_add_source(self):
        folder = QFileDialog.getExistingDirectory(self, "选择源文件夹")
        if folder:
            self._source_list.addItem(folder)

    def _on_del_source(self):
        row = self._source_list.currentRow()
        if row < 0:
            return
        self._source_list.takeItem(row)

    def _on_browse_root(self):
        folder = QFileDialog.getExistingDirectory(self, "选择备份根目录")
        if folder:
            self._backup_root_edit.setText(folder)

    def _on_toggle_password(self, checked):
        if checked:
            self._pwd_edit.setEchoMode(QLineEdit.Normal)
            self._btn_show_pwd.setText("隐藏")
        else:
            self._pwd_edit.setEchoMode(QLineEdit.Password)
            self._btn_show_pwd.setText("显示")

    def _on_ui_autostart_changed(self, state):
        if self._autostart_syncing:
            return
        self._autostart_syncing = True
        checked = bool(state)
        self._config["autostart"] = checked
        set_autostart(checked)
        self._tray.set_autostart_checked(checked)
        self._log(f"{'✅ 已开启' if checked else '❌ 已关闭'}开机自启")
        self._autostart_syncing = False

    def _on_autostart_toggled(self, checked):
        if self._autostart_syncing:
            return
        self._autostart_syncing = True
        self._config["autostart"] = checked
        set_autostart(checked)
        self._autostart_check.blockSignals(True)
        self._autostart_check.setChecked(checked)
        self._autostart_check.blockSignals(False)
        self._log(f"{'✅ 已开启' if checked else '❌ 已关闭'}开机自启")
        self._autostart_syncing = False

    def _center_progress(self, progress):
        center = self.geometry().center()
        progress.move(
            center.x() - progress.width() // 2,
            center.y() - progress.height() // 2,
        )

    def _log(self, msg):
        self._signals.log_signal.emit(msg)

    def _append_log(self, msg):
        self._log_text.append(msg)

    def _set_status(self, msg):
        self._status_label.setText(msg)

    def show_and_focus(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_quit(self):
        self._quitting = True
        if self._orphan_dialog:
            try:
                self._orphan_dialog.reject()
            except Exception:
                pass
            self._orphan_dialog = None
        if self._integrity_dialog:
            try:
                self._integrity_dialog.reject()
            except Exception:
                pass
            self._integrity_dialog = None
        try:
            self._watcher.stop()
        except Exception:
            pass
        try:
            self._tray.hide()
        except Exception:
            pass
        try:
            self._threadpool.clear()
            self._threadpool.waitForDone(2000)
        except Exception:
            pass
        try:
            QApplication.instance().quit()
        except Exception:
            pass
        os._exit(0)

    def closeEvent(self, event: QCloseEvent):
        if self._quitting:
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self._restore_msg_shown:
            self._restore_msg_shown = True
            self._tray.show_message("强哥备份", "程序已最小化到系统托盘，后台继续运行")
