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
            for archive in backup_dir.glob("*.7z"):
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
