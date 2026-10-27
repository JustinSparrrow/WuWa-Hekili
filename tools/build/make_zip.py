"""
把发布目录打成 zip。

为什么不用 PowerShell 的 Compress-Archive：
刚 PyInstaller 出来的 exe/dll 会被 Windows Defender 之类短暂占用，
Compress-Archive 遇到就整体报错退出（命令行还返回 0，bat 无从判断），
结果"打包成功"但 zip 根本没生成。这个脚本逐个文件写、遇到占用就重试，
最后把跳过清单报出来 —— 静默丢文件比报错更糟。

    python tools/build/make_zip.py WuWa_Hekili_v2.3 WuWa_Hekili_v2.3_win64.zip
"""

from __future__ import annotations

import os
import sys
import time
import zipfile

RETRIES = 4
RETRY_WAIT = 0.4


def collect(root: str) -> list[tuple[str, str]]:
    """返回 [(绝对路径, zip 内相对路径)]，保持稳定的顺序便于对比。"""
    items = []
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(base, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            items.append((full, rel))
    return items


def add_one(zf: zipfile.ZipFile, full: str, rel: str) -> bool:
    for attempt in range(RETRIES):
        try:
            zf.write(full, rel)
            return True
        except PermissionError:
            # 杀毒软件 / 索引服务正在扫这个文件。等一下再试。
            time.sleep(RETRY_WAIT * (attempt + 1))
        except OSError:
            time.sleep(RETRY_WAIT * (attempt + 1))
    return False


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2

    src, dst = argv[1], argv[2]
    if not os.path.isdir(src):
        print(f"  [ERROR] directory not found: {src}")
        return 1
    if os.path.exists(dst):
        os.remove(dst)

    items = collect(src)
    skipped: list[str] = []

    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for i, (full, rel) in enumerate(items, 1):
            if not add_one(zf, full, rel):
                skipped.append(rel)
            if i % 400 == 0:
                print(f"  packing {i}/{len(items)}")

    size_mb = os.path.getsize(dst) / (1024 * 1024)
    print(f"  zip ok: {os.path.basename(dst)}  {size_mb:.1f} MB  ({len(items) - len(skipped)}/{len(items)} files)")

    if skipped:
        print(f"  [WARN] {len(skipped)} file(s) skipped (locked):")
        for rel in skipped[:10]:
            print(f"         {rel}")
        if len(skipped) > 10:
            print(f"         ... and {len(skipped) - 10} more")
        # 少了 dll 就等于发了个跑不起来的包，这种情况必须当失败
        if any(rel.lower().endswith((".dll", ".pyd")) for rel in skipped):
            print("  [ERROR] skipped files include dll/pyd - this package is incomplete, do NOT publish")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
