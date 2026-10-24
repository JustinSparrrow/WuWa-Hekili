"""
UI 设计系统：颜色、字体、形状、绘制工具。

设计取向
--------
**Apple 的克制** —— 大圆角（连续曲率）、大量留白、无边框按钮、
柔和的多层阴影、克制的动效。

**鸣潮的质感** —— 墨黑玻璃底、香槟金细线、元素色点缀、菱形装饰分隔。

双主题
------
    夜间（默认）  墨黑玻璃 + 香槟金   —— 打游戏时用，压得住战斗特效
    日间          冷灰蓝白玻璃 + 钢蓝 —— 白色系，录制/办公时更清爽

切换：`theme.apply("light")` / `theme.apply("dark")`。
切换后通过 `theme.bus.changed` 广播，窗口收到信号后重建自己的缓存底图
（玻璃面板是缓存成 QPixmap 的，不重建就会留着旧配色）。

**所有颜色都必须走模块属性**（`theme.GOLD`），不要 `from ui.theme import GOLD`——
后者在 import 那一刻把值拷走了，切主题时不会跟着变。

为什么不用 QSS
--------------
QSS 能表达的只有方块 + 圆角 + 描边 + 线性渐变，做不出：
    · 连续曲率圆角（superellipse，苹果那种"更圆润的圆角"）
    · 多层柔和外阴影、内发光高光
    · 环形进度、渐变描边、遮罩裁切
悬浮窗是玩家全程盯着看的东西，值得直接用 QPainter 画。

性能约定
--------
所有开销大的东西（外阴影、噪点底纹、玻璃面板）都要**缓存成 QPixmap**，
只在尺寸或主题变化时重建；每帧只做一次 drawPixmap 贴图。
"""

from __future__ import annotations

import random

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QFontMetricsF,
                           QImage, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap, QRadialGradient)

# ============================================================ 调色板
# 角色名 -> 颜色。两套主题键名完全一致，apply() 时整体刷进模块全局。
#
# 命名说明：GOLD / IVORY 是夜间主题的历史叫法（香槟金 / 象牙白），
# 在日间主题里分别代表"强调色 / 主文字色"，语义不变，所以名字没改。

DARK = {
    "shadow": "#000000",
    "shadow_alpha": 120,

    "GLASS_TOP": "#1B2029",
    "GLASS_MID": "#11151C",
    "GLASS_BOT": "#0A0D13",
    "a_top": 0.96, "a_mid": 0.97, "a_bot": 0.985,

    "GOLD": "#E8C88C",          # 主强调色
    "GOLD_HI": "#F8E9C4",       # 高光
    "GOLD_DEEP": "#9C7434",     # 暗部（金属渐变收口）
    "IVORY": "#F6F2E9",         # 主文字

    "TEXT_DIM": "#B9B2A4",
    "TEXT_FAINT": "#8A8578",

    "CYAN": "#5FD8E8",          # 并行提示
    "ALERT": "#FF5F57",         # 按错反馈
    "GREEN": "#4ADE80",         # 激活
    "AMBER": "#FFB86B",         # 重击 / 长按

    "TILE_PLATE": "#0B0E14",    # 技能格底（图标下面那层）
    "KEYCAP_BG": "#05070A",     # 按键帽底
    "KEYCAP_EDGE": "#FFFFFF",   # 按键帽描边
    "BADGE_BG": "#05070A",      # 角标底
    "TEXT_ON_ACCENT": "#241A08",  # 主按钮上的字

    "CARD_BG": "#FFFFFF",       # 分组卡片（很淡的一层）
    "CARD_BORDER": "#FFFFFF",
    "DIVIDER": "#FFFFFF",

    "INPUT_BG": "#000000",
    "POPUP_BG": "#14181F",
    "SELECT_BG": "#E8C88C",

    "edge_hi_alpha": 0.20,      # 玻璃内描边顶部亮度
    "noise_rgb": 255,           # 噪点用白点
    "noise_alpha": 0.55,
    "vignette_alpha": 70,       # 底部内侧压暗
    "glyph_bg": "#0B0E14",      # 头像占位圆底
}

