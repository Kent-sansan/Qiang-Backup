"""Change detection -- compare current files against latest backup archives.

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


def _compute_sha256(file_path):
    """Compute SHA-256 hex digest of entire file."""
    h = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _compute_safe_stem(filename):
    return filename


def _get_source_folder_name(source_root):
    """Get display name for source folder: 'OneDrive' for D:\\OneDrive, 'D盘' for D:\\."""
    source_root = Path(source_root)
    if source_root.parent == source_root:
        drive = source_root.drive
        return drive[0] + '盘' if drive else source_root.name
    return source_root.name


def _get_relative_mirror_dir(source_file, source_root):
    """Get the mirror directory path relative to source_root, prefixed with source folder name."""
    source_file = Path(source_file)
    source_root = Path(source_root)
    folder_name = _get_source_folder_name(source_root)
    rel = source_file.relative_to(source_root)
    return str(Path(folder_name) / rel.parent)


def _find_latest_backup_hash(source_file, source_root, backup_root):
    """Find known archive hashes for a source file.
    Returns (latest_archive, latest_hash, all_hashes) or (None, None, set()) if no backup exists."""
    backup_root = Path(backup_root)
    source_root = Path(source_root)

    try:
        mirror_dir = _get_relative_mirror_dir(source_file, source_root)
    except ValueError:
        return None, None, set()

    backup_dir = backup_root / mirror_dir
    safe_stem = _compute_safe_stem(source_file.name)

    if not backup_dir.exists():
        return None, None, set()

    pattern = re.compile(
        rf"^{re.escape(safe_stem)}_(\d{{8}})_(\d{{6}})_([0-9a-f]{{16}})\.7z$"
    )

    latest = None
    latest_ts = ""
    latest_hash = None
    all_hashes = set()

    for archive in backup_dir.glob("*.7z"):
        m = pattern.match(archive.name)
        if m:
            h = m.group(3)
            all_hashes.add(h)
            ts = f"{m.group(1)}_{m.group(2)}"
            if ts > latest_ts:
                latest_ts = ts
                latest = archive
                latest_hash = h

    return latest, latest_hash, all_hashes


def compute_file_hash16(file_path):
    """Compute full SHA-256 and return first 16 hex chars."""
    full_hash = _compute_sha256(file_path)
    if full_hash is None:
        return None
    return full_hash[:16]


def get_dirty_files(source_folder, backup_root, extensions, source_root=None, progress_cb=None):
    """Scan a source folder and return list of files that need backup.

    A file needs backup if:
    - No backup archive exists for it (new file)
    - Its current content hash is not in any known backup hash set

    progress_cb(file_path) is called for each scanned file.
    """
    source_folder = Path(source_folder)
    if source_root is None:
        source_root = source_folder
    source_root = Path(source_root)
    backup_root = Path(backup_root)
    dirty = []

    if not source_folder.exists():
        return dirty

    for f in safe_rglob(source_folder, extensions):
        if progress_cb and not progress_cb(f):
            break
        latest_archive, backup_hash, all_hashes = _find_latest_backup_hash(f, source_root, backup_root)

        if latest_archive is None:
            dirty.append(f)
            continue

        current_hash = compute_file_hash16(f)
        if current_hash is None:
            continue

        if current_hash not in all_hashes:
            dirty.append(f)

    return dirty


def scan_all_sources(source_folders, backup_root, extensions, progress_cb=None):
    """Scan all source folders, return {folder: [dirty_files]} and total count."""
    results = {}
    total = 0
    for folder in source_folders:
        dirty = get_dirty_files(folder, backup_root, extensions, progress_cb=progress_cb)
        if dirty:
            results[folder] = dirty
            total += len(dirty)
    return results, total
