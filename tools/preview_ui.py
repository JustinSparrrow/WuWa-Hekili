"""
悬浮窗 UI 预览 / 截图工具（只用于看设计，不参与游戏逻辑）。

两种用法
-------
1) 截图（推荐先看这个）
       python tools/preview_ui.py --shot
   把悬浮窗叠在一帧真实游戏录像上，输出 docs/ui/state_*.png。
   用真实录像做背景是为了检验"战斗特效很亮时字还看不看得清"。

2) 桌面实时预览
       python tools/preview_ui.py --live
   直接把悬浮窗显示在桌面上，自动循环推进，右键退出。
   改完样式想立刻看效果时用它。

为什么不用真实 Director 跑数据
--------------------------
预览要的是"把某一帧摆成我想要的样子"（比如停在长按那一步看环形进度），
而 Director 是跟着真实按键推进的。这里按剧本顺序走一遍、照 _build_slot
的字段拼出槽位数据，既真实又可控，也不会动到核心逻辑。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# ---------------------------------------------------------------- 路径
# 独立运行：就地向上找到项目根（含 main.py）并加入 import 路径，再复用统一根查找。
_root = os.path.abspath(__file__)
while True:
    _root = os.path.dirname(_root)
    if os.path.exists(os.path.join(_root, "main.py")) or _root == os.path.dirname(_root):
        break
if _root not in sys.path:
    sys.path.insert(0, _root)

from utils.paths import project_root  # noqa: E402

ROOT = str(project_root())

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from ui import theme
from ui.overlay_window import (GEO_CUR, MARGIN, HekiliOverlay,
                               ParallelTrackWindow)
from utils.asset_manager import AssetManager

DEFAULT_ROUTINE = os.path.join(ROOT, "configs", "routines", "爱琳莫轮椅轴.json")
DOCS_UI = os.path.join(ROOT, "docs", "ui")
BACKDROP = os.path.join(DOCS_UI, "backdrop.jpg")


# ---------------------------------------------------------------- 数据

def _press_mode(action):
    """和 Director.resolve_press_mode 保持一致的近似（预览够用）。"""
    if action.get("hold") or action.get("type") == "heavy":
        return "hold"
    if action.get("type") == "basic":
        return "tap"
    return "any"


def walk_script(script, team):
    """
    按剧本顺序走一遍，记下每一步该显示哪个角色。

    切人那一步显示的是"切过去的角色"（和 Director.get_visual_data 一致），
    否则切人图标和头像会对不上。
    """
    out = []
    char_idx = 1
    for action in script:
        if action.get("type") == "intro" and action.get("next_char"):
            char_idx = action["next_char"]
        out.append((action, team.get(char_idx, "Unknown")))
    return out


def slot_for(action, char_name, mgr, current=False, parallel=False):
    """拼一个槽位字典，字段与 Director._build_slot 对齐。"""
    icon = mgr.get_icon_path(char_name, action["type"], action.get("variant"),
                             action.get("force_general", False),
                             action.get("custom_icon"))
    target = action.get("next_char") if action["type"] == "intro" else None
    btn = mgr.get_button_path(action["type"], target_index=target)
    mode = _press_mode(action)

    return {
        "desc": action.get("desc", ""),
        "icon_path": icon,
        "btn_path": btn,
        "char_avatar": mgr.get_icon_path(char_name, "intro"),
        "type": action["type"],
        "variant": action.get("variant"),
        "char_name": char_name,
        "press_mode": mode,
        "hold_threshold": 0.5 if mode == "hold" else 0.0,
        "parallel_hint": parallel,
        "is_current": current,
        "is_history": False,
    }


def build_state(flat, index, mgr, phase="opener", total=None):
    """
    取 flat[index] 作为"当前步"，拼出 [历史, 当前, 下一个, 未来]。

    :return: (slots, meta, parallel_slot)
    """
    total = total or len(flat)
    index = max(0, min(index, len(flat) - 1))

    def pick(i):
        if i < 0 or i >= len(flat):
            return None
        return flat[i]

    history = pick(index - 1)
    cur = pick(index)
    nxt = pick(index + 1)
    fut = pick(index + 2)
    par = pick(index + 2)

    # 当前步是长按、后面又有 parallel 步时，才给"下一个"打可并行标记
    parallel_hint = bool(cur and _press_mode(cur[0]) == "hold"
                         and nxt and nxt[0].get("parallel"))

    slots = [
        slot_for(*history, mgr, current=False) if history
        else {"desc": "START", "icon_path": None, "btn_path": None},
        slot_for(*cur, mgr, current=True) if cur else {},
        slot_for(*nxt, mgr, current=False, parallel=parallel_hint) if nxt else {},
        slot_for(*fut, mgr) if fut else {},
    ]
    meta = {"phase": phase, "index": index, "total": total}

    par_slot = None
    if cur and _press_mode(cur[0]) == "hold":
        for i in range(index + 1, min(index + 4, len(flat))):
            if flat[i][0].get("parallel"):
                par_slot = slot_for(*flat[i], mgr, parallel=True)
                break
    return slots, meta, par_slot


# ---------------------------------------------------------------- 渲染

def render_widget(widget: QWidget) -> QPixmap:
    """把一个控件（含子控件、含透明度效果）画到透明画布上。"""
    pm = QPixmap(widget.size())
    pm.fill(Qt.GlobalColor.transparent)
    widget.render(pm, QPoint(0, 0))
    return pm


def compose(backdrop: QPixmap, layers) -> QPixmap:
    """
    把悬浮窗叠到游戏画面上。

    :param layers: [(QPixmap, QPoint), ...]，按顺序叠加
    """
    canvas = QPixmap(1920, 1080)
    canvas.fill(Qt.GlobalColor.black)

    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.drawPixmap(QRect(0, 0, 1920, 1080), backdrop)
    for pm, pos in layers:
        p.drawPixmap(pos, pm)
    p.end()
    return canvas


def _load_backdrop() -> QPixmap:
    if os.path.exists(BACKDROP):
        return QPixmap(BACKDROP)
    pm = QPixmap(1920, 1080)
    pm.fill(QColor("#1a1420"))
    return pm


# ---------------------------------------------------------------- 截图模式

def shot_mode(routine_path, out_dir, theme_name="dark"):
    os.makedirs(out_dir, exist_ok=True)
    theme.apply(theme_name)
    prefix = "" if theme_name == "dark" else f"{theme_name}_"
    data = json.load(open(routine_path, "r", encoding="utf-8"))
    team = {int(k): v for k, v in data["team_config"].items()}
    mgr = AssetManager(os.path.join(ROOT, "assets", "characters"))
    flat = walk_script(data["opener_script"], team)

    app = QApplication.instance() or QApplication(sys.argv)
    overlay = HekiliOverlay()
    overlay.setWindowOpacity(0.0)       # 截图不需要窗口可见，只是别闪
    backdrop = _load_backdrop()

    put_x = (1920 - overlay.width()) // 2
    put_y = 812

    def snapshot(name, slots, meta, par_slot=None, active=True,
                 gate=0.0, reject=None):
        overlay.set_active(active)
        overlay.update_ui(slots, is_advance=False,
                          parallel_slot=par_slot, meta=meta)
        overlay.widgets[1].set_gate_progress(gate)

        # 格子是复用的，上一张图留下的闪红状态必须手动清掉，否则会串图
        for w in overlay.widgets:
            w._flash = ""
            w._fx = 0.0
            w._burst = 0.0

        if reject:
            overlay.widgets[1].flash_reject(reject)
            overlay.widgets[1]._fx = 1.0        # 抖到最大幅度，截图才看得见
        app.processEvents()

        layers = [(render_widget(overlay), QPoint(put_x, put_y))]

        if par_slot:
            par = ParallelTrackWindow()
            par.set_slot(par_slot)
            par_pm = render_widget(par)
            layers.append((par_pm, QPoint(put_x + MARGIN + GEO_CUR.x() - 26,
                                          put_y - par.height() + 8)))

        filename = f"{prefix}state_{name}.png"
        compose(backdrop, layers).save(os.path.join(out_dir, filename))
        print(f"  -> {filename}")

    print(f"渲染状态图（{theme_name}）：")

    # 1. 常规战斗态：停在"切人"那一步，能同时看到头像、技能、按键
    slots, meta, _ = build_state(flat, 23, mgr)
    snapshot("normal", slots, meta, gate=0.0)

    # 2. 蓄力 + 并行：声骸可以趁重击没放完先按
    slots, meta, par = build_state(flat, 25, mgr)
    snapshot("parallel", slots, meta, par_slot=par, gate=0.55)

    # 3. 按错反馈：该长按却轻点了
    slots, meta, _ = build_state(flat, 25, mgr)
    snapshot("reject", slots, meta, gate=0.0, reject="hold")

    # 4. 待命态：剧本已加载，等启动键
    slots, meta, _ = build_state(flat, 0, mgr)
    snapshot("idle", slots, meta, active=False)

    # 5. 循环轴中途：验证"循环轴 12/41"这种信息位
    loop = walk_script(data["loop_script"], team)
    slots, meta, par = build_state(loop, 6, mgr, phase="loop")
    snapshot("loop", slots, meta, par_slot=par, gate=0.25)

    print(f"\n输出目录: {out_dir}")


# ---------------------------------------------------------------- 实时预览

def live_mode(routine_path, theme_name="dark"):
    theme.apply(theme_name)
    data = json.load(open(routine_path, "r", encoding="utf-8"))
    team = {int(k): v for k, v in data["team_config"].items()}
    mgr = AssetManager(os.path.join(ROOT, "assets", "characters"))
    flat = walk_script(data["opener_script"], team)

    app = QApplication.instance() or QApplication(sys.argv)
    overlay = HekiliOverlay()
    overlay.set_active(True)
    overlay.show()

    state = {"i": 0}

    def step():
        i = state["i"] % len(flat)
        slots, meta, par = build_state(flat, i, mgr)
        overlay.update_ui(slots, is_advance=(state["i"] > 0),
                          parallel_slot=par, meta=meta)
        overlay.widgets[1].set_gate_progress(0.0)
        state["i"] += 1

    timer = QTimer()
    timer.setInterval(1100)
    timer.timeout.connect(step)
    timer.start()
    step()

    print("实时预览中：拖动窗口可移动，右键退出。")
    sys.exit(app.exec())


def main():
    parser = argparse.ArgumentParser(description="悬浮窗 UI 预览")
    parser.add_argument("--shot", action="store_true", help="渲染状态截图到 docs/ui")
    parser.add_argument("--live", action="store_true", help="在桌面上实时预览")
    parser.add_argument("--theme", default="dark", choices=["dark", "light"],
                        help="截图/预览用哪套主题")
    parser.add_argument("--routine", default=DEFAULT_ROUTINE)
    parser.add_argument("--out", default=DOCS_UI)
    args = parser.parse_args()

    if not os.path.exists(args.routine):
        print(f"找不到剧本: {args.routine}")
        return 1

    if args.shot:
        shot_mode(args.routine, args.out, args.theme)
    else:
        live_mode(args.routine, args.theme)
    return 0


if __name__ == "__main__":
    sys.exit(main())
