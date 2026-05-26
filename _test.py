"""Integration test for core engine modules."""
import tempfile
import shutil
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from engine.config import load_config, save_config
from engine.change_detector import get_dirty_files, scan_all_sources
from engine.backup_engine import backup_single_file, backup_folder
from engine.restore_engine import find_restorable_files, restore_single_file
from engine.reconciliation import find_orphaned_backups, check_backup_integrity


def test_change_detection():
    tmp = Path(tempfile.mkdtemp())
    backup_root = tmp / "backups"
    src = tmp / "src"
    src.mkdir(parents=True)
    backup_root.mkdir()

    test_file = src / "test.GBQ7"
    test_file.write_bytes(b"Hello World v1")

    dirty = get_dirty_files(str(src), str(backup_root), [".GBQ7"])
    assert len(dirty) == 1, f"Expected 1 dirty file, got {len(dirty)}"

    ok, _ = backup_single_file(test_file, src, backup_root, "testpass", max_versions=5)
    assert ok, "Backup failed"

    dirty = get_dirty_files(str(src), str(backup_root), [".GBQ7"])
    assert len(dirty) == 0, f"Expected 0 dirty files, got {len(dirty)}"

    test_file.write_bytes(b"Hello World v2")
    dirty = get_dirty_files(str(src), str(backup_root), [".GBQ7"])
    assert len(dirty) == 1, f"Expected 1 dirty file after change, got {len(dirty)}"

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

    test_file.write_bytes(b"corrupted")

    restorable, _ = find_restorable_files([str(src)], str(backup_root), [".GBQ7"])
    assert len(restorable) == 1, f"Expected 1 restorable, got {len(restorable)}"

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
    assert ok, "Backup failed"

    test_file.unlink()

    orphans = find_orphaned_backups([str(src)], str(backup_root), [".GBQ7"])
    assert len(orphans) == 1, f"Expected 1 orphan, got {len(orphans)}"

    shutil.rmtree(tmp)
    print("✅ orphan detection tests passed")


def test_integrity():
    tmp = Path(tempfile.mkdtemp())
    backup_root = tmp / "backups"
    src = tmp / "src"
    src.mkdir(parents=True)
    backup_root.mkdir()

    test_file = src / "test.GBQ7"
    test_file.write_bytes(b"hello")

    ok, _ = backup_single_file(test_file, src, backup_root, "testpass")
    assert ok, "Backup failed"

    corrupted = check_backup_integrity(str(backup_root), [".GBQ7"], "testpass")
    assert len(corrupted) == 0, f"Expected 0 corrupted, got {len(corrupted)}"

    corrupted = check_backup_integrity(str(backup_root), [".GBQ7"], "wrongpass")
    assert len(corrupted) == 1, "Should detect corruption with wrong password"

    shutil.rmtree(tmp)
    print("✅ integrity tests passed")


if __name__ == "__main__":
    test_change_detection()
    test_restore()
    test_orphan_detection()
    test_integrity()
    print("\n🎉 All integration tests passed!")
