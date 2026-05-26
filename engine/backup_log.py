"""Structured JSONL backup log -- append-only operation record."""

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
