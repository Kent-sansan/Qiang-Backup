# 强哥备份工具 V2 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从零重写强哥备份工具 V2，核心架构变化：去掉 backup_state.json，改用"当前文件直接对比最新备份存档"的变化检测机制。移除重建索引功能。

**Architecture:** 桌面备份工具，PySide6 GUI + py7zr 加密 + watchdog 文件监控。变化检测直接遍历源目录，对每个文件找到最新备份存档对比哈希。不再维护独立的本地状态文件。

**Tech Stack:** Python 3, PySide6, py7zr, watchdog, winreg

---

### Task 1: 项目脚手架

**Files:**
- Create: `D:\OpenCode\Qiang Backup\requirements.txt`
- Create: `D:\OpenCode\Qiang Backup\engine\__init__.py`
- Create: `D:\OpenCode\Qiang Backup\ui\__init__.py`
- Create: `D:\OpenCode\Qiang Backup\utils\__init__.py`
- Copy: `icon.ico` from old project

- [ ] **Step 1: 创建目录结构和 requirements.txt**

```bash
New-Item -ItemType Directory -Path "D:\OpenCode\Qiang Backup\engine" -Force
New-Item -ItemType Directory -Path "D:\OpenCode\Qiang Backup\ui" -Force
New-Item -ItemType Directory -Path "D:\OpenCode\Qiang Backup\utils" -Force
New-Item -ItemType File -Path "D:\OpenCode\Qiang Backup\engine\__init__.py" -Force
New-Item -ItemType File -Path "D:\OpenCode\Qiang Backup\ui\__init__.py" -Force
New-Item -ItemType File -Path "D:\OpenCode\Qiang Backup\utils\__init__.py" -Force
Copy-Item -LiteralPath "D:\OpenCode\backup_tool\icon.ico" -Destination "D:\OpenCode\Qiang Backup\icon.ico"
```

Create `D:\OpenCode\Qiang Backup\requirements.txt`:
```
py7zr>=1.1.0
watchdog>=4.0.0
PySide6>=6.5.0
```

---

### Task 2: 配置管理

**Files:**
- Create: `D:\OpenCode\Qiang Backup\engine\config.py`

- [ ] **Step 1: 编写配置管理模块**

```python
"""Configuration management for Qiang Backup."""
import sys
import json
from pathlib import Path

DEFAULT_CONFIG = {
    "config_version": 2,
    "source_folders": [],
    "backup_root": "D:/强哥备份",
    "extensions": [
        ".GBQ7", ".GSH7", ".GSC7", ".GPV7", ".GEPC7", ".GPB7", ".GTJ",
        ".GPB6", ".GPB5", ".GBG9", ".GPE9", ".GBQ6", ".GBQ5", ".GBQ4",
        ".GZB4", ".GTB4", ".GPB9", ".GEPC6", ".GPV6", ".GPV5", ".GSC6",
        ".GSC5", ".GSH6", ".GSH5", ".GBQSH4", ".GBGSH4", ".GXMSH4",
        ".GDBSH4", ".GXMDBSH4", ".GPC5", ".GBQPC4", ".GBGPC9", ".GZBPC4",
        ".GTBPC4", ".GPBPC9", ".GPBEC9", ".GEC5",
    ],
    "password": "强哥备份",
    "debounce_seconds": 3,
    "max_versions": 5,
    "anomaly_threshold": 3,
    "autostart": False,
    "monitor_was_running": False,
}


def _get_app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).resolve().parent.parent


CONFIG_PATH = _get_app_dir() / "config.json"


def load_config(config_path=CONFIG_PATH):
    if not config_path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update({k: v for k, v in data.items() if k in merged})
    return merged


def save_config(config, config_path=CONFIG_PATH):
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = config_path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        tmp.replace(config_path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
```

---

### Task 3: 变化检测（核心模块，替代旧版 state_manager）

**Files:**
- Create: `D:\OpenCode\Qiang Backup\engine\change_detector.py`

这是 V2 最关键的模块。核心逻辑：对每个文件直接找到它的最新备份存档，对比哈希。

- [ ] **Step 1: 编写变化检测模块**

