# 项目缺口评估（不含视觉 2.0）

> 评估时点：2026-10-25，对应代码版本 v1.4
> 范围：**只讨论"不引入游戏画面识别"的前提下，项目还缺什么**
> 结论基于实际读代码 + 跑测试，每一条都指到了具体位置，可自行验证
>
> **更新（v1.5）**：P0 第 1 条已解决（`tools/routine_lint.py` + 加载前体检）；
> P0 第 2 条**部分解决**——底层能力（`ScriptParser.render` 往返一致）已具备，
> 但编辑器还在走旧保存逻辑，字段依然会丢。详见
> [changelog/v1.5](changelog/v1.5-解析器分层与体检.md)。
>
> **更新（v1.6）**：P1 第 6 条已解决（`tests` 与 `assets/input` 已纳入版本库）；
> 同时做了全项目结构规范化（目录、import、素材路径）。详见
> [changelog/v1.6](changelog/v1.6-结构规范化.md)。
> 本文档中提到的路径若与 v1.6 之前一致，均已随手更新；历史记录见 changelog。
>
> **更新（v1.7）**：P2 第 10 条的**数据部分**已解决——wiki 爬虫重写，
> 65 个角色的武器/元素全部抓到，`Character_Occupation.txt` 从 8 条补到 44 条。
> 剧本数量仍是 1 个（内容问题）。详见 [changelog/v1.7](changelog/v1.7-素材数据工具.md)。

## 一句话结论

引擎层（时间轴、手势判定、并行）已经够用了，**真正拖后腿的是"数据层"和"容错层"**：
剧本没有校验、参数没有 UI、编辑器会吞字段、出错没有提示。

换句话说：**核心能力已经到 7 分，但用户碰到问题的概率仍然很高，且出了问题无法自救。**

---

## P0 — 会造成数据损坏或无声错误

### 1. 剧本没有任何校验 ✅ 已在 v1.5 解决

**现状**

```python
# main.py:178
self.director = Director(
    team_config={int(k): v for k, v in data["team_config"].items()},  # KeyError 直接抛
    opener_script=data["opener_script"],                              # 同上
    ...
)
```

`Director` 内部再用 `self.team.get(idx, "Unknown")` 兜底。

**三类后果**

| 情况 | 表现 | 用户能否理解 |
|---|---|---|
| 缺 `team_config` / `opener_script` 键 | 加载时抛 `KeyError`，弹一个英文异常框 | 否 |
| `next_char` 写了不存在的槽位（如 4） | 画面显示 `Unknown`，图标落到通用图 | 否，会以为"图没做" |
| `custom_icon` 指向不存在的文件 | 静默降级到通用图，无日志 | 否 |

**为什么这是 P0**：作者自己在做剧本时会频繁改 JSON。改错一个字段 → 程序崩溃或
显示错乱 → 但没有任何信息告诉他"哪一行错了"。这会把调试成本放大到劝退级别。

**建议** —— ✅ 已实现为 `tools/routine_lint.py`

```bash
python tools/routine_lint.py <剧本.json>
python tools/routine_lint.py --all
python tools/routine_lint.py --assets-only
```

覆盖：必需字段、`type` 白名单、`next_char` 越界、`custom_icon` 文件存在性、
`variant` 与图标编号冲突、`duration_ms` 合理性、素材来源分级、武器映射覆盖率。

已接进 `main._preflight()`，加载前只拦 error 并弹窗列前 5 条。

### 2. 编辑器会静默吞掉手写字段 ⬜ 底层已备，UI 未接

**现状**

`ui/routine_uploader.py` 保存时会**从黑话字符串重新解析生成动作数组**。
除了 `custom_icon` 之外，这些字段全部丢失：

```
parallel        v1.3 引入，标记"蓄力中可同时按"
uncancellable   v1.4 引入，标记"换键也打断不了"
duration_ms     单步时长覆盖
hold / hold_time 手势声明（可用 + 语法替代）
```

**后果**：用户手改 JSON 加了 `"parallel": true` → 过几天想改个描述 → 打开编辑器
→ 点保存 → **并行标记没了，功能退回**。而他不会知道发生了什么。

这比"不提供这个功能"更糟，因为它**破坏用户已有的工作**。

**建议**（v1.5 之后成本大幅下降）

- **方案 B（推荐，现在很便宜）**：`ScriptParser.render(actions, names)` 已经能把
  动作数组还原成带 `+ ! & {ms} *N` 的黑话字符串，且真实剧本往返测试通过。
  编辑器只要在"载入剧本"时用 `render` 回填文本框、而不是用 `original_*` 原文，
  这些字段就天然被写进字符串里，保存时不会再丢。
- **方案 A**：编辑器里给这些字段加 UI（「可同时」「不可打断」「自定义时长」开关）。
  体验更好，但要改动作行的渲染，成本高。

