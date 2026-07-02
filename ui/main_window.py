"""Main window for Qiang Backup."""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLineEdit, QListWidget, QTextEdit, QPlainTextEdit,
    QLabel, QSpinBox, QCheckBox, QFileDialog, QMessageBox,
    QProgressDialog, QStatusBar, QSystemTrayIcon, QDialog,
    QApplication, QProgressBar,
)
from PySide6.QtCore import Qt, QThreadPool, Signal, QObject, QRunnable, QMutex, QTimer
from PySide6.QtGui import QFont, QCloseEvent, QIcon

from ui.tray_icon import TrayIcon
from engine.config import load_config, save_config
from engine.change_detector import get_dirty_files, _find_latest_backup_hash
from engine.backup_engine import backup_folder
from engine.restore_engine import find_restorable_files, restore_single_file
from engine.file_watcher import FileWatcher
from engine.reconciliation import (
    find_orphaned_backups,
    delete_orphan_versions,
)
from engine.backup_log import log_scan
from utils.autostart import set_autostart


def _generate_batch_id():
    """生成批次ID，格式：batch_YYYYMMDD_HHMMSS"""
    return f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


class LogSignals(QObject):
    log_signal = Signal(str)
    status_signal = Signal(str)


class ScanSignals(QObject):
    progress = Signal(str)
    file_count = Signal(int)
    finished = Signal(object, object, float)  # results, locked_files, elapsed


class ScanWorker(QRunnable):
    def __init__(self, source_folders, backup_root, extensions, signals, scan_locked=True, locked_only=False):
        super().__init__()
        self.source_folders = source_folders
        self.backup_root = backup_root
        self.extensions = extensions
        self.signals = signals
        self.scan_locked = scan_locked
        self.locked_only = locked_only
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        from engine.change_detector import safe_rglob, _is_file_locked

        results = {}
        all_locked = []
        total = 0
        file_counter = [0]
        start = time.monotonic()

        def on_file(f):
            if self._cancelled:
                return False
            file_counter[0] += 1
            if file_counter[0] % 5 == 0:
                self.signals.file_count.emit(file_counter[0])
            return True

        try:
            self.signals.file_count.emit(0)
            for folder in self.source_folders:
                if self._cancelled:
                    break
                self.signals.progress.emit(f"正在扫描 {folder}...")

                if self.locked_only:
                    # 全盘扫描模式：仅检测被锁文件，跳过哈希比对
                    for f in safe_rglob(Path(folder), self.extensions):
                        if not on_file(f):
                            break
                        if _is_file_locked(f):
                            all_locked.append(f)
                else:
                    dirty, locked = get_dirty_files(
                        folder, self.backup_root, self.extensions,
                        progress_cb=on_file, scan_locked=self.scan_locked
                    )
                    if self._cancelled:
                        break
                    if dirty:
                        results[folder] = dirty
                        total += len(dirty)
                    if locked:
                        all_locked.extend(locked)
        except Exception:
            pass
        elapsed = time.monotonic() - start
        if not self._cancelled:
            self.signals.finished.emit(results, all_locked, elapsed)


class BackupWorker(QRunnable):
    def __init__(self, folder, backup_root, extensions, password,
                 files, max_versions, signals, batch_id=None, on_folder_done=None):
        super().__init__()
        self.folder = folder
        self.backup_root = backup_root
        self.extensions = extensions
        self.password = password
        self.files = files
        self.max_versions = max_versions
        self.signals = signals
        self.batch_id = batch_id
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
                batch_id=self.batch_id,
            )
            self.signals.status_signal.emit("就绪")
        finally:
            if self._on_folder_done:
                self._on_folder_done()


class OrphanScanSignals(QObject):
    result = Signal(object)
    file_count = Signal(int)


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
            def on_progress(count):
                if self._cancelled:
                    return False
                self.signals.file_count.emit(count)
                return True

            orphans = find_orphaned_backups(
                self.source_folders, self.backup_root, self.extensions,
                progress_cb=on_progress,
            )
        except Exception:
            orphans = []
        if not self._cancelled:
            self.signals.result.emit(orphans)


class RestoreScanSignals(QObject):
    result = Signal(object, object, object)  # restorable, unmatched, locked_files
    file_count = Signal(int)


