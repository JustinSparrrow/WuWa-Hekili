# WuWa_Hekili (鸣潮连招助手) 🎮
**WuWa_Hekili** 是一款受《魔兽世界》知名插件 Hekili 启发，专为《鸣潮》开发的战斗连招辅助工具。它通过在屏幕上叠加透明的“技能流”图标，帮助玩家肌肉记忆复杂的输出轴（Rotation），提升实战 DPS。

**⚠️ 安全声明：本工具仅通过手柄/键盘信号监听实现逻辑跳转，不读取、不修改游戏内存数据，属于“绿色辅助”。但请注意，任何外部覆盖层工具在反作弊系统下均存在理论上的误封风险，请玩家自行承担后果。**

## ✨ 核心特性
- Hekili 风格 UI：横向滚动的技能队列，左侧聚焦当前动作，右侧预告后续技能。
- 智能资源管理： 
  - 多级降级查找：优先查找角色专属动作图，无素材时自动降级使用通用武器图。 
  - 模糊匹配：支持 normal, enhanced, forte, heavy 等关键词自动匹配文件名。
- 生理级手感反馈： 
  - 重击长按判定：检测手柄按键时长，蓄力达到 0.5s（可配置）后自动跳转。 
  - 时效性：基于 QTimer 的心跳检查，确保长按反馈与游戏同步。
- 多轴支持：自动区分“启动轴 (Opener)”与“循环轴 (Loop)”，启动完成后无缝进入循环。 
- 深度手柄兼容： 
  - 支持 Xbox/PS 手柄及线性扳机（目前只适配了Xbox）。 
  - 动态切人提示：根据角色所在的 1/2/3 号槽位，动态显示手柄方向键提示。
- 高度定制化： 
  - 窗口可自由拖动，位置自动保存。 
  - 所有按键映射、角色武器映射、UI 不透明度均可通过 config.json 修改。

## 🎥 演示视频 (v1.0 Preview)
> **⚠️ 特别声明 / Disclaimer**
> 
> *   **轴来源 (Rotation Source)**：本演示视频中的输出轴逻辑参考自 Bilibili UP主 **[Hagoromogizune](https://www.bilibili.com/video/BV14erDB4E14/)**。感谢大佬的思路！
> *   **开发阶段 (Dev Stage)**：当前展示的仅为 **Version 1** 版本，核心目的是验证逻辑跑通。
>     *   目前尚未实装“预输入（合轴）”检测和精细的“输入间隔”控制，因此实际上手表现很鸡肋。
> *   **关于操作 (Gameplay)**：视频仅用于展示程序功能，操作过程中为了配合脚本判定可能略显僵硬/迟钝，**绝不代表作者真实游戏水平QAQ！**

[![演示视频_v1](docs/demo/demo_pic.png)](https://github.com/JustinSparrrow/WuWa-Hekili/issues/1#issue-4007743699)

## 🛠️ 安装与运行
本项目基于 Python 编写，在运行前需要配置相关的运行环境并安装必要的依赖库。请确保你的操作系统为 **Windows 10 或 11**。

### 第一步：安装 Python 环境
1. 请前往 [Python 官网](https://www.python.org/downloads/) 下载并安装 **Python 3.8 或更高版本**（推荐 Python 3.10+）。
2. **⚠️ 极其重要**：在安装过程中，务必勾选 **"Add Python to PATH"** 选项。

### 第二步：克隆/下载项目
你可以使用 Git 克隆本项目，或者直接下载 ZIP 压缩包：
```bash
# 使用 Git 克隆
git clone https://github.com/JustinSparrrow/WuWa_Hekili.git
```

下载后，进入项目根目录。

### 安装依赖库
由于本项目涉及底层硬件监听、图像处理和 GUI 渲染，需要安装几个核心的第三方库。
在项目根目录（WuWa_Hekili 文件夹下），在地址栏输入 cmd 并回车打开命令行，运行以下命令：
```bash
# 推荐使用 requirements.txt 一键安装
pip install -r requirement.txt
```

主要依赖说明：
- PySide6：用于渲染 Hekili 风格的透明悬浮窗口。
- pygame：用于读取 XInput / DirectInput 手柄信号。
- keyboard & mouse / ctypes：用于监听键盘与鼠标底层的硬件级输入。
- opencv-python (cv2)：用于辅助工具中的图像处理。

### 第四步：权限与启动 (极其重要)
由于《鸣潮》客户端（及其反作弊系统 ACE）通常以高权限运行，为了保证 keyboard 等底层钩子在游戏处于前台时仍能正常监听按键：
1. 必须以【管理员身份】运行！ 
   - 如果你使用命令行启动：请右键点击“开始”菜单，选择 “终端(管理员)” 或 “命令提示符(管理员)”，然后 cd 到项目目录。 
   - 如果你使用 PyCharm / VS Code 等编辑器：请完全关闭编辑器，然后右键点击其快捷方式，选择“以管理员身份运行”。
2. 启动程序：
   - 在管理员权限的环境下，运行：`python main.py`

### 第五步：游戏内设置建议
显示模式：请务必在《鸣潮》游戏设置中将图像显示模式改为 “无边框窗口 (Borderless Windowed)” 或 “窗口化”。如果使用独占全屏，Windows 将无法在游戏画面上方渲染本工具的悬浮窗。


## 📝 如何编写剧本 (Rotation)

## 📸 素材收集技巧

## 🤝 贡献与感谢
- UI 参考：World of Warcraft - Hekili Addon
- 素材来源：Xelu Controller Prompts / 游戏内截图

## 🚀 目前成果
1. 可视化素材抠图工具完成
2. 有预先输入的轴可以正常演示
3. hekili面板可以正常运行

## 🧠 下一步
cv