LIGHT = {
    "shadow": "#2A3B52",
    "shadow_alpha": 62,

    "GLASS_TOP": "#FFFFFF",
    "GLASS_MID": "#F7F9FC",
    "GLASS_BOT": "#E7EDF4",
    "a_top": 0.975, "a_mid": 0.98, "a_bot": 0.985,

    "GOLD": "#3E6FA3",          # 日间用钢蓝当强调色（金在白底上太弱）
    "GOLD_HI": "#6E9CCB",
    "GOLD_DEEP": "#2A4F77",
    "IVORY": "#1C2530",         # 主文字：冷调近黑

    "TEXT_DIM": "#5B6B7C",
    "TEXT_FAINT": "#8B99A8",

    "CYAN": "#2C8FA6",
    "ALERT": "#D9483F",
    "GREEN": "#2E9E5B",
    "AMBER": "#C2761F",

    "TILE_PLATE": "#FFFFFF",
    "KEYCAP_BG": "#2A3442",     # 日间也是深色键帽 —— 按键图本身是白色字形
    "KEYCAP_EDGE": "#FFFFFF",
    "BADGE_BG": "#FFFFFF",
    "TEXT_ON_ACCENT": "#FFFFFF",

    "CARD_BG": "#0F1A26",
    "CARD_BORDER": "#0F1A26",
    "DIVIDER": "#0F1A26",

    "INPUT_BG": "#FFFFFF",
    "POPUP_BG": "#FFFFFF",
    "SELECT_BG": "#3E6FA3",

    "edge_hi_alpha": 0.60,
    "noise_rgb": 40,
    "noise_alpha": 0.30,
    "vignette_alpha": 26,
    "glyph_bg": "#E6EBF2",
}

PALETTES = {"dark": DARK, "light": LIGHT}

# 模块级颜色变量（默认夜间）。apply() 把选中的调色板刷进来。
MODE = "dark"
for _k, _v in DARK.items():
    globals()[_k] = _v

# 鸣潮六元素：夜间用浅色（压在墨黑上亮），日间用深色（压在白上才有对比）
ELEMENTS = {
    "glacio": {"cn": "冷凝", "dark": "#7CD4F5", "light": "#1F7FA8"},
    "fusion": {"cn": "热熔", "dark": "#FF7A4D", "light": "#C4501F"},
    "electro": {"cn": "导电", "dark": "#B487FF", "light": "#6B45B8"},
    "aero": {"cn": "气动", "dark": "#5FE0B8", "light": "#1B8A6C"},
    "spectro": {"cn": "衍射", "dark": "#FFD36E", "light": "#A87A12"},
    "havoc": {"cn": "湮灭", "dark": "#D0528F", "light": "#A32F66"},
}

_generation = 0


class _ThemeBus(QObject):
    """主题变更广播。窗口连上它就能自动重建缓存。"""
    changed = Signal()


bus = _ThemeBus()


def generation() -> int:
    """主题代数。窗口用它判断自己的缓存底图是否过期。"""
    return _generation


def current() -> str:
    return MODE


def is_dark() -> bool:
    return MODE == "dark"


def apply(mode: str) -> bool:
    """
    切换主题并广播。

    :param mode: "dark" / "light"；其它值（含旧配置里的 "default"）一律按夜间处理
    :return: True 表示确实切换了
    """
    global MODE, _generation

    mode = "light" if str(mode).lower() == "light" else "dark"
    if mode == MODE:
        return False

    MODE = mode
    for key, value in PALETTES[mode].items():
        globals()[key] = value
    _generation += 1

    bus.changed.emit()
    return True


# ============================================================ 取色工具

def rgba(hex_color: str, alpha: float) -> QColor:
    """'#RRGGBB' + 0~1 透明度 -> QColor（项目里最常用的取色方式）。"""
    c = QColor(hex_color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def with_alpha(color, alpha: float) -> QColor:
    """给任意颜色（QColor 或 '#RRGGBB'）换一个透明度。"""
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def qa(hex_color: str, alpha: float) -> str:
    """给 QSS 用的 rgba() 字符串。"""
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{int(max(0.0, min(1.0, alpha)) * 255)})"


def element_color(element: str | None, fallback: str | None = None) -> QColor:
    """元素英文名 -> 元素色；未知元素退回强调色。"""
    info = ELEMENTS.get((element or "").lower())
    if info:
        return QColor(info["light" if MODE == "light" else "dark"])
    return QColor(fallback or GOLD)


def element_cn(element: str | None) -> str:
    info = ELEMENTS.get((element or "").lower())
    return info["cn"] if info else ""


# ============================================================ 字体

_FAMILIES: list[str] | None = None


def _families() -> list[str]:
    """
    挑一套"像苹果"的字体栈。

    Segoe UI Variable 是 Win11 的视觉字体（字重跨度大、字形干净），
    没有就退 Segoe UI；中文统一用微软雅黑 UI。
    Qt 会按列表顺序做逐字回退，中英混排不会变成方块。
    """
    global _FAMILIES
    if _FAMILIES is None:
        try:
            available = set(QFontDatabase.families())
        except Exception:
            available = set()
        wanted = ["Segoe UI Variable Display", "Segoe UI Variable Text",
                  "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei",
                  "PingFang SC", "Noto Sans SC"]
        picked = [f for f in wanted if f in available]
        _FAMILIES = picked or ["Microsoft YaHei"]
    return _FAMILIES