> **注意还有一个死结**：`custom_icon` 在黑话语法里**没有表达方式**，
> 所以它仍然只能在 JSON 层存在。`render` 不会输出它，编辑器重新保存依然会丢。
> 这是下一步要解决的重点（要么加语法，要么把编辑器改成"以 JSON 为主、黑话只做辅助"）。

---

## P1 — 影响可用性，但不损坏数据

### 3. `timing` 全套参数没有 UI 入口

**现状**：`config.json` 的 `timing` 段（`input_buffer_ms` / `durations_ms` /
`character_durations` / `enable_parallel`）**只能手改文件**。
设置窗口（`ui/settings_window.py`）只有两个 Tab：手柄映射、键盘映射。

**后果**：这直接导致"手感调不好"——而这些参数是**必须按个人节奏调**的。
作者自己能改，但每个用户都得自己去翻 JSON。

**建议**：设置窗加第三个 Tab「手感」：

| 控件 | 映射到 |
|---|---|
| 滑块：预输入缓冲 100~500ms | `timing.input_buffer_ms` |
| 滑块：普攻占位 250~600ms | `durations_ms.basic` |
| 开关：启用并行 | `timing.enable_parallel` |
| 开关：严格轻按判定 | `settings.strict_tap_check` |
| 下拉：应用预设（偏快 / 标准 / 偏慢） | 一次性改一组值 |

再加一个「实时生效」按钮，不用重启程序。

> 更省事的版本：只做一个滑块「整体节奏快慢」，内部按比例缩放整张
> `durations_ms`。用户只需要调一个东西，这已经能解决 80% 的抱怨。

### 4. 没有暂停 / 跳过 / 重来

**现状**：只有 `rollback`（回退一步，最多 20 步）和 `reset`（回到开头）。
没有"暂停"，也没有"跳过当前这一步"。

**场景**：打错了一个技能，玩家想跳到下一步而不是倒回一步；或者想在中途休息一下。

**建议**：加两个按键映射项 `pause` 和 `skip`。`skip` 在 Director 里就是
`advance()` 但不算正确率；`pause` 只需要一个布尔位挡住 `input_received`。

### 5. 没有练习反馈：不知道自己练得怎么样，也没法标定时长

**现状**：`timing_summary()` 会在退出时打一行日志，但那组数字**要用户自己去翻
logs 文件手抄到 config**。而且没有正确率、没有每步耗时、没有卡在哪一步。

**后果**：这是一个"练习工具"，却没有练习工具最该有的东西。

**建议**：加一个结束结算面板：

```
本次练习
  总步数      88
  正确推进    81  (92.0%)
  手势判错     5   ← 该长按却轻点 3 次，该轻按却按住 2 次
  最长卡顿     步骤 37「解放2」，停留 2.4s
  观测节奏     basic 362ms / heavy 688ms / skill 511ms
               [一键写回配置]
```

最后那个按钮直接解决"标定时长"的问题，比日志手抄体验好一个数量级。

### 6. `assets/ui/` 和 `tests/` 被 `.gitignore` 排除 ✅ 已在 v1.6 解决

**原状**

```
.gitignore:
    assets/ui       ← 按键图标（键盘/手柄/PS）
    tests           ← 所有测试
```

- `assets/ui` 不在版本库里 → 别人 clone 下来，**设置窗口直接显示"未找到图标"，
  按键映射无法调整**。打包时 `build.bat` 会从本地拷，所以发布包没问题，
  但**任何协作者都跑不了开发环境**
- `tests` 不在版本库里 → 89 项回归测试 **根本不会提交**，等于白写。
  任何人改了 `director.py` 都没法验证有没有破坏

**已做**：两行都从 `.gitignore` 删除；`assets/ui` 同时改名为 `assets/input`
（避免和代码里的 `ui/` 目录同名）。`assets/video`（2.6G）和 `kenney` 原始素材包
仍排除在外，这是对的。

---

## P2 — 工程健壮性，平时不疼、出事很疼

### 7. `Director` 是 1192 行的上帝对象

现在它同时承担 6 类职责：

| 职责 | 大致行范围 |
|---|---|
| 剧本导航（指针 / 切轴 / 回退栈） | 300~600 |
| 手势裁决（tap/hold 判定） | 模块级 + 700~900 |
| 时间轴（闸门 / 缓冲 / 心跳） | 900~1100 |
| 并行双轨（探测 / 集合 / 小窗数据） | 700~800 |
| 视觉数据组装（图标 / 角色推演） | 600~700 |
| 配置读取 | 200~300 |

**不是必须现在拆**，但它已经是"改一处要考虑五处"的状态。
建议在下一次要加功能（比如角色 profile）时，顺手拆成：

```
core/preset/script.py     剧本导航 + 切轴 + 回退
core/preset/gesture.py    手势裁决（纯函数，已可拆）
core/preset/timeline.py   闸门 / 缓冲 / 并行
core/preset/director.py   组装 + 对外接口
```