```python
"""Change detection — compare current files against latest backup archives.

Core principle: backup archives are the source of truth.
No local state file (backup_state.json) is used.
"""

import hashlib
import re
from pathlib import Path


def _is_junction_or_symlink(path):
    try:
        return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())
    except OSError:
        return True


def safe_rglob(root, extensions):
    """Recursively glob files matching extensions, skipping symlinks/junctions."""
    root = Path(root)
    try:
        for entry in root.iterdir():
            if _is_junction_or_symlink(entry):
                continue
            if entry.is_dir():
                yield from safe_rglob(entry, extensions)
            elif any(entry.name.lower().endswith(ext.lower()) for ext in extensions):
                yield entry
    except (OSError, PermissionError):
        pass


def _compute_sha256(file_path, head_only=False):
    """Compute SHA-256 of entire file. If head_only, only first 4096 bytes."""
    h = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            if head_only:
                data = f.read(4096)
                h.update(data)
            else:
                for chunk in iter(lambda: f.read(65536), b''):
                    h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _compute_safe_stem(filename):
    return re.sub(r'[. ]', '_', filename)


def _get_relative_mirror_dir(source_file, source_root):
    """Get the mirror directory path relative to source_root, stripping drive letter."""
    source_file = Path(source_file)
    source_root = Path(source_root)
    rel = source_file.relative_to(source_root)
    return str(rel.parent)


def _find_latest_backup_hash(source_file, source_root, backup_root):
    """Find the most recent backup archive for a source file and return its content hash.
    Returns (archive_path, hash16) or (None, None) if no backup exists."""
    backup_root = Path(backup_root)
    source_root = Path(source_root)
    mirror_dir = _get_relative_mirror_dir(source_file, source_root)
    backup_dir = backup_root / mirror_dir
    safe_stem = _compute_safe_stem(source_file.name)

    if not backup_dir.exists():
        return None, None

    pattern = re.compile(
        rf"^{re.escape(safe_stem)}_(\d{{8}})_(\d{{6}})_([0-9a-f]{{16}})\.7z$"
    )

    latest = None
    latest_ts = ""
    latest_hash = None

    for archive in backup_dir.glob(f"{safe_stem}_*.7z"):
        m = pattern.match(archive.name)
        if m:
            ts = f"{m.group(1)}_{m.group(2)}"
            if ts > latest_ts:
                latest_ts = ts
                latest = archive
                latest_hash = m.group(3)

    return latest, latest_hash


def compute_file_hash16(file_path):
    """Compute full SHA-256 and return first 16 hex chars."""
    full_hash = _compute_sha256(file_path, head_only=False)
    if full_hash is None:
        return None
    return full_hash[:16]


def get_dirty_files(source_folder, backup_root, extensions):
    """Scan a source folder and return list of files that need backup.

    A file needs backup if:
    - No backup archive exists for it (new file)
    - Its current content hash differs from the latest backup's hash
    """
    source_folder = Path(source_folder)
    backup_root = Path(backup_root)
    dirty = []

    if not source_folder.exists():
        return dirty

    for f in safe_rglob(source_folder, extensions):
        latest_archive, backup_hash = _find_latest_backup_hash(f, source_folder, backup_root)

        if latest_archive is None or backup_hash is None:
            dirty.append(f)
            continue

        current_hash = compute_file_hash16(f)
        if current_hash is None:
            continue

        if current_hash != backup_hash:
            dirty.append(f)

    return dirty


def scan_all_sources(source_folders, backup_root, extensions):
    """Scan all source folders, return {folder: [dirty_files]} and total count."""
    results = {}
    total = 0
    for folder in source_folders:
        dirty = get_dirty_files(folder, backup_root, extensions)
        if dirty:
            results[folder] = dirty
            total += len(dirty)
    return results, total
```

---

### Task 4: 操作日志

**Files:**
- Create: `D:\OpenCode\Qiang Backup\engine\backup_log.py`

- [ ] **Step 1: 编写日志模块**

```python
"""Structured JSONL backup log — append-only operation record."""

import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path


def _get_log_path():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "backup.log"
    else:
        return Path(__file__).resolve().parent.parent / "backup.log"


_log_path = _get_log_path()
_log_lock = threading.Lock()


def _append_entry(entry):
    entry["ts"] = entry.get("ts") or datetime.now(timezone.utc).isoformat()
    line = json.dumps(entry, ensure_ascii=False)
    try:
        _log_path.parent.mkdir(parents=True, exist_ok=True)
        with _log_lock:
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
    except OSError:
        pass


def log_scan(total_files, dirty_count, elapsed_seconds):
    _append_entry({
        "type": "scan",
        "total_files": total_files,
        "dirty_count": dirty_count,
        "elapsed_seconds": elapsed_seconds,
    })


def log_backup(source_path, archive_path, sha256, size):
    _append_entry({
        "type": "backup",
        "source": str(source_path),
        "archive": str(archive_path),
        "sha256": sha256,
        "size": size,
    })


def log_restore(source_path, archive_path):
    _append_entry({
        "type": "restore",
        "source": str(source_path),
        "archive": str(archive_path),
    })


def log_delete(reason, archive_paths):
    _append_entry({
        "type": "delete",
        "reason": reason,
        "count": len(archive_paths),
        "archive_paths": [str(p) for p in archive_paths],
    })


def log_error(error_type, detail, path=None):
    entry = {
        "type": "error",
        "error_type": error_type,
        "detail": str(detail),
    }
    if path:
        entry["path"] = str(path)
    _append_entry(entry)
```

---

### Task 5: 备份引擎

**Files:**
- Create: `D:\OpenCode\Qiang Backup\engine\backup_engine.py`

- [ ] **Step 1: 编写备份引擎**

