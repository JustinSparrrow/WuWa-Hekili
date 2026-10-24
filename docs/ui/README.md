# docs/ui — 界面设计参照物

这个目录只放**看设计用的图**，不参与程序运行。

## 文件

| 文件 | 内容 |
|---|---|
| `backdrop.jpg` | 一帧真实游戏录像（`assets/video/爱琳莫.mp4` 抽帧，1920×1080）。截图时的背景板 |
| `state_normal.png` | 悬浮窗 · 常规战斗态（切人那一步） |
| `state_parallel.png` | 悬浮窗 · 蓄力 + 并行轨（声骸可以趁重击没放完先按） |
| `state_reject.png` | 悬浮窗 · 按错反馈（该长按却轻点了） |
| `state_idle.png` | 悬浮窗 · 待命态（剧本已加载，等启动键） |
| `state_loop.png` | 悬浮窗 · 循环轴中途 |
| `win_menu.png` | 启动器 |
| `win_settings.png` | 按键设置 |
| `win_selector.png` | 流程选择 |
| `win_editor.png` | 流程编辑器（第一页） |
| `light_*.png` | 上面九张的**日间主题**版本（同名，前缀 `light_`） |

## 怎么重新生成

```bash
# 悬浮窗五张状态图（叠在真实录像上）——夜间
python tools/preview_ui.py --shot

# 日间主题（输出 light_state_*.png）
python tools/preview_ui.py --shot --theme light

# 单个管理窗口
python tools/preview_ui.py --live          # 桌面实时预览悬浮窗，右键退出
```

管理窗口的截图没有专门的工具，都是"构造窗口 → `QWidget.render()` → 贴到
深色背景上"三步，需要时临时写几行即可。

## 为什么要叠在真实录像上截图

纯色背景看不出真实问题。鸣潮的战斗特效亮度很高（尤其湮灭/衍射），
玻璃面板透明度定在 0.90 还是 0.96，字压不压得住，只有叠在实拍画面上才看得出来。
`backdrop.jpg` 是刻意挑的一帧高亮紫粉场面。

## 注意

- 这些图**不能**直接当素材用（是整屏截图，不是切好的图标）
- `backdrop.jpg` 来自作者自己的录像，体积 640KB，只作参照，可随时删
