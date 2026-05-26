"""Orphan backup detection and integrity checking."""

import re
import time
from pathlib import Path
from collections import defaultdict

import py7zr

from engine.backup_log import log_delete


def _parse_backup_filename(basename, extensions):
    m = re.search(r'_(\d{8})_(\d{6})_([0-9a-f]{16})\.7z$', basename)
    if not m:
        return None
    safe_stem = basename[:m.start()]
    if not safe_stem:
        return None
    date_str = m.group(1)
    time_str = m.group(2)
    file_hash = m.group(3)

    stem_lower = safe_stem.lower()
    for ext in sorted(extensions, key=len, reverse=True):
        ext_dot = ext.lower()
        if stem_lower.endswith(ext_dot):
            return safe_stem, f"{date_str}_{time_str}", file_hash
    return None


def _collect_archive_entries(backup_root, extensions):
    root = Path(backup_root)
    if not root.exists():
        return []
    entries = []
    try:
        for archive_path in root.rglob("*.7z"):
            parsed = _parse_backup_filename(archive_path.name, extensions)
            if parsed is None:
                continue
            original_name, ts, file_hash = parsed
            relative_parent = str(archive_path.parent.relative_to(root))
            entries.append((archive_path, relative_parent, original_name, ts, file_hash))
    except (OSError, PermissionError):
        pass
    return entries


def _filter_accessible_sources(source_folders):
    return [f for f in source_folders if Path(f).exists()]


def find_orphaned_backups(source_folders, backup_root, extensions):
    """Find backup archives whose source files no longer exist."""
    accessible = _filter_accessible_sources(source_folders)
    if not accessible:
        return []

    entries = _collect_archive_entries(backup_root, extensions)
    if not entries:
        return []

    orphan_map = defaultdict(list)
    for archive_path, relative_parent, original_name, ts, _fh in entries:
        found = False
        for src in accessible:
            candidate = Path(src) / relative_parent / original_name
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
        ok = False
        for attempt in range(2):
            try:
                with py7zr.SevenZipFile(archive_path, "r", password=password):
                    pass
                ok = True
                break
            except FileNotFoundError:
                break
            except Exception:
                if attempt == 0:
                    time.sleep(0.5)
        if not ok:
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
