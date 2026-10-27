"""
启动器：程序打开后的第一个窗口。

设计思路
--------
左侧不堆按钮堆功能，而是先回答一个问题：**"我上次打的是哪个轴？"**
所以顶部是一块"最近使用"区域 —— 队伍里三个角色的头像 + 轴名 + 步数，
这才是玩家打开工具时真正想确认的东西。

下面几行入口刻意做成极简文字行（无图标、无边框，hover 才亮），
视觉重量全部让给上面的头像区。
"""

from __future__ import annotations

import glob
import json
import os

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QWidget

import ui.theme as theme
from ui.frame import HEADER_H, GlassWindow
from ui.widgets import get_cached_pixmap
from utils.character_meta import element_of
from utils.logger import log
from utils.paths import project_root


def recent_routine() -> dict | None:
    """
    找最近改过的剧本，返回它的概要。

    启动器要显示"上次打的轴"，靠修改时间判断最省事，
    也不用在 config 里多维护一个 last_routine 字段。
    任何异常都返回 None（宁可少显示一块，也不能让启动器打不开）。
    """
    try:
        root = str(project_root())
        files = glob.glob(os.path.join(root, "configs", "routines", "*.json"))
        if not files:
            return None
        latest = max(files, key=os.path.getmtime)
        with open(latest, "r", encoding="utf-8") as f:
            data = json.load(f)

        team_map = {int(k): v for k, v in data.get("team_config", {}).items()}
        return {
            "name": os.path.splitext(os.path.basename(latest))[0],
            "team": [team_map[i] for i in sorted(team_map)],
            "opener": len(data.get("opener_script", [])),
            "loop": len(data.get("loop_script", [])),
        }
    except Exception as e:
        log.debug(f"读取最近剧本失败（不影响启动）: {e}")
        return None


