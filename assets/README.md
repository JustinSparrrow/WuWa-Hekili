# assets/ — 素材目录

存放悬浮窗要显示的所有图标。**按"这张图会随什么变化"来分类，不按角色分类。**

```
assets/
├── characters/                 角色与动作图标（游戏内画面裁出来的）
│   ├── _general/               通用库：所有角色共用同一张图的部分
│   │   ├── normal_attack/      再按武器类型分：sword / pistols / broadblade / ...
│   │   ├── jump/
│   │   ├── dodge/
│   │   ├── echo/
│   │   └── concerto_energy/
│   ├── Aemeath/                角色专属：只放这个角色长得不一样的图
│   │   ├── normal_attack/      normal.png / normal_2.png / normal_3.png
│   │   ├── resonance_skill/    skill.png / skill_2.png
│   │   ├── resonance_liberation/
│   │   ├── character/          变奏头像
│   │   ├── forte_circuit/      共鸣回路条
│   │   └── （其余标准子目录可留空）
│   ├── Lynae/
│   ├── ...
│   └── Character_Occupation.txt   角色 → 武器类型映射
├── input/                      按键提示小图（keyboard / xbox / ps）
├── video/                      裁图用的录像（**不进发布包**）
└── kenney_input-prompts_1.4.1/ 按键图标的原始素材包（**不进发布包**）
```

## 图标从哪来（重要）

**不要手工一帧一帧截图。** 有两条自动化路径：

```bash
# 首选：从解包资源镜像批量下载（65 个角色一次搞定，128×128 透明 PNG）
python tools/factory/icon_fetcher.py

# 备选：自己有录像时，用裁图工具按帧切
# （也可以从主菜单「素材工坊」直接打开，界面是同一套风格）
python tools/factory/asset_factory_gui.py
```

`icon_fetcher.py` 的源是 `static.nanoka.cc`（社区维护的鸣潮解包 UI 资源镜像），
目录结构与游戏内一致：`SkillIcon<拼音代号>/SP_Icon<拼音代号><后缀>.webp`。

实测各角色后缀集合不同，工具会自动探测：

| 后缀 | 对应 | 落到项目目录 |
|---|---|---|
| `A1..A6` | 技能栏图标 · 常态攻击各段 | `normal_attack/normal.png`、`normal_2.png`… |
| `Y` / `Y1` | 共鸣技能 | `resonance_skill/skill.png` |
| `C1..C2` | 共鸣解放 | `resonance_liberation/liberation.png` |
| `D1..D2` | 共鸣回路 | `forte_circuit/forte.png` |
| `QTE` | 变奏技能 | `character/intro.png` |
| `T` | 延奏技能 | `character/outro.png` |
| `B1..B6` | 技能演示图 | **只在角色没有 A 系列时**顶替 `normal_attack` |

> **`A` 和 `B` 是两种不同性质的图。**
> `A` 是技能栏图标——简洁的武器形/几何形，游戏里技能栏显示的就是它。
> `B` 是技能演示图——角色动作剪影，wiki 技能介绍里配的那种。
>
> 大部分角色有 A 系列，但**不是全部**：赞妮（Zanni）一个 A 都没有，只有 `B1..B5`。
> 所以工具的逻辑是「有 A 就用 A，没有 A 才拿 B 顶普攻」——
> 拿 B 顶出来的图观感和游戏技能栏不同，但确实是这个角色的招式，比空着强。
>
> 另外，"形态变化后的招式"（锁暝「念深状态」下普攻替换成"普攻·解伞形"）
> 也会占用 A/B 编号，当前判定逻辑按不到这么细，这些图混在同一个编号序列里。

**默认不覆盖已有文件。** 项目早期有 8 个角色是手工截图裁的（带游戏内元素光晕），
观感未必更差；而且 `forte_circuit/forte.png` 原本是能量条截图，语义和技能图标完全不同。
要换掉就显式加 `--overwrite`（先 `git commit`）。

想让它看起来更接近游戏？加 `--tint` 会按角色元素给白色蒙版着色
（热熔橘红 / 衍射金黄 / 导电紫 / 冷凝蓝 / 气动青 / 湮灭紫红）。

## 核心问题：通用好，还是每个角色一套？

**答案是"默认通用、按需专属"，判断标准只有一个：这张图会随角色变化吗？**