def font(size: float, weight: int = 400, spacing: float = 0.0) -> QFont:
    """
    统一取字体。

    :param size:    像素字号（Qt 会按系统缩放自动换算成逻辑像素）
    :param weight:  400 常规 / 500 中等 / 600 半粗 / 700 粗
    :param spacing: 字距（小号全大写标签加一点字距会显得更"高级"）
    """
    f = QFont()
    f.setFamilies(_families())
    f.setPixelSize(max(1, int(round(size))))
    if weight >= 700:
        f.setWeight(QFont.Weight.Bold)
    elif weight >= 600:
        f.setWeight(QFont.Weight.DemiBold)
    elif weight >= 500:
        f.setWeight(QFont.Weight.Medium)
    else:
        f.setWeight(QFont.Weight.Normal)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def elide(text: str, f: QFont, width: float) -> str:
    """按像素宽度省略（中文没有空格，只能靠 QFontMetrics 算）。"""
    if not text:
        return ""
    fm = QFontMetricsF(f)
    if fm.horizontalAdvance(text) <= width:
        return text
    return fm.elidedText(text, Qt.TextElideMode.ElideRight, width)


# ============================================================ 形状

# 圆角控制点系数：0.5523 = 正圆角，调到 0.50 会让转角"更饱满"，
# 接近苹果图标那种连续曲率（superellipse）的手感。
_CORNER_T = 0.50


def squircle(rect: QRectF | QRect, radius: float) -> QPainterPath:
    """
    连续曲率圆角矩形。

    直角三角形的圆弧用三次贝塞尔逼近：控制点越靠近角点，转角越饱满。
    这就是"苹果圆角"和"QSS border-radius"肉眼可见的差别。
    """
    r = QRectF(rect)
    rad = min(radius, r.width() / 2, r.height() / 2)
    if rad <= 0.5:
        path = QPainterPath()
        path.addRect(r)
        return path

    t = rad * _CORNER_T
    x, y, w, h = r.x(), r.y(), r.width(), r.height()

    path = QPainterPath()
    path.moveTo(x + rad, y)
    path.lineTo(x + w - rad, y)
    path.cubicTo(x + w - rad + t, y, x + w, y + rad - t, x + w, y + rad)
    path.lineTo(x + w, y + h - rad)
    path.cubicTo(x + w, y + h - rad + t, x + w - rad + t, y + h, x + w - rad, y + h)
    path.lineTo(x + rad, y + h)
    path.cubicTo(x + rad - t, y + h, x, y + h - rad + t, x, y + h - rad)
    path.lineTo(x, y + rad)
    path.cubicTo(x, y + rad - t, x + rad - t, y, x + rad, y)
    path.closeSubpath()
    return path


# ============================================================ 绘制工具

def draw_shadow(painter: QPainter, rect: QRectF | QRect, radius: float,
                spread: int = 14, alpha: int = -1,
                color: QColor | None = None) -> None:
    """
    柔和外阴影：一圈圈逐渐外扩、逐渐变淡的描边。

    比 QGraphicsDropShadowEffect 便宜得多（后者每帧都要做一次离屏模糊），
    而且不会被父控件裁掉。必须在画主体之前调用。
    """
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    base = QColor(color) if color is not None else QColor(globals().get("shadow", "#000000"))
    total = alpha if alpha >= 0 else int(globals().get("shadow_alpha", 120))
    steps = max(6, spread)
    for i in range(steps, 0, -1):
        fade = (1.0 - i / steps) ** 2.2
        a = int(total * fade)
        if a <= 0:
            continue
        pen = QPen(QColor(base.red(), base.green(), base.blue(), a))
        pen.setWidthF(1.4)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        grow = i * 0.85
        painter.drawPath(squircle(QRectF(rect).adjusted(-grow, -grow, grow, grow),
                                  radius + grow))
    painter.restore()


_NOISE_IMGS: dict = {}
_NOISE_SIZE = 64


def _noise_image(rgb: int) -> QImage:
    """
    噪点底纹。

    纯渐变的玻璃看起来是"塑料"，叠一层极淡的噪点才有磨砂质感。
    64x64 平铺，透明度只有 0~14，肉眼几乎看不见但整体会"活"过来。

    :param rgb: 255 = 白点（夜间），40 = 深点（日间，白底上才看得见）
    """
    img = _NOISE_IMGS.get(rgb)
    if img is not None:
        return img

    rnd = random.Random(20261025 + rgb)   # 固定种子，避免每次启动纹理都变
    buf = bytearray(_NOISE_SIZE * _NOISE_SIZE * 4)
    for i in range(0, len(buf), 4):
        v = max(0, min(255, rgb + rnd.randint(-12, 12)))
        buf[i] = v
        buf[i + 1] = v
        buf[i + 2] = v
        buf[i + 3] = rnd.randint(0, 14)
    img = QImage(bytes(buf), _NOISE_SIZE, _NOISE_SIZE, _NOISE_SIZE * 4,
                 QImage.Format.Format_ARGB32).copy()
    _NOISE_IMGS[rgb] = img
    return img