class NavRow(QWidget):
    """
    启动器的一行入口。

    自己画而不是用 QPushButton，是为了拿到：
        · 悬停时整行淡入的暖色底 + 右侧箭头轻微右移
        · 不受不同系统按钮 padding 影响的行高
    """

    clicked = Signal()

    def __init__(self, title: str, desc: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._desc = desc
        self._hover = 0.0
        self.setFixedHeight(56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def enterEvent(self, event):
        self._hover = 1.0
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = 0.0
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(0, 1, -1, -1)
        hover = self._hover

        # 悬停底色：很淡的暖白，不抢标题
        if hover > 0.01:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.rgba(theme.GOLD, 0.10 * hover))
            p.drawPath(theme.squircle(rect, 12))
            p.setPen(QPen(theme.rgba(theme.GOLD, 0.22 * hover), 1.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(theme.squircle(rect, 12))

        # 标题 + 说明
        p.setFont(theme.font(13.5, 600))
        p.setPen(theme.rgba(theme.IVORY, 0.92 + 0.08 * hover))
        p.drawText(QRectF(14, 8, rect.width() - 60, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._title)

        p.setFont(theme.font(11, 400, 0.3))
        p.setPen(theme.rgba(theme.IVORY, 0.42 + 0.18 * hover))
        p.drawText(QRectF(14, 27, rect.width() - 60, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._desc)

        # 右侧箭头：悬停时往右挪 3px，暗示"能进去"
        cx = rect.right() - 20 + 3 * hover
        cy = rect.center().y()
        pen = QPen(theme.rgba(theme.GOLD, 0.45 + 0.45 * hover))
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(int(cx - 3), int(cy - 5), int(cx + 2), int(cy))
        p.drawLine(int(cx + 2), int(cy), int(cx - 3), int(cy + 5))

        p.end()


class StartMenu(GlassWindow):
    """启动器窗口。"""

    open_settings = Signal()        # 按键绑定
    open_upload = Signal()          # 流程上传 / 编辑
    open_select = Signal()          # 流程选择
    open_factory = Signal()         # 素材工坊
    start_overlay = Signal()        # 预留

    CONTENT_W = 520
    CONTENT_H = 524

    def __init__(self):
        super().__init__("WUWA HEKILI", self.CONTENT_W, self.CONTENT_H,
                         subtitle="鸣潮 · 连招提示器")
        self.setStyleSheet(theme.window_qss())

        self._routine = recent_routine()
        self._avatars = self._load_avatars()
        self._build()

    # ------------------------------------------------------------ 数据

    def _load_avatars(self):
        """把最近轴的队伍头像裁成圆片。"""
        if not self._routine:
            return []
        root = str(project_root())
        out = []
        for name in self._routine["team"][:3]:
            path = os.path.join(root, "assets", "characters", name,
                                "character", "avatar.png")
            pm = get_cached_pixmap(path)
            if pm is None or pm.isNull():
                out.append((name, None))
            else:
                out.append((name, theme.cover_pixmap(pm, 74, radius=37, zoom=1.16)))
        return out

    # ------------------------------------------------------------ 布局

    def _build(self):
        self.btn_settings = NavRow("按键绑定", "手柄十字键 / 键鼠按键对照")
        self.btn_settings.clicked.connect(self.open_settings.emit)

        self.btn_upload = NavRow("流程上传", "用黑话写一条轴，解析成可执行的剧本")
        self.btn_upload.clicked.connect(self.open_upload.emit)

        self.btn_select = NavRow("流程选择", "挑一条已有的轴，进入实战提示")
        self.btn_select.clicked.connect(self.open_select.emit)

        self.btn_factory = NavRow("素材工坊", "从录像里裁切技能图标，补齐缺的素材")
        self.btn_factory.clicked.connect(self.open_factory.emit)

        # hero 区是自绘的，用一块固定高度的占位把后续控件推到正确位置
        spacer = QWidget()
        spacer.setFixedHeight(144)
        self.body_layout.addWidget(spacer)

        self.body_layout.addWidget(self.btn_settings)
        self.body_layout.addWidget(self.btn_upload)
        self.body_layout.addWidget(self.btn_select)
        self.body_layout.addWidget(self.btn_factory)
        self.body_layout.addStretch(1)

    # ------------------------------------------------------------ 装饰

    def paint_content(self, p: QPainter):
        """hero 区：队伍头像 + 最近轴信息 + 声明。"""
        rect = self.panel_rect()
        base_x = rect.left() + 20 + 20
        top = rect.top() + HEADER_H + 4

        # ---- 入口的承托卡片 ----
        # 没有它，几行文字会像浮在半空；有它才像 iOS 设置里的分组。
        row_top = self.btn_settings.mapTo(self, self.btn_settings.rect().topLeft()).y() - 7
        row_bot = self.btn_factory.mapTo(self, self.btn_factory.rect().bottomLeft()).y() + 7
        card = QRectF(rect.left() + 12, row_top, rect.width() - 24, row_bot - row_top)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.rgba(theme.CARD_BG, 0.035 if theme.is_dark() else 0.04))
        p.drawPath(theme.squircle(card, 14))
        p.setPen(QPen(theme.rgba(theme.CARD_BORDER, 0.055 if theme.is_dark() else 0.08), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(theme.squircle(card, 14))

        # 行之间的细分隔线（贴着卡片内边，左右各留 14）
        for row in (self.btn_settings, self.btn_upload, self.btn_select):
            y = row.mapTo(self, row.rect().bottomLeft()).y() + 7
            p.setPen(theme.rgba(theme.DIVIDER, 0.05 if theme.is_dark() else 0.07))
            p.drawLine(card.left() + 14, y, card.right() - 14, y)

        # 头像后的暖光
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QRadialGradient
        glow = QRadialGradient(QPointF(base_x + 110, top + 74), 190)
        glow.setColorAt(0.0, theme.rgba(theme.GOLD, 0.13))
        glow.setColorAt(1.0, theme.rgba(theme.GOLD, 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawPath(theme.squircle(rect.adjusted(12, HEADER_H, -12, -12), 18))

        # ---- 头像 / 占位 ----
        if self._avatars:
            size = 74
            overlap = 18
            for i, (name, pm) in enumerate(self._avatars):
                x = base_x + i * (size - overlap)
                center = QRectF(x, top + 36, size, size)

                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.rgba(theme.TILE_PLATE, 0.95))
                p.drawEllipse(center)

                if pm is not None:
                    p.drawPixmap(center.topLeft(), pm)

                p.setPen(QPen(theme.rgba(theme.GOLD, 0.55), 1.4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(center.adjusted(0.5, 0.5, -0.5, -0.5))

                # 元素色弧：只画下半圈，轻量但一眼能认属性
                element = element_of(name)
                if element:
                    color = theme.element_color(element)
                    pen = QPen(theme.rgba(color.name(), 0.9), 2.2)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    p.setPen(pen)
                    p.drawArc(center.adjusted(-1.4, -1.4, 1.4, 1.4), 200 * 16, 140 * 16)

            info_x = base_x + len(self._avatars) * (size - overlap) + 18
        else:
            info_x = base_x

        info_w = rect.right() - 40 - info_x

        # ---- 最近轴的文字信息 ----
        y = top + 40
        p.setFont(theme.font(10.5, 600, 1.4))
        p.setPen(theme.rgba(theme.GOLD, 0.62))
        p.drawText(QRectF(info_x, y, info_w, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "上次使用" if self._routine else "还没有剧本")

        if self._routine:
            name_font = theme.font(17, 600)
            p.setFont(name_font)
            p.setPen(theme.rgba(theme.IVORY, 0.95))
            p.drawText(QRectF(info_x, y + 18, info_w, 26),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       theme.elide(self._routine["name"], name_font, info_w))

            p.setFont(theme.font(11, 400, 0.4))
            p.setPen(theme.rgba(theme.IVORY, 0.45))
            p.drawText(QRectF(info_x, y + 46, info_w, 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"启动轴 {self._routine['opener']} 步 · "
                       f"循环轴 {self._routine['loop']} 步")
        else:
            hint_font = theme.font(12, 400)
            p.setFont(hint_font)
            p.setPen(theme.rgba(theme.IVORY, 0.45))
            p.drawText(QRectF(info_x, y + 20, info_w, 40),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                       | Qt.TextFlag.TextWordWrap,
                       "去「流程上传」写第一条连招，\n程序会把它变成一条时间轴。")

        # ---- 底部版本信息 ----
        p.setFont(theme.font(10, 500, 1.0))
        p.setPen(theme.rgba(theme.IVORY, 0.28))
        p.drawText(QRectF(rect.left() + 22, rect.bottom() - 32, 240, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "v2.2 · 潮汐界面")

        # 右下角一颗小金点，收边用
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.rgba(theme.GOLD, 0.5))
        p.drawEllipse(QRectF(rect.right() - 26, rect.bottom() - 24, 3, 3))

    def closeEvent(self, event):
        log.info("👋 启动器关闭，正在退出程序...")
        from PySide6.QtWidgets import QApplication
        QApplication.quit()