| 动作类型 | 放哪 | 为什么 |
|---|---|---|
| `normal_attack` / `heavy` | 角色专属，缺失时按**武器类型**落通用 | 挥剑和挥拳的图标不同，但同武器角色之间是一样的 |
| `resonance_skill` | **必须专属** | 图标就是角色自己的技能图标 |
| `resonance_liberation` | **必须专属** | 同上 |
| `character`（变奏头像） | **必须专属** | 是角色头像 |
| `forte_circuit`（回路条） | **必须专属** | 每个角色的机制不同 |
| `echo` | **通用** | 声骸取决于装备，与角色无关 |
| `jump` / `dodge` | **通用** | 全员一致 |
| `concerto_energy` / `energy_bar` | **通用** | 全员一致 |

按这个表，`_general/` 里有 `concerto_energy`、`jump`、`normal_attack/<武器>` 是**正确设计**，不是历史遗留。

> 以前它叫 `AAA_general`，前缀 AAA 只是为了让它在文件管理器里排到最前面。v1.6 改成了 `_general`——下划线同样排在最前，但不会再让人以为是"AAA 级素材"。

## 查找顺序（代码在 `utils/asset_manager.py`）

```
① 剧本写了 custom_icon          → 直接用指定的文件
② 角色专属目录                   normal_attack/normal_2.png
③ 同角色跨目录（重击没图时借普攻）  normal_attack/normal.png
④ 通用库                         _general/normal_attack/<武器>/
⑤ 角色目录兜底                   （处决/闪避不做这一级，宁可显示文字）
⑥ 都没有                         界面退化为文字
```

想知道某一步**实际命中了哪一级**，跑：

```bash
python tools/checks/routine_lint.py <剧本> --ignore-custom
```

它会打出 `exclusive:variant`（最理想）、`heavy_fallback`（借图）、`general`（掉通用）、
`loose:first`（随便拿了一张，可疑）这样的来源分级。

## 命名规范

| 动作 | 文件名 | 说明 |
|---|---|---|
| 普攻 1/2/3 段 | `normal.png` / `normal_2.png` / `normal_3.png` | 没有 1 后缀，从 2 开始才有数字 |
| 技能 1/2 段 | `skill.png` / `skill_2.png` | 同上 |
| 解放 | `liberation.png` / `liberation_2.png` | |
| 声骸 | `echo.png` | |
| 跳跃 / 闪避 | `jump.png` / `dodge.png` | |
| 变奏头像 | `avatar.png` | |
| 回路条 | `forte.png` / `forte_2.png` | |
| 协奏值 | `concerto.png` | |

数字后缀必须和剧本里的 `variant` 对得上。`a2` 应该配 `normal_2.png`——
如果配成 `normal_3.png`，体检会警告（`tools/checks/routine_lint.py`）。

## 加一个新角色

```bash
# 1. 铺好标准子目录（9 个）
python tools/scaffold.py --create 角色英文名

# 2. 拿图。首选自动下载：
python tools/factory/icon_fetcher.py --char 角色中文名
#    没有中文名映射时，也可以直接给代号：
#    （代号见 tools/factory/db/code_map.json）

# 3. 如果是普攻/重击要落到通用库，记得在 Character_Occupation.txt 加一行
#    角色英文名=武器类型     （sword / pistols / broadblade / gauntlets / rectifier）

# 4. 检查命中情况
python tools/checks/routine_lint.py --assets-only
```

## 现状（2026-10-25，接入 icon_fetcher 之后）

```
角色目录 45 个，其中 37 个有素材，合计 349 张 png（5.4 MB）
  手工截图（早期 8 个角色）：104 张，尺寸不统一（105~467px）、无 alpha
  游戏原图（icon_fetcher）：245 张，统一 128×128 + 透明

Character_Occupation.txt 登记 44 个（wiki 爬虫补齐），只剩 Aalto 未对中文名
```

想知道每个角色素材是手工还是原图，看 `tools/factory/db/characters/db_<角色>.json`
里的 `asset_source` 字段（`manual` / `nanoka` / `mixed` / `none`）。

补齐命令：

```bash
python tools/factory/icon_fetcher.py       # 下载缺失的技能图标
python tools/factory/build_db.py           # 重新生成角色档案（含素材清单）
python tools/checks/routine_lint.py --assets-only   # 看覆盖率
```

清理空目录（只删完全空的，有文件的一律不动）：

```bash
python tools/scaffold.py --prune --dry-run   # 先预演
python tools/scaffold.py --prune             # 确认后执行
```

## 不该进版本库 / 发布包的东西

| 目录 | 原因 |
|---|---|
| `video/` | 2.6G 录像，只是裁图原料 |
| `kenney_input-prompts_1.4.1/` | 17M 原始素材包，成品已在 `input/` 下 |

`build.bat` 现在只拷 `characters/` 和 `input/` 进发布包，
以前是整个 `assets/` 拷（会把 2.6G 视频打进去）。
