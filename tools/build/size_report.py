"""
打印发布目录的体积，供 build.bat 调用。

单独拆出来的原因：在 bat 里用 powershell 拼统计命令，引号和管道转义
很容易被 cmd 吃掉，出错还很难看出来。交给 python 一行搞定。
"""

import os
import sys


def dir_size_mb(path: str) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total / (1024 * 1024)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = argv[1]
    if not os.path.isdir(path):
        print(f"  Size: n/a ({path} not found)")
        return 1
    print(f"  Size: {dir_size_mb(path):.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
