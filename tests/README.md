# tests/ — 回归测试

```
tests/
├── test_script_parser.py    42 项  剧本解析 + 剧本体检
├── test_director_press.py   40 项  状态机：手势判定 / 时间轴 / 预输入 / 并行
└── test_managers.py          7 项  资源查找 / 配置管理
```

没有 pytest 依赖，纯 `unittest`，直接跑文件即可：

```bash
python tests/test_script_parser.py
python tests/test_director_press.py
python tests/test_managers.py

# 只想看结论
python tests/test_director_press.py 2>&1 | tail -3
```

环境：`F:\anaconda\envs\wuwahekili\python.exe`（PySide6 6.10.1）。
涉及 Qt 的测试会自己设 `QT_QPA_PLATFORM=offscreen`，不会弹窗。

## 各套测什么

### `test_script_parser.py`

| 分组 | 内容 |
|---|---|
| 旧语法兼容 | 12 项，保证现有剧本一个字不用改 |
| 新语法 | 8 项：注释 / 重复 / 并行 / 不可打断 / 自定义时长 |
| 诊断 | 7 项：未知字符带行列、报错不中断、起手角色不误报 |
| 往返 | 3 项：解析 → 还原字符串 → 再解析，字段必须一致 |
| 真实剧本 | 2 项：用仓库里的轴做回归，防止改解析器把轴改坏 |
| 体检 | 10 项：缺字段 / 槽位越界 / 图标不存在 / 时长非法 |

### `test_director_press.py`

手势（轻按/长按）、闸门开合、预输入兑现与过期、连按合并、
并行插入与关闭、回退、跨轴预览、角色级时长覆盖、整份轴自动演奏。

### `test_managers.py`

图标三级降级、缓存命中、配置读写与去重写盘。

## 加测试的时机

改这几处**必须**补/跑测试：

| 改动位置 | 对应测试 |
|---|---|
| `core/director.py` 判定逻辑 | `test_director_press.py` |
| `core/script_parser.py` 语法 | `test_script_parser.py` |
| `utils/asset_manager.py` 查找顺序 | `test_managers.py`、`test_script_parser.py` 的体检分组 |
| `tools/checks/routine_lint.py` 检查项 | `test_script_parser.py` 的体检分组 |

## 已知问题

**`tests/` 目前被 `.gitignore` 排除**，所以这些测试不会进版本库。
后果是别人 clone 下来没有任何回归保护，改了 `director.py` 只能靠手感验证。

建议把 `.gitignore` 里的 `tests` 那行删掉。目前的取巧办法是本地保留，
但它们随时可能因为一次清理丢失。