注意：`core/engine/` 目录现在是**空的**（只有一个 `__init__.py`），
看起来是之前留的坑位。

### 8. 没有全局异常兜底

**现状**：`main.py:207 on_action_detected()` 是 Qt 槽函数，内部没有 try。
且 `start_execution()` 之外的初始化（`Director(...)`）也没有 try。

**后果**：槽函数里抛异常，PySide6 默认只打一行 traceback 到 stderr
（打包成 `-w` 无控制台后就**彻底看不见**）。程序不会崩，但**状态机卡死**，
玩家只看到"按什么都没反应"，没有任何提示。

**建议**：在 `on_action_detected` 和 `on_tick` 外层包一层：

```python
try:
    ...
except Exception:
    log.exception("输入处理异常")
    if not self._error_shown:          # 只弹一次，避免刷屏
        self._error_shown = True
        QMessageBox.warning(None, "内部错误",
            "程序出现异常，已记录到 logs/。\n建议按回退键或重启悬浮窗。")
```

### 9. 没有 DPI 适配

**现状**：`main.py` 里没有 `HighDpiScaleFactorRoundingPolicy`，
`overlay_window.py` 里没有 `devicePixelRatio` 相关处理，尺寸全是硬编码像素
（400×150、槽位 W/H 常量）。

**后果**：Windows 缩放设为 125% / 150% / 200% 时：

- 图标可能模糊（位图被拉伸）
- 悬浮窗尺寸与预期不符，可能盖住游戏 UI
- 多显示器不同缩放时，拖到另一个屏会错位

**建议**：在 `QApplication` 创建前加

```python
QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
```

并把 `PANEL_W/H`、槽位尺寸改成按 `screen().devicePixelRatio()` 缩放。

### 10. 剧本和角色数据严重不足 ⬜ 数据已补齐，剧本仍只有 1 个

**原状**：`configs/routines/` 只有 **1 个剧本**（爱琳莫轮椅轴）。
`tools/configs/db/characters/` 里的角色数据 `stats_90` / `skills_lv10` /
`resonance_chains` **全是空的**——`wiki_spider.py` 的选择器已失效。

**v1.7 已做**：爬虫重写，抓到 **65 个角色**，武器类型与元素零缺失，
`Character_Occupation.txt` 从 8 条补到 44 条。产出在
`tools/factory/db/characters.json`。

**仍缺**：剧本还是 1 个。这是内容问题，不是代码问题——
加角色只需要 `python tools/scaffold.py --create <角色>` + 放图 + 写黑话。

**下一步最有价值的**：详情页里有"最多 3 段""按住普攻"这类技能描述，
可以解析出来自动生成 `durations_ms` 初值，省掉手工标定的痛苦。

另一个中期的：做「轴分享」——现在全靠手动放文件进 `configs/routines/`，
可以加导入/导出单文件。

### 11. 零散但该记一笔的

| 项 | 位置 | 说明 |
|---|---|---|
| 热键冲突无检测 | `ui/settings_window.py` | `start_trigger` 和 `basic` 若选成同一颗键，行为会互相干扰，保存时不校验 |
| `build.bat` 版本号写死 v1.0 | `build.bat` | ✅ v1.6 已改 `set VERSION=`，单点修改 |
| 没有音效 | — | 纯视觉提示，打起来眼睛很忙，加个极轻的"叮"能省很多余光 |
| `lock` 键空转 | `utils/input_listener.py` | 映射有、信号发、Director 不处理 |

---

## 如果只能做三件事

按投入产出比排序：

1. ~~**剧本校验器**~~ ✅ **v1.5 已完成**（`tools/routine_lint.py`）
2. **编辑器接上诊断与 `render`** —— 一条硬编码路径的修改，就能同时解决
   "看不到解析错误"和"保存吞字段"两个 P0
3. **手感 Tab**（`ui/settings_window.py` 加一页 + 一个"整体节奏"滑块）
   把必须手改 JSON 的 6 个参数变成能点的
4. ~~**把 `tests/` 和 `assets/ui/` 移出 `.gitignore`**~~ ✅ **v1.6 已完成**

## 明确不建议现在做的

| 项 | 原因 |
|---|---|
| 视觉识别闭环 | 成本高（常驻截图 + 推理）、对分辨率和滤镜敏感、UI 改版即失效。而且前面三个痛点已经证明**不需要看游戏状态**也能解决 |
| 读内存 / 注入 | ACE 内核反作弊，必封。没有任何投机空间 |
| 按角色建类继承 | 差异主要在**数据**不在**规则**，继承会得到一堆只改数字的空子类。用 `character_durations` 填表即可（已实装） |
| 拆 `Director` | 现在拆是纯风险无收益，等下一个新功能进来一起动 |
