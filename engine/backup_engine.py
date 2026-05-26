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
