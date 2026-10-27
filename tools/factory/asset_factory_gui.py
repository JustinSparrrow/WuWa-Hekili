"""
素材工坊 —— 启动器（真正的窗口在 `ui/asset_factory.py`）。

为什么不直接写在这里
--------------------
这个窗口已经并进主菜单，和其它窗口共用同一套设计系统（`ui.theme` + `ui.frame`）。
如果还把界面代码留在 tools/ 下，就得从 tools 反向 import ui 的绘制层，
两边样式也会慢慢分叉。所以界面搬到 `ui/`，这里只留一个入口，
让 `python tools/factory/asset_factory_gui.py` 和 PyInstaller 打包继续可用。

用法
----
    python tools/factory/asset_factory_gui.py
"""

import os
import sys

# 独立运行：就地向上找到项目根（含 main.py）并加入 import 路径
_root = os.path.abspath(__file__)
while True:
    _root = os.path.dirname(_root)
    if os.path.exists(os.path.join(_root, "main.py")) or _root == os.path.dirname(_root):
        break
if _root not in sys.path:
    sys.path.insert(0, _root)

from ui.asset_factory import AssetFactoryWindow, main  # noqa: E402,F401

__all__ = ["AssetFactoryWindow", "main"]

if __name__ == "__main__":
    sys.exit(main())
