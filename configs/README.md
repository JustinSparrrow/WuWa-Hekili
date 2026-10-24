# configs/ — 剧本（连招轴）

```
configs/
└── routines/
    ├── 爱琳莫轮椅轴.json
    └── <你的轴>.json
```

**这个目录是纯数据，不是 Python 包**（之前的空 `__init__.py` 已删）。
程序通过两条路径读它：

| 用途 | 代码位置 |
|---|---|
| 选择列表（主菜单 → 选择流程） | `ui/routine_selector.py` |
| 保存编辑后的剧本 | `ui/routine_uploader.py` |
| 测试与压测 | `tests/`、`tools/checks/mem_bench.py` |

> 注意：**`config.json` 不在这里**。那是程序设置（按键映射、手感参数），在项目根目录。
> 两者的区别：`config.json` 是"你这台机器的偏好"，`configs/` 是"可以分享给别人的轴"。

## 一份剧本长什么样

```json
{
  "team_config":       { "1": "Aemeath", "2": "Lynae", "3": "Mornye" },
  "team_aliases":      { "1": "爱", "2": "琳", "3": "莫" },
  "original_opener":   "爱aaaa莫aaaz...",
  "original_loop":     "莫raaa...",
  "opener_script":     [ { "type": "basic", "desc": "普攻" }, ... ],
  "loop_script":       [ ... ],
  "initial_char_index": 1
}
```

| 字段 | 作用 | 能否手改 |
|---|---|---|
| `team_config` | 槽位号 → 角色英文名（**必须和 `assets/characters/` 下的目录同名**） | 可以 |
| `team_aliases` | 槽位号 → 黑话里用的代称（逗号分隔多个） | 可以 |
| `original_opener` / `original_loop` | 黑话原文，编辑器回显用 | 可以 |
| `opener_script` / `loop_script` | 解析后的动作数组，**程序真正执行的是这个** | 谨慎，改错会让程序跑偏 |
| `initial_char_index` | 开局在场角色（1/2/3） | 可以 |

## 动作字段

| 字段 | 说明 |
|---|---|
| `type` | `basic` / `heavy` / `skill` / `ult` / `echo` / `jump` / `dodge` / `execution` / `intro` |
| `desc` | 显示文字（会出现在悬浮窗角标旁边） |
| `variant` | 变体号，决定用哪张图（`"2"` → `normal_2.png`） |
| `next_char` | 仅 `intro` 用：切到第几号槽位 |
| `custom_icon` | 指定图标文件名，绕过自动查找 |
| `force_general` | 强制用通用库，不找角色专属 |
| `parallel` | 允许这一步在前一步蓄力时提前按（**只有琳奈那种角色特性才需要**） |
| `uncancellable` | 换键也打断不了（长动画大招），闸门会等它播完 |
| `duration_ms` | 单独指定这步的占位时长（覆盖全局配置） |
| `hold` | 要求长按（`+` 语法生成） |

## 怎么写

**推荐用编辑器**（主菜单 → 写轴），写黑话字符串即可：

```
爱aaaa莫aaazr2a2a2a2e2z2q琳e
```

语法速查见 [`core/script_parser.py`](../core/script_parser.py) 顶部文档，要点：

| 写法 | 含义 |
|---|---|
| `a e r q z f s j` / `跳 闪` | 普攻 技能 解放 声骸 重击 处决 闪避 跳跃 |
| `a2` | 二段普攻（数字 = 变体） |
| `e+` | 长按技能 |
| `z&q` | q 与前一步并行 |
| `r!` | 不可打断 |
| `a{620}` | 这步占位 620ms |
| `a*3` | 重复三次 |
| `// 注释` | 到行尾 |
| 角色名 / 代称 | 切人 |

**保存前建议先体检**：

```bash
python tools/checks/routine_lint.py configs/routines/你的轴.json
```

能查出"切到不存在的槽位""图标文件不存在""variant 和图标编号对不上"这类
**以前只会表现为界面错乱、不会有任何提示**的问题。

## 已知的坑

- 编辑器保存时是**重新解析黑话**生成动作数组，所以手写在 JSON 里的
  `parallel` / `uncancellable` / `duration_ms` 会被覆盖掉。
  用语法表达（`&` `!` `{}`）才不会丢。`custom_icon` 目前**没有语法能表达**，
  进编辑器改一遍就会丢，这一点还没解决。
- `team_config` 里的角色名必须是 `assets/characters/` 下真实存在的目录名，
  否则图标全部退化。体检会报「槽位 N 的角色 'Xxx' 在 assets/characters/ 下没有对应目录」。