```python
"""AES-256 encrypted 7z backup engine using py7zr with header encryption."""

import hashlib
import re
import time
from datetime import datetime
from pathlib import Path

import py7zr

from engine.change_detector import safe_rglob, _compute_safe_stem
from engine.backup_log import log_backup, log_error


def _compute_file_sha256(file_path):
    """Compute full SHA-256 hex digest of a file."""
    try:
        h = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _make_archive_name(source_file, ts, file_hash):
    safe_stem = _compute_safe_stem(source_file.name)
    return f"{safe_stem}_{ts}_{file_hash}.7z"


def _cleanup_old_versions(archive_dir, stem, max_versions):
    max_versions = max(1, max_versions)
    pattern = re.compile(rf"^{re.escape(stem)}_\d{{8}}_\d{{6}}_[0-9a-f]{{16}}\.7z$")
    versions = sorted(
        [p for p in archive_dir.glob(f"{stem}_*.7z") if pattern.match(p.name)],
        key=lambda p: p.name,
    )
    while len(versions) > max_versions:
        oldest = versions[0]
        if oldest == versions[-1]:
            break
        if oldest.exists():
            try:
                oldest.unlink()
            except OSError:
                pass
        versions.pop(0)


def backup_single_file(source_file, source_root, backup_root, password, max_versions=5):
    """Backup a single file. Returns (success, message)."""
    source_file = Path(source_file)
    source_root = Path(source_root)
    backup_root = Path(backup_root)

    if not source_file.exists():
        return False, f"文件不存在: {source_file}"

    try:
        rel = source_file.relative_to(source_root)
    except ValueError:
        return False, f"文件不在源文件夹内: {source_file}"

    max_versions = max(1, min(max_versions, 999))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    full_hash = _compute_file_sha256(source_file)
    if full_hash is None:
        return False, f"无法读取文件: {source_file}"
    hash16 = full_hash[:16]

    archive_name = _make_archive_name(source_file, ts, hash16)
    mirror_dir = str(rel.parent)
    archive_path = backup_root / mirror_dir / archive_name
    archive_path_tmp = None

    for attempt in range(3):
        try:
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            archive_path_tmp = archive_path.with_suffix('.tmp')

            with py7zr.SevenZipFile(
                archive_path_tmp, "w", password=password, header_encryption=True,
                filters=[{"id": py7zr.FILTER_COPY}],
            ) as szf:
                szf.write(str(source_file), source_file.name)

            archive_path_tmp.rename(archive_path)
            _cleanup_old_versions(archive_path.parent, _compute_safe_stem(source_file.name), max_versions)

            try:
                size = source_file.stat().st_size
                log_backup(str(source_file), str(archive_path), full_hash, size)
            except Exception:
                pass

            return True, str(archive_path)

        except Exception as e:
            if archive_path_tmp is not None and archive_path_tmp.exists():
                try:
                    archive_path_tmp.unlink()
                except Exception:
                    pass
            if attempt < 2:
                time.sleep(1)
            else:
                log_error("backup_failed", str(e), path=str(source_file))
                return False, str(e)


def backup_folder(source_root, backup_root, extensions, password,
                  files=None, max_versions=5, progress_cb=None, file_done_cb=None):
    """Backup files in a source folder. files=None means scan all.
    Returns (success_count, total_count)."""
    source_root = Path(source_root)
    backup_root = Path(backup_root)

    if not source_root.exists():
        return 0, 0

    if files is not None:
        file_list = [Path(f) for f in files if Path(f).exists()]
    else:
        file_list = list(dict.fromkeys(safe_rglob(source_root, extensions)))

    if not file_list:
        return 0, 0

    total = len(file_list)
    success_count = 0
    for i, f in enumerate(file_list, 1):
        ok, _ = backup_single_file(f, source_root, backup_root, password, max_versions)
        if ok:
            success_count += 1
        if file_done_cb:
            file_done_cb(ok, str(f))
        if progress_cb and (i % 5 == 0 or i == total):
            progress_cb(i, total, f.name)

    return success_count, total
```

---

### Task 6: 恢复引擎

**Files:**
- Create: `D:\OpenCode\Qiang Backup\engine\restore_engine.py`

- [ ] **Step 1: 编写恢复引擎**

```python
"""Restore files from encrypted 7z backup archives."""

import re
from pathlib import Path

import py7zr

from engine.change_detector import safe_rglob, _compute_safe_stem
from engine.backup_log import log_restore, log_error


def find_restorable_files(source_folders, backup_root, extensions):
    """Scan source folders and backup directory, return (restorable_list, unmatched_list)."""
    backup_root = Path(backup_root)
    restorable = []
    unmatched = []

    for folder in source_folders:
        source_root = Path(folder)
        if not source_root.exists():
            continue

        for source_file in safe_rglob(source_root, extensions):
            safe_stem = _compute_safe_stem(source_file.name)
            rel = source_file.relative_to(source_root)
            mirror_dir = str(rel.parent)
            backup_dir = backup_root / mirror_dir

            if not backup_dir.exists():
                unmatched.append(str(source_file))
                continue

            pattern = re.compile(
                rf"^{re.escape(safe_stem)}_(\d{{8}})_(\d{{6}})_([0-9a-f]{{16}})\.7z$"
            )

            versions = []
            for archive in backup_dir.glob(f"{safe_stem}_*.7z"):
                m = pattern.match(archive.name)
                if m:
                    versions.append({
                        "path": archive,
                        "timestamp": f"{m.group(1)}_{m.group(2)}",
                    })

            if versions:
                versions.sort(key=lambda v: v["timestamp"], reverse=True)
                restorable.append({
                    "source_path": str(source_file),
                    "relative_dir": mirror_dir,
                    "original_name": source_file.name,
                    "versions": versions,
                })
            else:
                unmatched.append(str(source_file))

    return restorable, unmatched


def restore_single_file(archive_path, source_path, password):
    """Restore a single file from archive. Returns True on success."""
    archive_path = Path(archive_path)
    source_path = Path(source_path)
    target_name = source_path.name
    target_dir = str(source_path.parent)

    try:
        with py7zr.SevenZipFile(archive_path, "r", password=password) as szf:
            szf.extract(targets=[target_name], path=target_dir)
        log_restore(str(source_path), str(archive_path))
        return True
    except Exception as e:
        log_error("restore_failed", str(e), path=str(source_path))
        return False
```

---

### Task 7: 备份对账（孤儿检测 + 完整性检查）

**Files:**
- Create: `D:\OpenCode\Qiang Backup\engine\reconciliation.py`

- [ ] **Step 1: 编写对账模块**