def draw_panel(painter: QPainter, rect: QRectF, radius: float = 34,
               opacity: float = 1.0, shadow_spread: int = 14,
               shimmer: bool = True) -> None:
    """
    画一块玻璃面板：外阴影 + 渐变底 + 噪点 + 顶部高光 + 内描边。

    :param opacity: 整体不透明度（待命状态会调低让它"退后"）
    :param shimmer: 是否画顶部那道很细的反光（小控件可以关掉省开销）
    """
    if opacity <= 0.01:
        return

    if shadow_spread > 0:
        draw_shadow(painter, rect, radius, shadow_spread, int(shadow_alpha * opacity))

    path = squircle(rect, radius)

    painter.save()
    painter.setClipPath(path)

    # 底：上亮下暗的渐变
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0.0, rgba(GLASS_TOP, a_top * opacity))
    grad.setColorAt(0.55, rgba(GLASS_MID, a_mid * opacity))
    grad.setColorAt(1.0, rgba(GLASS_BOT, a_bot * opacity))
    painter.fillPath(path, QBrush(grad))

    # 左上角一盏极淡的强调色光，让画面不呆板（夜间=金，日间=钢蓝）
    glow = QRadialGradient(QPointF(rect.left() + rect.height() * 0.55,
                                   rect.top() + rect.height() * 0.15),
                           rect.width() * 0.55)
    glow.setColorAt(0.0, rgba(GOLD, (0.10 if is_dark() else 0.09) * opacity))
    glow.setColorAt(1.0, rgba(GOLD, 0.0))
    painter.fillPath(path, QBrush(glow))

    # 底部内侧压暗：卡片"有厚度"的关键，也比纯渐变更耐看
    vign = QLinearGradient(rect.bottomLeft(), QPointF(rect.left(), rect.top()))
    vign.setColorAt(0.0, QColor(0, 0, 0, int(vignette_alpha * opacity)))
    vign.setColorAt(0.32, QColor(0, 0, 0, 0))
    painter.fillPath(path, QBrush(vign))

    # 磨砂噪点
    painter.setOpacity(noise_alpha * opacity)
    painter.fillPath(path, QBrush(_noise_image(noise_rgb)))
    painter.setOpacity(1.0)

    painter.restore()

    # 内描边：上缘一道亮、下缘几乎看不见 —— 玻璃厚度感就靠这 1px
    painter.save()
    pen = QPen()
    pen.setWidthF(1.0)
    pen.setBrush(QBrush(_edge_gradient(rect, opacity)))
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(squircle(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5))
    painter.restore()

    if shimmer:
        # 顶部反光条：只有中间最亮，两端淡出，像一块塑料边缘的高光
        painter.save()
        pen = QPen()
        pen.setWidthF(1.2)
        pen.setBrush(QBrush(_top_sheen(rect, opacity)))
        painter.setPen(pen)
        painter.drawLine(QPointF(rect.left() + radius * 0.9, rect.top() + 1.0),
                         QPointF(rect.right() - radius * 0.9, rect.top() + 1.0))
        painter.restore()


def _edge_gradient(rect: QRectF, opacity: float) -> QLinearGradient:
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    if is_dark():
        g.setColorAt(0.0, rgba("#FFFFFF", edge_hi_alpha * opacity))
        g.setColorAt(0.45, rgba(GOLD, 0.07 * opacity))
        g.setColorAt(1.0, rgba("#FFFFFF", 0.03 * opacity))
    else:
        # 白卡片在白底上要靠"边缘的灰蓝"才看得出轮廓
        g.setColorAt(0.0, rgba("#FFFFFF", 0.95 * opacity))
        g.setColorAt(0.45, rgba(GOLD, 0.18 * opacity))
        g.setColorAt(1.0, rgba("#8FA3BA", 0.45 * opacity))
    return g


def _top_sheen(rect: QRectF, opacity: float) -> QLinearGradient:
    g = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.right(), rect.top()))
    if is_dark():
        g.setColorAt(0.0, rgba("#FFFFFF", 0.0))
        g.setColorAt(0.28, rgba(GOLD_HI, 0.34 * opacity))
        g.setColorAt(0.62, rgba("#FFFFFF", 0.16 * opacity))
        g.setColorAt(1.0, rgba("#FFFFFF", 0.0))
    else:
        # 白底上"白高光"看不见，改成顶端一道很淡的钢蓝反光
        g.setColorAt(0.0, rgba("#FFFFFF", 0.0))
        g.setColorAt(0.28, rgba(GOLD_HI, 0.65 * opacity))
        g.setColorAt(0.62, rgba("#FFFFFF", 0.85 * opacity))
        g.setColorAt(1.0, rgba("#FFFFFF", 0.0))
    return g


