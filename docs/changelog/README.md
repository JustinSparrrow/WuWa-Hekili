# AI 改动记录（Changelog）

本目录记录**由 AI 助手参与的每一次代码改动**，区别于人工提交。

原始 v1.0 是作者手写的可运行版本（已备份在根目录 `WuWa_Hekili_v1.0/`），
从 v1.1 起的所有重构、修 bug、加功能都在这里留档，方便回溯"这行为什么变成这样"。

## 文件命名

```
v<主>.<次>-<一句话概括>.md
```

例：`v1.3-时间轴引擎.md`

- **主版本**：架构或规则发生根本变化的，升主版本
- **次版本**：修 bug、优化、加参数，递增次版本
- 一份文件对应一轮**完整可交付**的改动（能跑、能测、能回滚）

## 版本总览

| 版本 | 主题 | 触发原因 | 主要影响面 |
|---|---|---|---|
| [v1.1](v1.1-性能与稳定.md) | 内存与流畅度优化 | 作者要求"占内存更低、更流畅" | 资源层 / 悬浮窗 / 输入线程 / 启动流程 |
| [v1.2](v1.2-长短按判定.md) | 轻按与长按区分 | 重击与普攻共用一个键，轻按也被判成重击 | `director.py` / `input_listener.py` / 黑话语法 |
| [v1.3](v1.3-时间轴引擎.md) | 预输入 / 连按 / 并行双轨 | 程序把按键当施法，导致空转、跑飞、无法双键并行 | `director.py` / `overlay_window.py` / 剧本格式 |
| [v1.4](v1.4-同键缓冲规则.md) | 闸门只对同键生效 | 鸣潮换键优先级高，换键不该排队 | `director.py` / 测试 / README |
| [v1.5](v1.5-解析器分层与体检.md) | 解析器分层 + 剧本体检 | 作者提出「导演→剧本→演出」三层，指出转换层与道具层不完整 | `tools/script_parser.py`（后移至 core）/ `routine_lint.py`（新）/ `asset_manager.py` |
| [v1.6](v1.6-结构规范化.md) | 项目结构规范化（**破坏性**） | "软件最重要的是干净和一看即懂" | 全项目目录、import、素材路径 |
| [v1.7](v1.7-素材数据工具.md) | wiki 爬虫重写 + 角色数据补齐 | 裁图抄数据工作量太大，旧爬虫跑不通 | `tools/factory/wiki_spider.py`、`Character_Occupation.txt` |
| [v1.8](v1.8-技能图标来源.md) | 技能图标批量下载 + 角色档案拆分 | "图片总不能一帧一帧截吧" | `tools/factory/icon_fetcher.py`（新）、`build_db.py`（新）、`asset_manager.py` |
| [v2.0](v2.0-界面重制.md) | 界面重制（设计系统 + 全部窗口） | "pyqt 做不出好看的界面，来点鸣潮装饰，喜欢苹果那种风格" | `ui/theme.py`（新）、`ui/frame.py`（新）、全部 `ui/*.py`、`tools/preview_ui.py`（新） |
| [v2.1](v2.1-双主题.md) | 夜间 / 日间双主题 | "白色系我也喜欢，最好能自己选是否开夜间模式" | `ui/theme.py`（调色板化）、全部 `ui/*.py` 的颜色引用、`settings_window.py` |

## 每份记录必含的六段

1. **背景 / 触发** — 谁提的、现象是什么、为什么必须改
2. **根因** — 改之前的代码为什么会产生这个现象（贴关键行）
3. **改法** — 改成了什么，以及为什么选这个方案而不是别的
4. **改动文件清单** — 逐文件说明动了什么
5. **验证** — 跑了哪些测试、实测数字
6. **遗留 / 风险** — 这次故意没做的、以及改完可能引入的新问题

## 维护约定

- **只增不改**：已发布的记录不要回头修改结论。发现写错了，新开一份记录说明修正。
- **改动结论必须能被验证**：写"快 24 倍"就要能指出是哪个 benchmark 跑出来的。
- **诚实记录失败**：方案试过但回退的，也写进去（附原因），避免下次重踩。

## 与代码的对应关系

| 功能点 | 落点文件 |
|---|---|
| 状态机 / 时间轴 / 手势裁决 | `core/director.py` |
| 黑话 → JSON 剧本（分层解析） | `core/script_parser.py` |
| 按键感知 / 按压时长测量 | `utils/input_listener.py` |
| 设计系统（颜色/字体/形状/面板绘制） | `ui/theme.py` |
| 管理窗口无边框外壳 | `ui/frame.py` |
| 悬浮窗 / 并行小窗 / 动画 | `ui/overlay_window.py`、`ui/widgets.py` |
| 角色元素 / 中文名查询 | `utils/character_meta.py` |
| UI 预览与截图 | `tools/preview_ui.py`（产出 `docs/ui/*.png`） |
| 图标查找与缓存 | `utils/asset_manager.py` |
| 剧本体检 / 素材审计 | `tools/checks/routine_lint.py` |
| 素材目录脚手架 | `tools/scaffold.py` |
| 角色数据爬取 | `tools/factory/wiki_spider.py`（产出 `factory/db/characters.json`） |
| 内存观测 | `tools/checks/mem_probe.py`（外部进程）、`mem_bench.py`（内部压测） |
| 回归测试 | `tests/test_script_parser.py`、`test_director_press.py`、`test_managers.py` |