```python
"""Orphan backup detection and integrity checking."""

import os
import re
from pathlib import Path
from collections import defaultdict

import py7zr

from engine.backup_log import log_delete, log_error


def _parse_backup_filename(basename, extensions):
    for ext in sorted(extensions, key=len, reverse=True):
        ext_part = ext.lstrip(".")
        pattern = re.compile(
            rf"^(.+?)_{re.escape(ext_part)}_(\d{{8}})_(\d{{6}})_([0-9a-f]{{16}})\.7z$"
        )
        m = pattern.match(basename)
        if m:
            stem_part = m.group(1)
            date_str = m.group(2)
            time_str = m.group(3)
            file_hash = m.group(4)
            original_name = f"{stem_part}{ext}"
            return original_name, f"{date_str}_{time_str}", file_hash
    return None


def _collect_archive_entries(backup_root, extensions):
    root = Path(backup_root)
    if not root.exists():
        return []
    entries = []
    for archive_path in root.rglob("*.7z"):
        parsed = _parse_backup_filename(archive_path.name, extensions)
        if parsed is None:
            continue
        original_name, ts, file_hash = parsed
        relative_parent = str(archive_path.parent.relative_to(root))
        entries.append((archive_path, relative_parent, original_name, ts, file_hash))
    return entries


def _filter_accessible_sources(source_folders):
    accessible = []
    for sf in source_folders:
        root = Path(sf).anchor
        if root and Path(root).exists():
            accessible.append(sf)
    return accessible


def find_orphaned_backups(source_folders, backup_root, extensions):
    """Find backup archives whose source files no longer exist."""
    accessible = _filter_accessible_sources(source_folders)
    if not accessible:
        return []

    entries = _collect_archive_entries(backup_root, extensions)
    if not entries:
        return []

    drives = set()
    for sf in accessible:
        p = str(sf)
        if len(p) >= 2 and p[1] == ":":
            drives.add(p[:2] + os.sep)

    orphan_map = defaultdict(list)
    for archive_path, relative_parent, original_name, ts, _fh in entries:
        found = False
        for drive in drives:
            candidate = Path(drive) / relative_parent / original_name
            if candidate.exists():
                found = True
                break
        if not found:
            orphan_map[(relative_parent, original_name)].append((archive_path, ts))

    result = []
    for (relative_parent, original_name), versions in orphan_map.items():
        versions.sort(key=lambda v: v[1], reverse=True)
        result.append({
            "relative_dir": relative_parent,
            "original_name": original_name,
            "versions": [{"path": p, "timestamp": ts} for p, ts in versions],
            "version_count": len(versions),
        })

    return result


def check_backup_integrity(backup_root, extensions, password):
    """Check all backup archives for corruption."""
    root = Path(backup_root)
    if not root.exists():
        return []

    entries = _collect_archive_entries(backup_root, extensions)
    if not entries:
        return []

    corrupted = []
    seen = set()
    for archive_path, relative_parent, original_name, ts, _fh in entries:
        if archive_path in seen:
            continue
        seen.add(archive_path)
        try:
            with py7zr.SevenZipFile(archive_path, "r", password=password):
                pass
        except Exception:
            corrupted.append({
                "path": archive_path,
                "relative_dir": relative_parent,
                "original_name": original_name,
                "timestamp": ts,
            })

    return corrupted


def _cleanup_empty_dir(dir_path, stop_at):
    dir_path = Path(dir_path)
    stop_at = Path(stop_at).resolve()
    while dir_path != stop_at and dir_path.parent != dir_path:
        try:
            if dir_path.exists() and not any(dir_path.iterdir()):
                dir_path.rmdir()
                dir_path = dir_path.parent
            else:
                break
        except OSError:
            break


def delete_orphan_versions(orphan_items, backup_root):
    """Delete selected orphan backup archives."""
    backup_root = Path(backup_root)
    deleted = 0
    deleted_dirs = set()
    deleted_paths = []
    for item in orphan_items:
        for ver in item["versions"]:
            try:
                ver["path"].unlink()
                deleted_dirs.add(ver["path"].parent)
                deleted_paths.append(ver["path"])
                deleted += 1
            except OSError:
                pass
    if deleted_paths:
        try:
            log_delete("orphan", deleted_paths)
        except Exception:
            pass
    for d in sorted(deleted_dirs, key=lambda p: len(str(p)), reverse=True):
        _cleanup_empty_dir(d, backup_root)
    return deleted


def delete_corrupted_backups(corrupted_items, backup_root):
    """Delete selected corrupted backup archives."""
    backup_root = Path(backup_root)
    deleted = 0
    deleted_dirs = set()
    deleted_paths = []
    for item in corrupted_items:
        try:
            item["path"].unlink()
            deleted_dirs.add(item["path"].parent)
            deleted_paths.append(item["path"])
            deleted += 1
        except OSError:
            pass
    if deleted_paths:
        try:
            log_delete("corrupted", deleted_paths)
        except Exception:
            pass
    for d in sorted(deleted_dirs, key=lambda p: len(str(p)), reverse=True):
        _cleanup_empty_dir(d, backup_root)
    return deleted
```

---

### Task 8: 文件系统监控

**Files:**
- Create: `D:\OpenCode\Qiang Backup\engine\file_watcher.py`

沿用旧版的 watchdog 实现，保持不变。

- [ ] **Step 1: 复制并适配文件监控模块**

