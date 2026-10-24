"""
utils.paths — 项目根目录的唯一判定入口

历史上有 6 个文件各自写了一遍 `_project_root()`，实现大同小异
（向上找含 main.py 的目录，回退用 dirname 次数），散落三处：
ui/（routine_selector / settings_window / start_menu）、
tools/（routine_lint / mem_bench / preview_ui）、utils/character_meta。

每份都有细微差别：有的走 5 层、有的 6 层、有的 8 层，回退深度也不一样。
脚本一旦被移动，这些"写死的层数"就会静默算错根目录，导致素材/配置
全部查不到，且报错位置离真正的 bug 很远。

所以统一收敛到这里：一个函数、一个回退逻辑、打包前后都覆盖。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def project_root() -> Path:
    """
    返回项目根目录（含 main.py 的那个目录）。

    判定顺序：
    1. 打包运行（PyInstaller 等）时，根 = 可执行文件所在目录；
       此时资源被解包到 exe 同级，不能用源码的 __file__ 反推。
    2. 开发环境：从当前文件向上找第一个含 main.py 的目录。
       用标志文件而非"固定 dirname 次数"，脚本搬到哪里都能找对。
    3. 都找不到时回退到仓库根（向上两级），绝不返回 None。

    返回 Path 而非 str，调用方要字符串时自行 str()。
    """
    # 1) 打包运行
    if getattr(sys, "frozen", False):
        return Path(os.path.dirname(sys.executable))

    # 2) 向上找含 main.py 的目录（从本文件所在目录出发，封顶 12 层）
    cur = Path(__file__).resolve().parent
    for _ in range(12):
        if (cur / "main.py").is_file():
            return cur
        parent = cur.parent
        if parent == cur:      # 到文件系统根了，别再往上
            break
        cur = parent

    # 3) 回退：utils/ 的上两级就是仓库根
    return Path(__file__).resolve().parent.parent.parent


# 便捷别名：很多脚本在模块加载时就要求根目录，直接取一次缓存起来
ROOT = project_root()
