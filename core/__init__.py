"""
core — 领域逻辑层

放"和游戏机制有关、但不依赖窗口"的部分：

    director.py        状态机：剧本指针 / 时间闸门 / 输入缓冲 / 并行双轨 / 回退栈
    script_parser.py   黑话字符串 <-> 剧本动作数组（Lexer → Parser → AST → Resolver → Writer）

分层约束（加新文件请遵守）
--------------------------
- **不 import PySide6**。这一层要能在无窗口环境里跑（CI、命令行测试）。
  已验证：`grep PySide6 core/*.py` 为空。
- **不 import ui**。core 不知道界面存在。
- **不直接读磁盘素材**，图标路径通过 `utils.asset_manager` 注入进来。
- 判定逻辑尽量做成模块级纯函数（如 `is_long_press` / `press_matches`），
  单测可以直接喂"时长"参数，不必起 Qt 事件循环。

新文件放哪：三个问题全"是"才放 core
-----------------------------------
1. 它描述的是**规则**吗？（该不该推进 / 这串字符怎么解 / 什么算长按）
2. 去掉界面和磁盘，它还能工作吗？
3. 只靠传入的参数，能写单元测试吗？

对照现有文件：

| 文件 | 放哪 | 为什么 |
|---|---|---|
| `director.py` | core | 规则；IO 全靠注入（clock / asset_mgr）；可单测 |
| `script_parser.py` | core | 纯标准库，零依赖，输入字符串输出 dict |
| `asset_manager.py` | utils | 要 `os.listdir` 扫磁盘 |
| `input_listener.py` | utils | 要 QThread + 键盘/手柄/鼠标外设 |
| `config_manager.py` | utils | 要读写 `config.json` |

**所以 core 和 utils 不是平级的两堆代码，是"规则"依赖"能力"。**
合并会让 `script_parser` 这种纯函数也得拖着一个会读磁盘的邻居，
以后想单测就得先准备 config.json 和素材目录。

历史
----
`core/preset/director.py` 曾按"多方案"预留了 `core/engine/`（读内存版状态机），
但读内存对鸣潮不可行（腾讯 ACE 内核反作弊，见 README 的调研结论），
`engine/` 已删除，`director.py` 提到 core 根目录。
"""