```python
"""File system watcher with global debounce using watchdog."""

import threading
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class DebounceFileHandler(FileSystemEventHandler):
    def __init__(self, extensions, on_change_callback, debounce_seconds=3, max_debounce_seconds=30):
        super().__init__()
        self.extensions = [e.lower() for e in extensions]
        self.on_change_callback = on_change_callback
        self.debounce_seconds = debounce_seconds
        self.max_debounce_seconds = max_debounce_seconds
        self._pending_folders = set()
        self._timer = None
        self._first_event_time = None
        self._lock = threading.Lock()
        self._shutdown = False

    def _should_handle(self, path):
        lowered = path.lower()
        if lowered.endswith((".7z", ".tmp")) or path.endswith("~"):
            return False
        return any(lowered.endswith(ext) for ext in self.extensions)

    def _schedule(self, folder_path):
        folder_path = str(folder_path)
        with self._lock:
            if self._shutdown:
                return
            self._pending_folders.add(folder_path)
            now = time.monotonic()
            if self._first_event_time is None:
                self._first_event_time = now
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            elapsed = now - self._first_event_time
            if elapsed >= self.max_debounce_seconds:
                self._fire_now()
            else:
                remaining = max(0.1, self.debounce_seconds - elapsed)
                self._timer = threading.Timer(remaining, self._on_timer)
                self._timer.start()

    def _on_timer(self):
        with self._lock:
            if self._shutdown:
                return
            self._timer = None
        self._fire_now()

    def _fire_now(self):
        folders = []
        with self._lock:
            if not self._pending_folders:
                return
            folders = [Path(p) for p in self._pending_folders]
            self._pending_folders.clear()
            self._first_event_time = None
        if not self._shutdown:
            self.on_change_callback(folders)

    def shutdown(self):
        self._shutdown = True
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._pending_folders.clear()
            self._first_event_time = None

    def on_modified(self, event):
        if not event.is_directory and self._should_handle(event.src_path):
            self._schedule(Path(event.src_path).parent)

    def on_created(self, event):
        if not event.is_directory and self._should_handle(event.src_path):
            self._schedule(Path(event.src_path).parent)

    def on_deleted(self, event):
        if not event.is_directory and self._should_handle(event.src_path):
            self._schedule(Path(event.src_path).parent)

    def on_moved(self, event):
        if event.is_directory:
            self._schedule(Path(event.src_path).parent)
            self._schedule(Path(event.dest_path).parent)
        else:
            if self._should_handle(event.dest_path):
                self._schedule(Path(event.dest_path).parent)
            if self._should_handle(event.src_path):
                self._schedule(Path(event.src_path).parent)


class FileWatcher:
    def __init__(self):
        self._observer = None
        self._handler = None
        self._source_folders = []

    def start(self, source_folders, extensions, on_change, debounce_seconds=3, max_debounce_seconds=30):
        if self._observer is not None:
            self.stop()
        self._source_folders = [str(Path(f)) for f in source_folders]
        self._handler = DebounceFileHandler(
            extensions, on_change, debounce_seconds, max_debounce_seconds
        )
        self._observer = Observer()
        for folder in source_folders:
            folder_path = Path(folder)
            if folder_path.exists():
                self._observer.schedule(self._handler, str(folder_path), recursive=True)
        self._observer.start()

    def stop(self):
        if self._handler:
            self._handler.shutdown()
            self._handler = None
        if self._observer:
            try:
                self._observer.unschedule_all()
            except Exception:
                pass
            try:
                self._observer.stop()
            except Exception:
                pass
            self._observer = None
        self._source_folders = []

    def is_running(self):
        if self._observer is None:
            return False
        return self._observer.is_alive()

    def health_check(self):
        if not self.is_running():
            return False
        for folder in self._source_folders:
            if not Path(folder).exists():
                return False
        return True
```

---

### Task 9: 开机自启工具

**Files:**
- Create: `D:\OpenCode\Qiang Backup\utils\autostart.py`

- [ ] **Step 1: 编写开机自启模块**

```python
"""Windows registry auto-start management."""

import sys
import os
from pathlib import Path

AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
ENTRY_NAME = "QiangGeBackup"


def _get_exe_path():
    if getattr(sys, "frozen", False):
        return sys.executable
    else:
        pythonw = Path(os.path.dirname(sys.executable)) / "pythonw.exe"
        main_script = Path(__file__).resolve().parent.parent / "main.py"
        return f'"{pythonw}" "{main_script}"'


def set_autostart(enabled):
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        )
    except FileNotFoundError:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY)
        winreg.CloseKey(key)
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        )
    try:
        if enabled:
            winreg.SetValueEx(key, ENTRY_NAME, 0, winreg.REG_SZ, _get_exe_path())
        else:
            try:
                winreg.DeleteValue(key, ENTRY_NAME)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def is_autostart_enabled():
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_READ
        )
        try:
            winreg.QueryValueEx(key, ENTRY_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except FileNotFoundError:
        return False
```

---

### Task 10: 系统托盘图标

**Files:**
- Create: `D:\OpenCode\Qiang Backup\ui\tray_icon.py`

- [ ] **Step 1: 编写系统托盘模块**

```python
"""System tray icon for Qiang Backup."""

import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QObject, Signal


def _find_icon():
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent
    icon = base / "icon.ico"
    if icon.exists():
        return str(icon)
    return None


class TrayIcon(QObject):
    show_window_signal = Signal()
    manual_backup_signal = Signal()
    start_monitor_signal = Signal()
    stop_monitor_signal = Signal()
    quit_signal = Signal()
    autostart_toggled_signal = Signal(bool)

    def __init__(self, icon_path=None):
        super().__init__()
        resolved = icon_path or _find_icon()
        self._icon = QIcon(resolved) if resolved else QIcon()
        self._tray = QSystemTrayIcon(self._icon)
        self._tray.setToolTip("Qiang Backup")
        self._tray.activated.connect(self._on_activated)

        self._last_message_time = 0
        self._last_message_key = ""

        self._menu = None
        self._show_action = None
        self._backup_action = None
        self._start_action = None
        self._stop_action = None
        self._autostart_action = None
        self._quit_action = None
        self._build_menu()

    def _build_menu(self):
        self._menu = QMenu()

        self._show_action = QAction("显示主窗口", self._menu)
        self._show_action.triggered.connect(self.show_window_signal.emit)
        self._menu.addAction(self._show_action)
        self._menu.addSeparator()

        self._backup_action = QAction("手动备份", self._menu)
        self._backup_action.triggered.connect(self.manual_backup_signal.emit)
        self._menu.addAction(self._backup_action)
        self._menu.addSeparator()

        self._start_action = QAction("开始监控", self._menu)
        self._start_action.triggered.connect(self.start_monitor_signal.emit)
        self._menu.addAction(self._start_action)

        self._stop_action = QAction("停止监控", self._menu)
        self._stop_action.triggered.connect(self.stop_monitor_signal.emit)
        self._menu.addAction(self._stop_action)
        self._menu.addSeparator()

        self._autostart_action = QAction("开机自启", self._menu)
        self._autostart_action.setCheckable(True)
        self._autostart_action.triggered.connect(
            lambda checked: self.autostart_toggled_signal.emit(checked)
        )
        self._menu.addAction(self._autostart_action)
        self._menu.addSeparator()

        self._quit_action = QAction("退出", self._menu)
        self._quit_action.triggered.connect(self.quit_signal.emit)
        self._menu.addAction(self._quit_action)

        self._tray.setContextMenu(self._menu)

    def set_autostart_checked(self, checked):
        self._autostart_action.setChecked(checked)

    def set_monitoring_active(self, active):
        self._start_action.setEnabled(not active)
        self._stop_action.setEnabled(active)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_window_signal.emit()

    def show(self):
        self._tray.setContextMenu(self._menu)
        self._tray.show()

    def hide(self):
        self._tray.hide()

    def show_message(self, title, message, icon=QSystemTrayIcon.Information):
        key = f"{title}|{message}"
        now = time.monotonic()
        if key == self._last_message_key and now - self._last_message_time < 5:
            return
        self._last_message_key = key
        self._last_message_time = now
        self._tray.showMessage(title, message, icon, 3000)
```

