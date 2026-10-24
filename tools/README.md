# tools/ — 辅助工具

按**用途**分三个位置，不按文件类型。这些脚本都是独立运行的，不参与主程序。

```
tools/
├── scaffold.py          目录脚手架（铺/清素材目录）
├── factory/             素材生产：把游戏画面变成可用的 png
│   ├── asset_factory_gui.py
│   ├── factory_config.json
│   ├── wiki_spider.py
│   └── db/characters/   爬下来的角色数据（半成品，基本都是空壳）
└── checks/              检查与观测：找出问题、量化性能
    ├── routine_lint.py
    ├── mem_probe.py
    ├── mem_bench.py
    └── check_input_ids.py
```

## factory/ — 素材生产

### `asset_factory_gui.py` — 素材工厂

从录像批量裁图。打开视频 → 框选 8 个固定区域 → 暂停在关键帧按 `1`~`8` 键，
自动裁切并按序号命名入库（`normal.png` / `normal_2.png` / ...）。

```bash
python tools/factory/asset_factory_gui.py
```

配置存在同目录的 `factory_config.json`（上次打开的视频路径、框选区域）。

### `wiki_spider.py` — 角色数据爬虫（**已可用**）

从库街区 wiki 抓全部角色，产出项目需要的元数据。

```bash
python tools/factory/wiki_spider.py                # 抓全部（已抓过的跳过）
python tools/factory/wiki_spider.py --limit 5      # 先试水
python tools/factory/wiki_spider.py --force        # 全部重抓
python tools/factory/wiki_spider.py --headful      # 显示浏览器（排查用）
python tools/factory/wiki_spider.py --occupation   # 顺带生成 Character_Occupation.txt
python tools/factory/wiki_spider.py --name-map     # 只重建中英文名对照表
```

产出：

| 文件 | 内容 |
|---|---|
| `db/characters.json` | 65 个角色的中文名 / 武器 / 元素 / 稀有度 / 出生地 / item_id |
| `db/name_map.json` | 中文 → 英文名对照（素材目录用英文名，缺的需人工补） |
| `assets/characters/Character_Occupation.txt` | 角色 → 武器类型（**与原有条目合并，不会覆盖丢失**） |

**抓什么、不抓什么**：只抓项目用得上的——武器类型（决定普攻/重击落哪个通用库）、
元素、稀有度、中英文名。游戏数值（90 级属性、技能倍率、共鸣链）对"下一步按哪个键"
没有帮助，默认不抓。

站点是 React SPA，必须用 Playwright 渲染。选择器依赖当前页面结构
（`.role-tags .text-ellipsis`、`[class*='card-star-N']`），
**wiki 改版后要重新核对**，否则会静默抓空。

`name_map.json` 里留空的条目是有意的：英文名不确定就留空，
`--occupation` 会在文件末尾把这些角色列出来。猜错会让剧本选到错的素材目录，
比留空更难查。

### `icon_fetcher.py` — 技能图标批量下载（**解决"没图"**）

**不要手工一帧一帧截图。** 这个从解包资源镜像批量取游戏原生图标。

```bash
python tools/factory/icon_fetcher.py --list         # 先看计划
python tools/factory/icon_fetcher.py --limit 3      # 试水
python tools/factory/icon_fetcher.py                # 全量（约 2 分钟）
python tools/factory/icon_fetcher.py --char 爱弥斯   # 单个角色
python tools/factory/icon_fetcher.py --tint         # 按元素着色
python tools/factory/icon_fetcher.py --overwrite    # 覆盖已有文件（默认跳过）
```

来源是 `static.nanoka.cc`（社区维护的鸣潮解包 UI 资源镜像），
路径规律 `SkillIcon<拼音代号>/SP_Icon<拼音代号><后缀>.webp`，128×128 带 alpha。

**后缀和项目目录的对应**（实测 6 个角色交叉验证）：