class RestoreScanWorker(QRunnable):
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
            def on_progress(count):
                if self._cancelled:
                    return False
                self.signals.file_count.emit(count)
                return True

            restorable, unmatched, locked_files = find_restorable_files(
                self.source_folders, self.backup_root, self.extensions,
                progress_cb=on_progress,
            )
        except Exception:
            restorable, unmatched, locked_files = [], [], []
        if not self._cancelled:
            self.signals.result.emit(restorable, unmatched, locked_files)


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


class ChangeFileScanSignals(QObject):
    result = Signal(object, object, object)  # changed_files, unbacked_files, locked_files
    file_count = Signal(int)


class ChangeFileScanWorker(QRunnable):
    def __init__(self, dirty_results, backup_root, source_folders, extensions, signals, locked_files=None):
        super().__init__()
        self.dirty_results = dirty_results
        self.backup_root = backup_root
        self.source_folders = source_folders
        self.extensions = extensions
        self.signals = signals
        self.locked_files = locked_files or []
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        changed_files = []
        unbacked_files = []
        file_counter = 0

        try:
            for folder, dirty_files in self.dirty_results.items():
                source_root = Path(folder)
                for f in dirty_files:
                    if self._cancelled:
                        return
                    file_counter += 1
                    if file_counter % 5 == 0:
                        self.signals.file_count.emit(file_counter)

                    latest_archive, backup_hash, all_hashes = _find_latest_backup_hash(
                        f, source_root, self.backup_root
                    )

                    if latest_archive is None:
                        unbacked_files.append(str(f))
                    else:
                        versions = []
                        import re
                        safe_stem = f.name
                        pattern = re.compile(
                            rf"^{re.escape(safe_stem)}_(\d{{8}})_(\d{{6}})_([0-9a-f]{{16}})\.7z$"
                        )
                        backup_dir = latest_archive.parent
                        for archive in backup_dir.glob("*.7z"):
                            m = pattern.match(archive.name)
                            if m:
                                versions.append({
                                    "path": archive,
                                    "timestamp": f"{m.group(1)}_{m.group(2)}",
                                })
                        versions.sort(key=lambda v: v["timestamp"], reverse=True)
                        changed_files.append((str(f), versions))
        except Exception:
            pass

        if not self._cancelled:
            self.signals.result.emit(changed_files, unbacked_files, self.locked_files)


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
        self._restoring = False
        self._quitting = False
        self._restore_msg_shown = False
        self._autostart_syncing = False
        self._change_scan_running = False
        self._view_change_scan_running = False
        self._orphan_dialog = None
        self._restore_progress = None

        self._tray = TrayIcon()
        self._setup_tray_signals()
        self._tray.show()  # 提前显示托盘图标，避免启动扫码期间无托盘

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
        last_progress_time = [time.monotonic()]
        startup_done = [False]
        retry_attempts = [0]
        worker_ref = [None]

        def on_count(n):
            last_progress_time[0] = time.monotonic()
            count_label.setText(f"已扫描 {n} 个文件")

        def on_finished(results, locked_files, elapsed):
            if startup_done[0]:
                return
            startup_done[0] = True
            watchdog.stop()
            dlg.accept()
            self._on_startup_scan_done(results, locked_files, elapsed)
            self._finish_startup()

        scan_signals.file_count.connect(on_count)
        scan_signals.finished.connect(on_finished)

        def _start_worker():
            w = ScanWorker(valid, backup_root, extensions, scan_signals)
            worker_ref[0] = w
            self._threadpool.start(w)

        _start_worker()

        watchdog = QTimer()
        watchdog.setInterval(5000)

        def check_stall():
            if startup_done[0]:
                watchdog.stop()
                return
            elapsed = time.monotonic() - last_progress_time[0]
            if elapsed < 30:
                return
            if worker_ref[0] is not None:
                worker_ref[0].cancel()
            if retry_attempts[0] == 0:
                retry_attempts[0] += 1
                last_progress_time[0] = time.monotonic()
                self._log("启动扫描超时，正在重试…")
                _start_worker()
            else:
                watchdog.stop()
                startup_done[0] = True
                dlg.accept()
                self._log("启动扫描未能完成，请手动运行备份")
                QMessageBox.warning(
                    dlg, "扫描超时",
                    "自动文件扫描未能在预期时间内完成。\n请点击「手动备份」按钮完成扫描和备份。"
                )
                self._finish_startup()

        watchdog.timeout.connect(check_stall)
        watchdog.start()

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
        adv_layout.addStretch()
        self._autostart_check = QCheckBox("开机自启")
        self._autostart_check.stateChanged.connect(self._on_ui_autostart_changed)
        adv_layout.addWidget(self._autostart_check)
        settings_layout.addLayout(adv_layout)

        action_layout = QHBoxLayout()

        self._btn_start = QPushButton("开始监控")
        self._btn_start.clicked.connect(self._on_start_monitor)
        action_layout.addWidget(self._btn_start)

        self._btn_stop = QPushButton("停止监控")
        self._btn_stop.clicked.connect(self._on_stop_monitor)
        action_layout.addWidget(self._btn_stop)

        self._btn_manual = QPushButton("手动备份")
        self._btn_manual.clicked.connect(self._on_manual_backup)
        action_layout.addWidget(self._btn_manual)

        self._btn_restore = QPushButton("一键恢复")
        self._btn_restore.clicked.connect(self._on_one_click_restore)
        action_layout.addWidget(self._btn_restore)

        self._btn_orphan = QPushButton("孤儿清理")
        self._btn_orphan.clicked.connect(self._on_orphan_cleanup)
        action_layout.addWidget(self._btn_orphan)

        self._btn_scan_locked = QPushButton("全盘扫描")
        self._btn_scan_locked.clicked.connect(self._on_scan_locked_files)
        action_layout.addWidget(self._btn_scan_locked)

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
        self._autostart_check.setChecked(self._config.get("autostart", False))
        self._tray.set_autostart_checked(self._config.get("autostart", False))

        # 自动保存：配置项改动时自动保存
        self._connect_auto_save()

    def _connect_auto_save(self):
        for widget in [self._backup_root_edit, self._pwd_edit]:
            widget.textChanged.connect(self._auto_save_config)
        self._ext_edit.textChanged.connect(self._auto_save_config)
        for spin in [self._debounce_spin, self._max_versions_spin]:
            spin.valueChanged.connect(self._auto_save_config)
        self._source_list.model().rowsInserted.connect(self._auto_save_config)
        self._source_list.model().rowsRemoved.connect(self._auto_save_config)

    def _auto_save_config(self):
        try:
            save_config(self._collect_config_from_ui())
            self._config = self._collect_config_from_ui()
        except Exception:
            pass

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
            "autostart": self._autostart_check.isChecked(),
            "monitor_was_running": self._watcher.is_running(),
        }

    def _on_startup_scan_done(self, results, locked_files, elapsed):
        total = sum(len(v) for v in results.values())
        log_scan(0, total, elapsed)
        if total > 0 or locked_files:
            if total > 0:
                self._log(f"发现 {total} 个文件变更 (耗时 {elapsed:.1f}s)")
            if locked_files:
                self._log(f"发现 {len(locked_files)} 个被锁文件")
            self._process_scan_results(self._config, results, locked_files)
        else:
            self._log(f"未发现文件变更 (耗时 {elapsed:.1f}s)")

        self._start_orphan_check()

        # 自动开启监控（除非检测到被锁文件）
        if not locked_files:
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

        progress, label = self._create_progress("手动备份 — 扫描中", "已扫描 0 个文件...")

        scan_signals = ScanSignals()
        worker = ScanWorker(valid_folders, cfg["backup_root"], cfg["extensions"], scan_signals)
        worker_holder = [worker]

        def on_file_count(count):
            label.setText(f"已扫描 {count} 个文件...")

        def on_finished(results, locked_files, _elapsed):
            progress.close()
            self._manual_scan_running = False
            self._process_scan_results(cfg, results, locked_files)

        def on_cancelled():
            worker_holder[0].cancel()
            self._manual_scan_running = False

        scan_signals.file_count.connect(on_file_count)
        scan_signals.finished.connect(on_finished)
        progress.rejected.connect(on_cancelled)
        self._threadpool.start(worker)

    def _process_scan_results(self, cfg, results, locked_files=None):
        if not results and not locked_files:
            QMessageBox.information(self, "提示", "没有检测到变动的文件。")
            self._log("── 手动备份：无变动文件 ──")
            return

        # 直接弹出大弹窗（两个标签页：未备份文件 + 被锁定文件）
        self._log("── 查看变动文件 ──")
        self._start_view_change_files(cfg, results, locked_files)

    def _start_view_change_files(self, cfg, results, locked_files=None):
        # 从 results 收集所有未备份文件
        unbacked_files = []
        for folder, files in results.items():
            for f in files:
                unbacked_files.append(str(f))

        # 确保被锁文件不在未备份列表中（分流），同时转字符串
        locked_paths = set(str(f) for f in (locked_files or []))
        unbacked_files = [f for f in unbacked_files if f not in locked_paths]
        locked_files = [str(f) for f in (locked_files or [])]

        # 直接弹出 ChangeFilesDialog
        self._show_view_change_files_dialog(cfg, [], unbacked_files, locked_files)

    def _show_view_change_files_dialog(self, cfg, changed_files, unbacked_files, locked_files=None):
        if not unbacked_files and not locked_files:
            QMessageBox.information(self, "提示", "没有变动或未备份的文件。")
            return

        from ui.change_files_dialog import ChangeFilesDialog
        dialog = ChangeFilesDialog(
            [], unbacked_files, cfg.get("backup_root", ""),
            locked_files=locked_files, parent=self,
            title="查看变动文件"
        )
        dialog.backup_selected_signal.connect(lambda files: self._execute_backup_from_dialog(cfg, files))
        try:
            dialog.exec()
        except Exception as e:
            self._log(f"弹窗出错: {e}")
            QMessageBox.warning(self, "错误", f"无法打开文件查看窗口:\n{e}")

    def _execute_backup_from_dialog(self, cfg, files):
        batch_id = _generate_batch_id()
        valid_folders = [f for f in cfg.get("source_folders", []) if Path(f).exists()]

        files_by_folder = {}
        for f in files:
            f_path = Path(f)
            for folder in valid_folders:
                try:
                    f_path.relative_to(folder)
                    files_by_folder.setdefault(folder, []).append(f)
                    break
                except ValueError:
                    continue

        pending_count = len(files_by_folder)
        self._manual_pending = pending_count
        self._manual_total = pending_count

        for folder, folder_files in files_by_folder.items():
            self._log(f"备份: {folder} ({len(folder_files)} 个文件)")

            def make_on_done():
                def on_one_done():
                    self._manual_pending -= 1
                    if self._manual_pending <= 0:
                        self._log("── 备份完成 ──")
                        self._tray.show_message("备份完成", f"已备份 {self._manual_total} 个文件夹")
                return on_one_done

            worker = BackupWorker(
                folder, cfg["backup_root"], cfg["extensions"], cfg["password"],
                files=folder_files,
                max_versions=cfg.get("max_versions", 5),
                signals=self._signals,
                batch_id=batch_id,
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

        progress, label = self._create_progress("一键恢复", "已扫描 0 个文件...")

        scan_signals = RestoreScanSignals()
        scan_signals.result.connect(self._on_restore_scan_done)

        def on_file_count(count):
            label.setText(f"已扫描 {count} 个文件...")

        def on_cancelled():
            worker_holder[0].cancel()
            self._restore_scan_running = False
            try:
                progress.close()
            except Exception:
                pass

        scan_signals.file_count.connect(on_file_count)
        progress.rejected.connect(on_cancelled)

        self._restore_progress = progress
        self._restore_cfg = {
            "password": cfg.get("password", ""),
            "backup_root": cfg.get("backup_root", ""),
        }

        worker = RestoreScanWorker(
            valid, cfg["backup_root"], cfg["extensions"], scan_signals
        )
        worker_holder = [worker]
        self._threadpool.start(worker)

    def _on_restore_scan_done(self, restorable, unmatched, locked_files=None):
        self._restore_scan_running = False
        if self._restore_progress:
            try:
                self._restore_progress.close()
            except Exception:
                pass
            self._restore_progress = None

        if not restorable and not locked_files:
            QMessageBox.information(self, "一键恢复", "未发现可恢复的文件。")
            return

        from ui.restore_dialog import RestoreDialog
        dialog = RestoreDialog(restorable, unmatched, self._restore_cfg["backup_root"], 
                              locked_files=locked_files, parent=self)
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

        def on_folder_changed(file_paths):
            if self._restoring:
                return

            config_roots = [Path(f) for f in existing]
            seen = set()
            dirty_by_root = {}

            # 按源根目录分组文件，传递文件列表实现快速路径
            files_by_root = {}
            for fp in file_paths:
                fp_path = Path(fp)
                # 过滤备份归档和临时文件，避免孤儿清理等操作触发误备份
                name_lower = fp_path.name.lower()
                if name_lower.endswith(('.7z', '.tmp', '~')):
                    continue
                for cr in config_roots:
                    try:
                        fp_path.relative_to(cr)
                        files_by_root.setdefault(str(cr), []).append(fp_path)
                        break
                    except ValueError:
                        continue

            for src_root, files in files_by_root.items():
                dirty, locked = get_dirty_files(
                    src_root, cfg["backup_root"], cfg["extensions"],
                    source_root=src_root, files=files
                )
                if locked:
                    self._log(f"监控检测到 {len(locked)} 个被锁文件，监控已停止")
                    self._tray.show_message(
                        "检测到被锁文件",
                        f"检测到 {len(locked)} 个被锁文件，监控已停止",
                        QSystemTrayIcon.Warning,
                    )
                    self._on_stop_monitor()
                    return
                for f in dirty:
                    if str(f) not in seen:
                        seen.add(str(f))
                        dirty_by_root.setdefault(src_root, []).append(f)

            if not dirty_by_root:
                return

            for src_root, dirty in dirty_by_root.items():
                self._log(f"监控: {src_root} ({len(dirty)} 个变更)")

                batch_id = _generate_batch_id()
                total_files = len(dirty)

                def on_folder_done():
                    self._tray.show_message(
                        "监控备份完成",
                        f"已备份 {total_files} 个文件"
                    )

                worker = BackupWorker(
                    src_root, cfg["backup_root"], cfg["extensions"],
                    cfg["password"], files=[str(f) for f in dirty],
                    max_versions=cfg.get("max_versions", 5),
                    signals=self._signals,
                    batch_id=batch_id,
                    on_folder_done=on_folder_done,
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

        progress, label = self._create_progress("孤儿清理", "已扫描 0 个文件...")

        orphan_signals = OrphanScanSignals()
        worker = OrphanScanWorker(
            valid, cfg["backup_root"], cfg["extensions"], orphan_signals
        )

        def on_file_count(count):
            label.setText(f"已扫描 {count} 个文件...")

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
        orphan_signals.file_count.connect(on_file_count)
        progress.rejected.connect(on_cancelled)
        self._threadpool.start(worker)

    # --- Scan locked files ---
    def _on_scan_locked_files(self):
        """全盘扫描被锁文件 — 扫描整个电脑所有驱动器"""
        cfg = self._collect_config_from_ui()
        extensions = cfg["extensions"]

        if not extensions:
            QMessageBox.warning(self, "全盘扫描", "请先设置文件扩展名后再扫描。")
            return

        # 获取所有可用驱动器
        import string
        all_drives = []
        for drive in string.ascii_uppercase:
            drive_path = Path(f"{drive}:\\")
            if drive_path.exists():
                all_drives.append(f"{drive}:\\")

        if not all_drives:
            QMessageBox.information(self, "提示", "未找到可用磁盘。")
            return

        self._log("全盘扫描被锁文件...")

        progress, label = self._create_progress("全盘扫描被锁文件", "已扫描 0 个文件...")
        scan_signals = ScanSignals()
        worker = ScanWorker(all_drives, cfg["backup_root"], extensions, scan_signals, scan_locked=True, locked_only=True)

        def on_file_count(count):
            label.setText(f"已扫描 {count} 个文件...")

        def on_finished(results, locked_files, elapsed):
            progress.close()
            self._log(f"扫描完成，发现 {len(locked_files)} 个被锁文件")

            if not locked_files:
                QMessageBox.information(self, "全盘扫描被锁文件", "未发现被锁文件。")
                return

            from ui.locked_files_dialog import LockedFilesDialog
            dialog = LockedFilesDialog([str(f) for f in locked_files], self)
            dialog.exec()

        def on_cancelled():
            worker.cancel()

        scan_signals.file_count.connect(on_file_count)
        scan_signals.finished.connect(on_finished)
        progress.rejected.connect(on_cancelled)
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

    def _create_progress(self, title, label_text, cancel_text="取消"):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setFixedSize(440, 120)
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 12, 20, 12)

        lbl = QLabel(label_text)
        lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl)

        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setFixedHeight(16)
        layout.addWidget(bar)

        btn = QPushButton(cancel_text)
        btn.clicked.connect(dlg.reject)
        layout.addWidget(btn, alignment=Qt.AlignCenter)

        screen = QApplication.primaryScreen().geometry()
        dlg.move(
            (screen.width() - dlg.width()) // 2,
            (screen.height() - dlg.height()) // 2,
        )
        dlg.show()

        return dlg, lbl

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