---

### Task 11: 对话框（恢复、孤儿清理、完整性检查）

**Files:**
- Create: `D:\OpenCode\Qiang Backup\ui\restore_dialog.py`
- Create: `D:\OpenCode\Qiang Backup\ui\orphan_dialog.py`
- Create: `D:\OpenCode\Qiang Backup\ui\integrity_dialog.py`

这三个对话框直接沿用旧版代码，仅做文件名和导入路径适配。

- [ ] **Step 1: 编写恢复对话框**

`D:\OpenCode\Qiang Backup\ui\restore_dialog.py` — 从旧版 `ui/restore_dialog.py` 复制，仅修改导入路径：删除 `from engine.reconciliation import delete_orphan_versions` 等业务导入（业务在 MainWindow 调用）。

- [ ] **Step 2: 编写孤儿清理对话框**

`D:\OpenCode\Qiang Backup\ui\orphan_dialog.py` — 从旧版 `ui/reconciliation_dialog.py` 复制，改名为 `OrphanDialog`，移除 `from engine.reconciliation import delete_orphan_versions`。删除操作改为 emit signal 由 MainWindow 处理。

- [ ] **Step 3: 编写完整性检查对话框**

`D:\OpenCode\Qiang Backup\ui\integrity_dialog.py` — 从旧版 `ui/integrity_dialog.py` 复制，移除 `from engine.reconciliation import delete_corrupted_backups`。删除操作改为 emit signal 由 MainWindow 处理。

关键变化：`OrphanDialog` 和 `IntegrityDialog` 需新增 `get_selected()` 方法返回用户选中的条目（供 `MainWindow` 调用删除函数），而非在对话框内部直接执行删除。

`OrphanDialog` 新增方法：
```python
def get_selected(self):
    return [w.item for w in self._item_widgets if w.is_checked()]
```

`IntegrityDialog` 新增方法：
```python
def get_selected(self):
    return [w.item for w in self._item_widgets if w.is_checked()]
```

删除旧版中的 `from engine.reconciliation import delete_orphan_versions` 和 `from engine.reconciliation import delete_corrupted_backups` 导入，将删除操作的 `accept()` 改为仅返回选中条目。

---

### Task 12: 主窗口

**Files:**
- Create: `D:\OpenCode\Qiang Backup\ui\main_window.py`

这是最大的文件。基于旧版 `ui/main_window.py` 重写，核心变化：
1. 移除所有 `state_manager` 导入和 `backup_state.json` 相关逻辑
2. 移除"重建索引"按钮和所有相关 worker/signal
3. 变化检测改用 `engine/change_detector.py`
4. 孤儿清理和完整性检查作为独立按钮
5. 简化启动流程：启动 → 自动扫描变更 → 孤儿检测 → (可选)恢复监控
6. 移除 `_state`、`_state_lock` 等状态管理变量

- [ ] **Step 1: 编写主窗口**