def draw_gold_ring(painter: QPainter, rect: QRectF, radius: float,
                   width: float = 2.0, alpha: float = 1.0,
                   color: str | QColor | None = None,
                   progress: float | None = None,
                   glow: bool = False, metal: bool = False) -> None:
    """
    强调色描边 + 可选环形进度。

    :param progress: None = 画完整一圈；0~1 = 从正上方顺时针填充这么多
    :param glow:     是否在描边外侧加一圈柔光（当前格用）
    :param metal:    是否用金属渐变而不是单色（当前格用）
    """
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    ring = QColor(color) if color is not None else QColor(GOLD)
    path = squircle(rect, radius)
    in_progress = progress is not None and progress < 0.999

    # 柔光只跟着"亮着的那一段"走：满环时绕整圈，行进中只裹住进度弧。
    # 整圈都发光的话，进度到 30% 和 90% 看起来一样亮，指示就失效了。
    if glow and not in_progress:
        # 白底上柔光会被"吃掉"，日间要加浓才看得出光晕
        boost = 1.0 if is_dark() else 1.7
        for extra, a in ((3.4, 0.20 * boost), (1.8, 0.32 * boost)):
            pen = QPen(with_alpha(ring, a * alpha))
            pen.setWidthF(width + extra)
            painter.setPen(pen)
            painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)

    if not in_progress:
        # 满环 = 这一步随时可以按
        pen = QPen(with_alpha(ring, 0.92 * alpha))
        pen.setWidthF(width)
        if metal:
            # 金属渐变：左上高光、右下收暗，比单色描边更像"镶了一道金边"。
            # 明暗从 ring 自己推出来，而不是写死金色 —— 否则重击（琥珀）、
            # 并行（青）的描边会变成冷热混色的脏边。
            g = QLinearGradient(rect.topLeft(), rect.bottomRight())
            g.setColorAt(0.0, with_alpha(ring.lighter(135), 0.98 * alpha))
            g.setColorAt(0.42, with_alpha(ring, 0.95 * alpha))
            g.setColorAt(1.0, with_alpha(ring.darker(160), 0.88 * alpha))
            pen.setBrush(QBrush(g))
        painter.setPen(pen)
        painter.drawPath(path)
    else:
        # 未满：先画一圈很淡的底环，再在底环上盖一段亮弧。
        # 亮弧越长 = 这个动作越接近播完，玩家的眼睛不用盯数字。
        pen = QPen(with_alpha(ring, 0.10 * alpha))
        pen.setWidthF(width)
        painter.setPen(pen)
        painter.drawPath(path)

        if progress > 0.002:
            part = QPainterPath()
            # 从正上方（12 点钟）起笔顺时针走，读起来跟时钟一致。
            # squircle 的路径起点在左上圆角结束处，所以顶边中点的偏移量
            # 正好是 "半宽 - 圆角"，不是周长的一半（那是右下角）。
            start = max(0.0, rect.width() / 2.0 - radius)
            _append_path_range(path, start, path.length() * min(1.0, progress), part)

            if glow:
                pen = QPen(rgba(GOLD_HI, 0.22 * alpha))
                pen.setWidthF(width + 3.4)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawPath(part)
                pen = QPen(rgba(GOLD_HI, 0.38 * alpha))
                pen.setWidthF(width + 1.8)
                painter.setPen(pen)
                painter.drawPath(part)

            pen = QPen(rgba(GOLD_HI, 1.0 * alpha))
            pen.setWidthF(width + 0.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawPath(part)

    painter.restore()


def _append_path_range(path: QPainterPath, start: float, length: float,
                       out: QPainterPath) -> None:
    """
    取 path 上从 start 开始、长度 length 的一段，写进 out。

    Qt 没有直接提供"路径截取"，所以按 1/72 的精度采样近似。
    这里只用于画进度环，精度足够，而且每帧最多 72 次 pointAtPercent。
    """
    total = path.length()
    if total <= 0 or length <= 0:
        return
    steps = max(8, int(72 * min(1.0, length / total)))
    first = True
    for i in range(steps + 1):
        t = (start + length * i / steps) / total
        p = path.pointAtPercent(t % 1.0)
        if first:
            out.moveTo(p)
            first = False
        else:
            out.lineTo(p)


def draw_diamond(painter: QPainter, center: QPointF, size: float,
                 color: QColor) -> None:
    """小菱形（鸣潮 UI 里最常见的分隔符）。"""
    path = QPainterPath()
    path.moveTo(center.x(), center.y() - size)
    path.lineTo(center.x() + size * 0.62, center.y())
    path.lineTo(center.x(), center.y() + size)
    path.lineTo(center.x() - size * 0.62, center.y())
    path.closeSubpath()
    painter.fillPath(path, QColor(color))


def draw_element_glyph(painter: QPainter, rect: QRectF, element: str,
                       color: QColor, thickness: float = 1.4) -> None:
    """
    六元素的几何徽记（不依赖素材，纯矢量）。

    只用最少笔画表达，10px 大小也能认出来：
        冷凝·六角雪 / 热熔·火苗 / 导电·闪电 / 气动·回旋 / 衍射·星芒 / 湮灭·倒锥
    """
    cx, cy = rect.center().x(), rect.center().y()
    s = min(rect.width(), rect.height()) / 2

    pen = QPen(color)
    pen.setWidthF(thickness)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

    painter.save()
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    key = (element or "").lower()

    if key == "glacio":                     # 六角雪花：三条交叉线
        import math
        for k in range(3):
            a = math.radians(60 * k + 90)
            painter.drawLine(QPointF(cx - s * 0.9 * math.cos(a), cy - s * 0.9 * math.sin(a)),
                             QPointF(cx + s * 0.9 * math.cos(a), cy + s * 0.9 * math.sin(a)))

    elif key == "fusion":                   # 火苗：上尖下圆
        path = QPainterPath()
        path.moveTo(cx, cy - s)
        path.cubicTo(cx + s * 0.95, cy - s * 0.1, cx + s * 0.55, cy + s * 0.95, cx, cy + s * 0.95)
        path.cubicTo(cx - s * 0.55, cy + s * 0.95, cx - s * 0.95, cy - s * 0.1, cx, cy - s)
        painter.drawPath(path)

    elif key == "electro":                  # 闪电
        path = QPainterPath()
        path.moveTo(cx + s * 0.35, cy - s)
        path.lineTo(cx - s * 0.45, cy + s * 0.12)
        path.lineTo(cx + s * 0.05, cy + s * 0.12)
        path.lineTo(cx - s * 0.28, cy + s)
        path.lineTo(cx + s * 0.5, cy - s * 0.14)
        path.lineTo(cx - s * 0.02, cy - s * 0.14)
        path.closeSubpath()
        painter.drawPath(path)

    elif key == "aero":                     # 回旋风：两段弧
        painter.drawArc(QRectF(cx - s, cy - s, 2 * s, 2 * s), 30 * 16, 220 * 16)
        painter.drawArc(QRectF(cx - s * 0.45, cy - s * 0.42, s * 0.9, s * 0.84), 200 * 16, 200 * 16)

    elif key == "havoc":                    # 湮灭：倒锥
        path = QPainterPath()
        path.moveTo(cx - s * 0.85, cy - s * 0.75)
        path.lineTo(cx + s * 0.85, cy - s * 0.75)
        path.lineTo(cx, cy + s)
        path.closeSubpath()
        painter.drawPath(path)

    else:                                   # 衍射（默认）：四芒星
        path = QPainterPath()
        path.moveTo(cx, cy - s)
        path.quadTo(cx + s * 0.16, cy - s * 0.16, cx + s, cy)
        path.quadTo(cx + s * 0.16, cy + s * 0.16, cx, cy + s)
        path.quadTo(cx - s * 0.16, cy + s * 0.16, cx - s, cy)
        path.quadTo(cx - s * 0.16, cy - s * 0.16, cx, cy - s)
        painter.drawPath(path)

    painter.restore()


# ============================================================ 图片工具

def cover_pixmap(pm: QPixmap, size: int, radius: float = 0.0,
                 dpr: float = 1.0, zoom: float = 1.0) -> QPixmap:
    """
    把任意尺寸的图裁成"铺满 size×size"的圆角方块。

    素材本来是从技能图标图集里切出来的，尺寸不统一（105~149），
    直接缩放会变形，所以按较长边铺满、居中裁掉多余部分。

    :param radius: 圆角半径；>= size/2 时直接裁成正圆（头像用）
    :param zoom:   放大倍数。立绘素材自带一圈描边底框，
                   放大一点把底框挤出画面，脸才能填满整个圆。
    """
    if pm is None or pm.isNull() or size <= 0:
        return QPixmap()

    px = size * dpr
    scaled = pm.scaled(int(px * zoom), int(px * zoom),
                       Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation)

    out = QPixmap(int(round(px)), int(round(px)))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.GlobalColor.transparent)

    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    if radius >= size / 2.0 - 0.5:
        circle = QPainterPath()
        circle.addEllipse(QRectF(0, 0, px, px))
        p.setClipPath(circle)
    elif radius > 0:
        p.setClipPath(squircle(QRectF(0, 0, px, px), radius * dpr))

    p.drawPixmap(int((px - scaled.width()) / 2),
                 int((px - scaled.height()) / 2), scaled)
    p.end()
    return out


