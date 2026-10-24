"""
utils — 基础设施层

    config_manager.py   单例配置读写（config.json，点号路径 get/update）
    paths.py            项目根目录唯一判定入口（project_root / ROOT）
    asset_manager.py    图标查找与路径缓存（三级降级 + explain_icon_path 来源诊断）
    input_listener.py   输入监听 QThread（键鼠/手柄热切换）+ 按压时长测量
    logger.py           日志（文件 INFO 级 2MB 滚动，控制台 DEBUG 全量）

分层约束
--------
这一层可以被 `core` 和 `ui` 共同依赖，但**自己不反向依赖它们**。
已验证：`grep "from core|from ui" utils/*.py` 为空。

`input_listener.py` 只负责"测量"（这个键按了多久），
"这个时长算不算数"的裁决在 `core.director`。这个划分是有意的：
时间戳在事件第一现场记录，才不会被主线程卡顿污染。

和 core 的区别（一句话）
------------------------
- `core` 回答"**该怎么处理**"——这步该不该推进、这串黑话怎么解
- `utils` 回答"**怎么拿到**"——配置、图标路径、按键事件、日志

所以两者不该合并：core 里已经有 `from utils.config_manager import config`，
是"规则依赖能力"。合起来会让 `script_parser` 这种零依赖纯函数
也被迫和磁盘 IO 绑在一起。
"""