```python
"""Main window for Qiang Backup."""

import os
import sys
import time
import threading
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLineEdit, QListWidget, QTextEdit, QPlainTextEdit,
    QLabel, QSpinBox, QCheckBox, QFileDialog, QMessageBox,
    QProgressDialog, QStatusBar, QSystemTrayIcon, QDialog,
)
from PySide6.QtCore import Qt, QThreadPool, Signal, QObject, QRunnable, QMutex
from PySide6.QtGui import QFont, QCloseEvent, QIcon

from ui.tray_icon import TrayIcon
from engine.config import load_config, save_config
from engine.change_detector import scan_all_sources
from engine.backup_engine import backup_folder, backup_single_file
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
        start = time.monotonic()
        for folder in self.source_folders:
            if self._cancelled:
                break
            self.signals.progress.emit(f"正在扫描 {folder}...")
            from engine.change_detector import get_dirty_files
            dirty = get_dirty_files(folder, self.backup_root, self.extensions)
            if self._cancelled:
                break
            if dirty:
                results[folder] = dirty
                total += len(dirty)
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

            success, total = backup_folder(
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

    def run(self):
        orphans = find_orphaned_backups(
            self.source_folders, self.backup_root, self.extensions
        )
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

    def run(self):
        corrupted = check_backup_integrity(
            self.backup_root, self.extensions, self.password
        )
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
        self._pending_folders = set()
        self._pending_lock = QMutex()
        self._manual_pending = 0
        self._manual_total = 0
        self._manual_scan_running = False
        self._orphan_scan_running = False
        self._restoring = False
        self._quitting = False
        self._restore_msg_shown = False
        self._orphan_dialog = None
        self._integrity_dialog = None

        self._tray = TrayIcon()
        self._setup_tray_signals()

        self._build_ui()
        self._load_config_to_ui()

        self._tray.show()

        if self._config.get("autostart", False):
            set_autostart(True)

        self._startup_scan()

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

        # --- Settings ---
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

        # --- Action buttons ---
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

        # --- Log area ---
        log_box = QGroupBox("备份日志")
        log_layout = QVBoxLayout(log_box)
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self._log_text)
        main_layout.addWidget(log_box, 1)

        # --- Status bar ---
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

    # --- Startup scan ---
    def _startup_scan(self):
        source_folders = self._config.get("source_folders", [])
        backup_root = self._config.get("backup_root", "")
        extensions = self._config.get("extensions", [])
        valid = [f for f in source_folders if Path(f).exists()]

        if not valid or not backup_root:
            return

        self._log("正在扫描文件变更...")
        scan_signals = ScanSignals()
        scan_signals.finished.connect(self._on_startup_scan_done)
        worker = ScanWorker(valid, backup_root, extensions, scan_signals)
        self._threadpool.start(worker)

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

    # --- Orphan check ---
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

        def on_finished(results, elapsed):
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
        est_seconds = total_size / (10 * 1024 * 1024)
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

            def on_one_done():
                self._manual_pending -= 1
                if self._manual_pending <= 0:
                    self._log("── 手动备份完成 ──")
                    self._show_complete_signal.emit(
                        f"手动备份已完成，共处理 {self._manual_total} 个文件夹。"
                    )

            worker = BackupWorker(
                folder, cfg["backup_root"], cfg["extensions"], cfg["password"],
                files=[str(f) for f in dirty],
                max_versions=cfg.get("max_versions", 5),
                signals=self._signals,
                on_folder_done=on_one_done,
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

            total_dirty = 0
            all_dirty = {}
            for fp in folder_paths:
                from engine.change_detector import get_dirty_files
                dirty = get_dirty_files(str(fp), cfg["backup_root"], cfg["extensions"])
                if dirty:
                    all_dirty[str(fp)] = dirty
                    total_dirty += len(dirty)

            if not all_dirty:
                return

            threshold = cfg.get("anomaly_threshold", 3)
            if total_dirty >= threshold or len(folder_paths) >= threshold:
                self._log(f"异常检测：{total_dirty} 个文件/{len(folder_paths)} 个文件夹同时变动，监控已暂停")
                self._tray.show_message(
                    "异常检测",
                    f"发现 {total_dirty} 个文件变更，监控已暂停",
                    QSystemTrayIcon.Warning,
                )
                self._on_stop_monitor()
                return

            for folder_str, dirty in all_dirty.items():
                self._log(f"监控: {folder_str} ({len(dirty)} 个变更)")

                def on_done():
                    pass

                worker = BackupWorker(
                    folder_str, cfg["backup_root"], cfg["extensions"],
                    cfg["password"], files=[str(f) for f in dirty],
                    max_versions=cfg.get("max_versions", 5),
                    signals=self._signals, on_folder_done=on_done,
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
        cfg = self._config
        valid = [f for f in cfg.get("source_folders", []) if Path(f).exists()]
        if not valid or not cfg.get("backup_root"):
            QMessageBox.warning(self, "提示", "请先设置源文件夹和备份路径。")
            return

        progress = QProgressDialog("正在扫描孤儿备份...", "", 0, 0, self)
        progress.setWindowTitle("孤儿清理")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.resize(400, 100)
        self._center_progress(progress)
        progress.show()

        orphan_signals = OrphanScanSignals()

        def on_done(orphans):
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
        self._threadpool.start(OrphanScanWorker(
            valid, cfg["backup_root"], cfg["extensions"], orphan_signals
        ))

    # --- Integrity check ---
    def _on_integrity_check(self):
        cfg = self._config
        if not cfg.get("backup_root"):
            QMessageBox.warning(self, "提示", "请先设置备份路径。")
            return

        progress = QProgressDialog("正在检查备份完整性...", "", 0, 0, self)
        progress.setWindowTitle("完整性检查")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.resize(400, 100)
        self._center_progress(progress)
        progress.show()

        integrity_signals = IntegrityScanSignals()

        def on_done(corrupted):
            try:
                progress.close()
            except Exception:
                pass
            if not corrupted:
                QMessageBox.information(self, "完整性检查", "所有备份文件完好。")
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
        self._threadpool.start(IntegrityScanWorker(
            cfg["backup_root"], cfg["extensions"], cfg.get("password", ""),
            integrity_signals,
        ))

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
        if getattr(self, '_autostart_syncing', False):
            return
        self._autostart_syncing = True
        checked = bool(state)
        self._config["autostart"] = checked
        set_autostart(checked)
        self._tray.set_autostart_checked(checked)
        self._log(f"{'✅ 已开启' if checked else '❌ 已关闭'}开机自启")
        self._autostart_syncing = False

    def _on_autostart_toggled(self, checked):
        if getattr(self, '_autostart_syncing', False):
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
```

---

### Task 13: 程序入口

**Files:**
- Create: `D:\OpenCode\Qiang Backup\main.py`

- [ ] **Step 1: 编写入口文件**

