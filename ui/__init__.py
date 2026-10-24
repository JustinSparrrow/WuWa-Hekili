"""
ui — 表现层

    theme.py             设计系统：颜色 / 字体 / 连续曲率圆角 / 玻璃面板 / 金环 / 全局 QSS
    frame.py             管理窗口的无边框玻璃外壳（GlassWindow）+ 小标题
    start_menu.py        启动器（最近使用的轴 + 三个入口）
    overlay_window.py    战斗悬浮窗 + 并行轨小窗（胶囊面板、头像、环形进度、格子池）
    widgets.py           单格控件（纯 QPainter 自绘）/ 图片缓存 / 编辑器行
    routine_selector.py  剧本选择
    routine_uploader.py  剧本编辑器（黑话 → 预览 → 保存）
    settings_window.py   按键映射设置（带按键小图预览）

渲染策略
--------
能自绘的一律自绘（theme + 悬浮窗 + 格子），因为 QSS 表达不了连续曲率圆角、
柔和多层阴影和环形进度；表单类控件（下拉框 / 输入框 / 列表 / 滚动条）保留
原生实现，只换 `theme.window_qss()` 的皮 —— 它们有现成的交互逻辑，重写不划算。

职责边界
--------
这一层只负责"把状态画出来"和"收集用户操作"，
**所有判定逻辑在 `core`**。ui 可以读 `director.get_visual_data()` 的结果，
但不要在里面算"这一步该不该推进"。
"""