# ============================================================ 控件样式表
# 说明：能用 QPainter 画的一律画（悬浮窗），但表单类控件（下拉框、输入框、
# 列表、滚动条）有现成的交互逻辑，用 QSS 换皮最划算，不值得自己重写。

def window_qss() -> str:
    """所有管理窗口共用的控件皮肤（跟随当前主题）。"""
    dark = is_dark()

    btn_bg = (255, 255, 255, 14) if dark else (15, 26, 38, 9)
    btn_hover = (255, 255, 255, 26) if dark else (15, 26, 38, 15)
    btn_border = (255, 255, 255, 26) if dark else (15, 26, 38, 30)
    field_bg = qa("#000000", 0.35) if dark else "#F7F9FC"
    field_border = qa("#FFFFFF", 0.12) if dark else qa("#0F1A26", 0.20)
    field_hover = qa(GOLD, 0.35) if dark else qa(GOLD, 0.55)
    field_focus = qa(GOLD, 0.62) if dark else qa(GOLD, 0.80)
    text = IVORY
    arrow = qa(text, 0.55)
    hover_bg = qa("#FFFFFF", 0.05) if dark else qa("#0F1A26", 0.05)
    list_hover = qa("#FFFFFF", 0.055) if dark else qa("#0F1A26", 0.045)
    list_sel = qa(GOLD, 0.16) if dark else qa(GOLD, 0.13)
    tab_sel = qa(GOLD, 0.14) if dark else qa(GOLD, 0.11)
    scroll = qa("#FFFFFF", 0.16) if dark else qa("#0F1A26", 0.16)
    pane_border = qa("#FFFFFF", 0.07) if dark else qa("#0F1A26", 0.10)

    return f"""
    QWidget {{
        color: {text};
        font-size: 12px;
    }}
    QLabel {{ background: transparent; }}
    QLabel#H1 {{ font-size: 17px; font-weight: 600; }}
    QLabel#Muted {{ color: {qa(text, 0.55)}; }}
    QLabel#Hint {{ color: {qa(text, 0.42)}; font-size: 11px; }}
    QLabel#Gold {{ color: {GOLD}; }}
    QLabel#RowName {{ color: {qa(text, 0.88)}; font-size: 12px; }}

    /* ---------- 按钮 ---------- */
    QPushButton {{
        background: rgba({btn_bg[0]},{btn_bg[1]},{btn_bg[2]},{btn_bg[3]});
        border: 1px solid rgba({btn_border[0]},{btn_border[1]},{btn_border[2]},{btn_border[3]});
        border-radius: 10px;
        padding: 8px 16px;
        color: {text};
    }}
    QPushButton:hover {{
        background: rgba({btn_hover[0]},{btn_hover[1]},{btn_hover[2]},{btn_hover[3]});
        border-color: {field_hover};
    }}
    QPushButton:pressed {{ background: {qa(GOLD, 0.18)}; }}
    QPushButton:disabled {{
        color: {qa(text, 0.30)};
        background: rgba({btn_bg[0]},{btn_bg[1]},{btn_bg[2]},5);
    }}

    /* 主行动按钮：强调色实底，全窗口只留一个 */
    QPushButton#Primary {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {GOLD_HI}, stop:1 {GOLD});
        border: 1px solid {qa("#FFFFFF", 0.30)};
        color: {TEXT_ON_ACCENT};
        font-weight: 600;
    }}
    QPushButton#Primary:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {GOLD_HI}, stop:1 {GOLD_HI});
    }}
    QPushButton#Primary:pressed {{ background: {GOLD}; }}
    QPushButton#Primary:disabled {{ color: {qa(TEXT_ON_ACCENT, 0.45)}; }}

    /* 分段控件（主题切换用） */
    QPushButton#Seg {{
        background: rgba({btn_bg[0]},{btn_bg[1]},{btn_bg[2]},10);
        border: 1px solid rgba({btn_border[0]},{btn_border[1]},{btn_border[2]},18);
        border-radius: 8px;
        padding: 5px 14px;
        color: {qa(text, 0.55)};
        font-size: 11px;
    }}
    QPushButton#Seg:hover {{ color: {text}; }}
    QPushButton#Seg:checked {{
        background: {qa(GOLD, 0.18)};
        border-color: {qa(GOLD, 0.55)};
        color: {GOLD};
        font-weight: 600;
    }}

    /* 关闭按钮：圆形小叉 */
    QPushButton#Close {{
        background: transparent;
        border: none;
        border-radius: 13px;
        color: {qa(text, 0.55)};
        font-size: 14px;
        padding: 0px;
    }}
    QPushButton#Close:hover {{ background: {qa(ALERT, 0.78)}; color: #FFFFFF; }}

    /* ---------- 输入类 ---------- */
    QComboBox, QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
        background: {field_bg};
        border: 1px solid {field_border};
        border-radius: 8px;
        padding: 6px 9px;
        color: {text};
        selection-background-color: {qa(GOLD, 0.35)};
        selection-color: {text};
    }}
    QComboBox:hover, QLineEdit:hover, QTextEdit:hover {{ border-color: {field_hover}; }}
    QComboBox:focus, QLineEdit:focus, QTextEdit:focus {{ border-color: {field_focus}; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {arrow};
        margin-right: 6px;
    }}
    QComboBox QAbstractItemView {{
        background: {POPUP_BG};
        border: 1px solid {qa(GOLD, 0.45)};
        border-radius: 8px;
        padding: 4px;
        outline: none;
        selection-background-color: {qa(GOLD, 0.20)};
        selection-color: {text};
    }}

    /* ---------- 列表 ---------- */
    QListWidget {{ background: transparent; border: none; outline: none; }}
    QListWidget::item {{
        padding: 9px 12px;
        margin: 2px 0px;
        border-radius: 9px;
        color: {qa(text, 0.80)};
    }}
    QListWidget::item:hover {{ background: {list_hover}; }}
    QListWidget::item:selected {{ background: {list_sel}; color: {text}; }}

    /* ---------- 标签页 ---------- */
    QTabWidget::pane {{
        border: 1px solid {pane_border};
        border-radius: 12px;
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {qa(text, 0.50)};
        padding: 7px 18px;
        margin-right: 4px;
        border-radius: 9px;
    }}
    QTabBar::tab:hover {{ color: {text}; background: {hover_bg}; }}
    QTabBar::tab:selected {{ background: {tab_sel}; color: {GOLD}; }}

    /* ---------- 分组框 ---------- */
    QGroupBox {{
        border: 1px solid {pane_border};
        border-radius: 12px;
        margin-top: 16px;
        padding: 14px 12px 10px 12px;
        font-size: 12px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        color: {qa(GOLD, 0.90)};
    }}

    /* ---------- 滚动条 ---------- */
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {scroll}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {qa(GOLD, 0.60)}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    /* ---------- 其它 ---------- */
    QProgressBar {{
        background: {qa(text, 0.10)};
        border: none;
        border-radius: 4px;
        height: 8px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {GOLD_DEEP}, stop:1 {GOLD});
        border-radius: 4px;
    }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{
        width: 15px; height: 15px;
        border-radius: 4px;
        border: 1px solid {qa(text, 0.35)};
        background: {field_bg};
    }}
    QCheckBox::indicator:checked {{ background: {GOLD}; border-color: {GOLD_HI}; }}
    QToolTip {{
        background: {POPUP_BG};
        color: {text};
        border: 1px solid {qa(GOLD, 0.45)};
        border-radius: 6px;
        padding: 5px 8px;
    }}
    """


