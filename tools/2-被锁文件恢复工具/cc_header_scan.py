"""扫描 .cc 备份文件头，识别被锁文件"""

import sys
from pathlib import Path
from collections import Counter

LOCKED = b'\x12\x44'

if len(sys.argv) < 2:
    print("用法: python cc_header_scan.py <目录路径>")
    sys.exit(1)

root = Path(sys.argv[1])
files = list(root.rglob("*.cc"))

if not files:
    print("未找到 .cc 文件")
    sys.exit(0)

headers = Counter()
locked_files = []

for i, f in enumerate(files, 1):
    try:
        with open(f, 'rb') as fh:
            header = fh.read(2)
    except OSError:
        continue

    hex_str = header.hex(' ')
    rel = str(f.relative_to(root))

    if header == LOCKED:
        locked_files.append(f)
        status = "[LOCKED]"
    elif header == b'\x50\x4b':
        status = "[ZIP]   "
    elif header == b'\x37\x7a':
        status = "[7z]    "
    else:
        status = f"[{hex_str:6s}]"

    headers[status] += 1
    print(f"[{i:4d}/{len(files)}] {status} | {rel}")

print()
print(f"共 {len(files)} 个 .cc 文件")
for h, c in headers.most_common():
    print(f"  {h}: {c}")

if locked_files:
    print(f"\nWARNING: {len(locked_files)} 个被锁文件，列表已保存到 locked_cc_files.txt")
    with open("locked_cc_files.txt", "w") as out:
        for f in locked_files:
            out.write(str(f) + "\n")