```python
"""Qiang Backup — encrypted file backup tool for engineering software."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QSharedMemory
from PySide6.QtWidgets import QApplication, QMessageBox
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("强哥备份工具")
    app.setOrganizationName("QiangGe")

    lock = QSharedMemory("QiangGeBackupTool_SingleInstance")
    if not lock.create(1):
        QMessageBox.warning(None, "强哥备份", "程序已在运行中。")
        sys.exit(0)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

---

### Task 14: 打包与 README

**Files:**
- Create: `D:\OpenCode\Qiang Backup\QiangBackup.spec`
- Create: `D:\OpenCode\Qiang Backup\README.md`

- [ ] **Step 1: 编写 PyInstaller spec**

```python
# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.ico', '.')],
    hiddenimports=['PySide6.QtCore', 'PySide6.QtWidgets', 'PySide6.QtGui',
                   'watchdog', 'py7zr', 'engine', 'ui', 'utils',
                   'engine.config', 'engine.change_detector',
                   'engine.backup_engine', 'engine.restore_engine',
                   'engine.file_watcher', 'engine.backup_log',
                   'engine.reconciliation',
                   'ui.main_window', 'ui.tray_icon',
                   'ui.restore_dialog', 'ui.orphan_dialog', 'ui.integrity_dialog',
                   'utils.autostart'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='QiangBackup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)
```

- [ ] **Step 2: 编写 README**

```markdown
# 强哥备份工具 (Qiang Backup)

面向广联达等工程计价软件的 Windows 桌面文件级实时备份工具。

## 使用方式

1. 双击运行 `QiangBackup.exe`
2. 添加源文件夹 → 设置备份目录 → 保存配置
3. 点击"开始监控"，最小化到系统托盘
4. 软件自动在文件保存后创建加密备份

## 手动备份 / 恢复 / 清理

- 手动备份：扫描源目录中变更的文件，确认后备份
- 一键恢复：选择文件和版本恢复到原位
- 孤儿清理：删除源文件已不存在的陈旧备份
- 完整性检查：检测损坏的备份存档

## 密码

默认密码为"强哥备份"。请妥善保管密码，丢失密码将无法恢复备份文件。

## 配置文件

`config.json` 存储所有配置。`backup.log` 存储操作日志。

## 打包

```
pip install pyinstaller
pyinstaller QiangBackup.spec
```
```

- [ ] **Step 3: 安装依赖并做快速验证**

```bash
pip install py7zr watchdog PySide6
```

```bash
cd "D:\OpenCode\Qiang Backup"
python main.py
```

验证：窗口正常显示，关闭窗口最小化到托盘，右键退出正常。

---

### Task 15: 集成测试

- [ ] **Step 1: 编写集成测试脚本**

创建 `D:\OpenCode\Qiang Backup\_test.py`:

```python
"""Integration test for core engine modules."""
import tempfile
import shutil
from pathlib import Path

import sys; sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine.config import load_config, save_config
from engine.change_detector import get_dirty_files, scan_all_sources
from engine.backup_engine import backup_single_file, backup_folder
from engine.restore_engine import find_restorable_files, restore_single_file
from engine.reconciliation import find_orphaned_backups, check_backup_integrity
from engine.backup_log import log_backup, log_scan, log_restore

def test_change_detection():
    tmp = Path(tempfile.mkdtemp())
    backup_root = tmp / "backups"
    src = tmp / "src"
    src.mkdir(parents=True)
    backup_root.mkdir()

    test_file = src / "test.GBQ7"
    test_file.write_bytes(b"Hello World v1")

    # No backup exists yet -> dirty
    dirty = get_dirty_files(str(src), str(backup_root), [".GBQ7"])
    assert len(dirty) == 1, f"Expected 1 dirty file, got {len(dirty)}"

    # Backup the file
    ok, _ = backup_single_file(test_file, src, backup_root, "testpass", max_versions=5)
    assert ok, "Backup failed"

    # File unchanged -> not dirty
    dirty = get_dirty_files(str(src), str(backup_root), [".GBQ7"])
    assert len(dirty) == 0, f"Expected 0 dirty files, got {len(dirty)}"

    # File changed -> dirty
    test_file.write_bytes(b"Hello World v2")
    dirty = get_dirty_files(str(src), str(backup_root), [".GBQ7"])
    assert len(dirty) == 1, f"Expected 1 dirty file after change, got {len(dirty)}"

    # Scan all sources
    results, total = scan_all_sources([str(src)], str(backup_root), [".GBQ7"])
    assert total == 1, f"Expected 1 total dirty, got {total}"

    shutil.rmtree(tmp)
    print("✅ change_detector tests passed")


def test_restore():
    tmp = Path(tempfile.mkdtemp())
    backup_root = tmp / "backups"
    src = tmp / "src"
    src.mkdir(parents=True)
    backup_root.mkdir()

    test_file = src / "test.GBQ7"
    original_content = b"Hello World Original"
    test_file.write_bytes(original_content)

    ok, _ = backup_single_file(test_file, src, backup_root, "testpass", max_versions=5)
    assert ok, "Backup failed"

    # Corrupt the file
    test_file.write_bytes(b"corrupted")

    # Find restorable
    restorable, _ = find_restorable_files([str(src)], str(backup_root), [".GBQ7"])
    assert len(restorable) == 1, f"Expected 1 restorable, got {len(restorable)}"

    # Restore
    archive = restorable[0]["versions"][0]["path"]
    ok = restore_single_file(archive, test_file, "testpass")
    assert ok, "Restore failed"
    assert test_file.read_bytes() == original_content, "Restored content mismatch"

    shutil.rmtree(tmp)
    print("✅ restore tests passed")


def test_orphan_detection():
    tmp = Path(tempfile.mkdtemp())
    backup_root = tmp / "backups"
    src = tmp / "src"
    src.mkdir(parents=True)
    backup_root.mkdir()

    test_file = src / "test.GBQ7"
    test_file.write_bytes(b"hello")

    ok, _ = backup_single_file(test_file, src, backup_root, "testpass")
    assert ok

    # Delete source file
    test_file.unlink()

    orphans = find_orphaned_backups([str(src)], str(backup_root), [".GBQ7"])
    assert len(orphans) == 1, f"Expected 1 orphan, got {len(orphans)}"

    shutil.rmtree(tmp)
    print("✅ orphan detection tests passed")


if __name__ == "__main__":
    test_change_detection()
    test_restore()
    test_orphan_detection()
    print("\n🎉 All integration tests passed!")
```

- [ ] **Step 2: 运行测试**

```bash
cd "D:\OpenCode\Qiang Backup"
python _test.py
```

Expected output:
```
✅ change_detector tests passed
✅ restore tests passed
✅ orphan detection tests passed
🎉 All integration tests passed!
```

---