def menu_qss() -> str:
    """右键菜单 / 弹出菜单的皮肤（悬浮窗用，跟随主题）。"""
    return f"""
    QMenu {{
        background: {POPUP_BG};
        border: 1px solid {qa(GOLD, 0.35)};
        border-radius: 10px;
        padding: 6px;
        color: {IVORY};
        font-size: 12px;
    }}
    QMenu::item {{ padding: 8px 18px; border-radius: 6px; margin: 1px 4px; }}
    QMenu::item:selected {{ background: {qa(GOLD, 0.18)}; color: {IVORY}; }}
    QMenu::separator {{
        height: 1px;
        background: {qa(DIVIDER, 0.10)};
        margin: 5px 12px;
    }}
    """


def row_qss() -> str:
    """剧本编辑器每一行的皮肤（暗/亮自动适配）。"""
    return f"""
    #EditorRow {{ background: transparent; border-bottom: 1px solid {qa(DIVIDER, 0.05)}; }}
    #EditorRow:hover {{ background: {qa(DIVIDER, 0.035)}; }}
    #EditorRow QLabel {{ color: {qa(IVORY, 0.80)}; font-size: 12px; background: transparent; }}
    #EditorRow QComboBox {{
        color: {IVORY};
        background: {qa(DIVIDER, 0.05)};
        border: 1px solid {qa(DIVIDER, 0.09)};
        border-radius: 7px; padding: 3px 8px; font-size: 12px;
    }}
    #EditorRow QComboBox:hover {{ border-color: {qa(GOLD, 0.50)}; }}
    """
