"""备份被锁文件自检工具 — 检查备份归档中是否混入了被锁文件"""

import sys
import tempfile
from pathlib import Path

try:
    import py7zr
except ImportError:
    print("请先安装 py7zr：pip install py7zr")
    sys.exit(1)

LOCKED_HEADER = b'\x12\x44'


def check_archive(archive_path, password=None):
    """检查单个 .7z 归档是否包含被锁文件"""
    archive_path = Path(archive_path)
    try:
        with py7zr.SevenZipFile(archive_path, 'r', password=password) as szf:
            file_list = szf.getnames()
            if not file_list:
                return None  # 空归档

            with tempfile.TemporaryDirectory() as tmpdir:
                szf.extractall(tmpdir)
                for name in file_list:
                    extracted = Path(tmpdir) / name
                    if extracted.is_file():
                        try:
                            with open(extracted, 'rb') as f:
                                header = f.read(2)
                            if header == LOCKED_HEADER:
                                return True  # 发现被锁文件
                        except OSError:
                            pass
            return False  # 正常文件
    except Exception as e:
        return f"错误: {e}"


def main():
    if len(sys.argv) < 2:
        print("用法: python lock_checker.py <备份目录路径> [密码]")
        print()
        print("示例: python lock_checker.py D:\\强哥备份 强哥备份")
        print()
        print("功能: 扫描备份目录中所有 .7z 归档，检查是否混入了被锁文件")
        sys.exit(1)

    password = sys.argv[2] if len(sys.argv) > 2 else None

    backup_dir = Path(sys.argv[1])
    if not backup_dir.exists():
        print(f"目录不存在: {backup_dir}")
        sys.exit(1)

    archives = list(backup_dir.rglob("*.7z"))
    if not archives:
        print("未找到 .7z 备份文件")
        return

    total = len(archives)
    locked_count = 0
    error_count = 0
    normal_count = 0

    print(f"扫描 {total} 个备份归档...\n")

    for i, archive in enumerate(archives, 1):
        result = check_archive(archive, password)
        relpath = archive.relative_to(backup_dir)

        if result is True:
            print(f"  [{i}/{total}] ⚠ 被锁: {relpath}")
            locked_count += 1
        elif result is False:
            normal_count += 1
            if i % 20 == 0:
                print(f"  [{i}/{total}] ✓ 正常 ({normal_count} 个)")
        else:
            print(f"  [{i}/{total}] ✗ {relpath} — {result}")
            error_count += 1

    print(f"\n{'='*50}")
    print(f"扫描完成: {total} 个归档")
    print(f"  正常:     {normal_count}")
    print(f"  被锁:     {locked_count}")
    print(f"  错误:     {error_count}")

    if locked_count > 0:
        print(f"\n⚠ 发现 {locked_count} 个备份归档包含被锁文件！")
        print("建议: 在恢复这些备份时注意，其内容可能是无用的锁定状态文件。")
    else:
        print("\n✓ 所有备份归档均正常，未发现被锁文件。")


if __name__ == "__main__":
    main()
