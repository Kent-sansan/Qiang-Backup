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


def log_backup(source_path, archive_path, sha256, size, batch_id=None):
    entry = {
        "type": "backup",
        "source": str(source_path),
        "archive": str(archive_path),
        "sha256": sha256,
        "size": size,
    }
    if batch_id:
        entry["batch_id"] = batch_id
    _append_entry(entry)


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


def get_batch_files(batch_id):
    """查询指定批次的所有备份文件"""
    files = []
    try:
        with open(_log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "backup" and entry.get("batch_id") == batch_id:
                        files.append(entry["archive"])
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return files


def get_recent_batches(limit=10):
    """查询最近的备份批次，只返回文件实际存在的批次"""
    batches = {}
    deleted_archives = set()
    try:
        with open(_log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "delete":
                        for p in entry.get("archive_paths", []):
                            deleted_archives.add(p)
                    if entry.get("type") == "backup" and entry.get("batch_id"):
                        batch_id = entry["batch_id"]
                        archive = entry["archive"]
                        if batch_id not in batches:
                            batches[batch_id] = {
                                "batch_id": batch_id,
                                "files": [],
                                "timestamp": entry.get("ts", ""),
                                "count": 0,
                            }
                        batches[batch_id]["files"].append(archive)
                        batches[batch_id]["count"] += 1
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass

    valid_batches = []
    for batch_id, batch in batches.items():
        existing_files = [f for f in batch["files"] if f not in deleted_archives and Path(f).exists()]
        if existing_files:
            batch["files"] = existing_files
            batch["count"] = len(existing_files)
            valid_batches.append(batch)

    valid_batches.sort(key=lambda x: x["timestamp"], reverse=True)
    return valid_batches[:limit]


def delete_batch_files(batch_id):
    """删除指定批次的所有备份文件"""
    files = get_batch_files(batch_id)
    deleted = 0
    for filepath in files:
        try:
            Path(filepath).unlink(missing_ok=True)
            deleted += 1
        except OSError:
            pass
    log_delete("batch_undo", files)
    return deleted