| 后缀 | 落到 |
|---|---|
| `A1..A6` | `normal_attack/normal.png`、`normal_2.png`… |
| `Y` / `Y1` | `resonance_skill/skill.png` |
| `C1..C2` | `resonance_liberation/liberation.png` |
| `D1..D2` | `forte_circuit/forte.png` |
| `QTE` | `character/intro.png` |
| `T` | `character/outro.png` |
| `B1..B6` | 角色没有 A 系列时，顶替 `normal_attack` |

`A` 是技能栏图标（几何/武器形），`B` 是技能演示图（角色动作剪影）。
大部分角色有 A，但赞妮这类一个 A 都没有，只能用 B 兜底。

具体哪个角色有哪些后缀不固定（忌炎 10 张、爱弥斯 17 张），工具会逐个探测。

### `build_db.py` — 拆角色档案

把 `characters.json` 拆成每个角色一份 `db/characters/db_<中文名>.json`：
基础资料 + **实际扫到的素材清单** + `asset_source`（`nanoka` / `manual` / `mixed` / `none`）。

```bash
python tools/factory/build_db.py --char 爱弥斯
```

比起一个大 json，拆开的好处是改一个角色只 diff 几十行，也不会把手工补的
`note` / `basic_mechanism` 冲掉（脚本会保留旧文件里的非空字段）。

## checks/ — 检查与观测

### `routine_lint.py` — 剧本体检（**最常用**）

```bash
python tools/checks/routine_lint.py configs/routines/爱琳莫轮椅轴.json
python tools/checks/routine_lint.py --all                # 全部剧本
python tools/checks/routine_lint.py <剧本> --ignore-custom   # 查自动降级路径
python tools/checks/routine_lint.py --assets-only        # 素材覆盖率
```

检查：必需字段、动作类型白名单、`next_char` 越界、角色目录是否存在、
`custom_icon` 文件是否存在、`variant` 与图标编号冲突、`duration_ms` 合理性、
素材来源分级（专属/借图/通用/兜底/缺失）、武器映射覆盖率。

退出码 0 = 无 error，1 = 有 error，可以直接接 git hook 或打包脚本。
主程序加载剧本前也会自动跑一遍（`main._preflight`），只拦 error。

### `mem_probe.py` — 外部进程内存采样

```bash
python tools/checks/mem_probe.py --list --name python
python tools/checks/mem_probe.py --pid 12345 --seconds 120
python tools/checks/mem_probe.py --pid 12345 --until-exit --csv out.csv
```

采 `PrivateUsage`（真实占用，判断泄漏只看它）、工作集、句柄数、线程数，
用最小二乘算斜率给出"稳定 / 轻微增长 / 疑似泄漏"的结论。

### `mem_bench.py` — 内部压测

```bash
python tools/checks/mem_bench.py --rounds 8000
```

离屏跑 N 次连招推进，分段采样私有内存，对比 Qt 控件数 / 动画对象数 / Python 堆。
**分段增量越来越小 = 缓存填满后收敛（正常）；每段等量增长 = 线性泄漏。**

### `check_input_ids.py` — 按键图标 id 校验

核对 `config.json` 里 `keymaps` 引用的图标文件是否都在 `assets/ui/<device>/` 下存在。

## scaffold.py — 素材目录脚手架

```bash
python tools/scaffold.py --list                # 现状：谁有素材、谁空壳
python tools/scaffold.py --create Aemeath      # 给某角色铺 9 个标准子目录
python tools/scaffold.py --create-all          # 全部铺一遍
python tools/scaffold.py --prune --dry-run     # 预演清理空目录
python tools/scaffold.py --prune               # 清理（只删完全空的）
```

## 约定

- 工具脚本**不 import 主程序的 UI**，最多依赖 `core/` 和 `utils/`。
  这样可以在没有窗口的环境（CI、纯命令行）里跑。
- 需要项目根目录时**向上找 `main.py`**，不要按 `dirname` 次数写死——
  这些脚本被移动过位置（`tools/` → `tools/checks/`），按层级算会静默算错。
- 新增工具请放进 `factory/` 或 `checks/`，不要堆在 `tools/` 根下。
