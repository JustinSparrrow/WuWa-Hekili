"""
游戏内悬浮窗：Hekili 风格的横向技能队列。

视觉结构（自左向右）
------------------
    ┌───────────────────────────────────────────────────────────────┐
    │  ◯头像  │ [历史] [ 当前 ] [下一个] [未来]      启动轴 03/24    │
    │  元素徽记                                    普攻             │
    │                                              轻点             │
    └───────────────────────────────────────────────────────────────┘
    整块面板是一枚"墨黑玻璃胶囊"：外阴影 + 渐变 + 噪点 + 金色细线，
    头像用鸣潮角色立绘，元素徽记用矢量几何（不依赖素材）。

为什么做成一整块面板，而不是四个漂浮的方格
--------------------------------------
四格散落在游戏画面上，看起来像四个贴纸，没有"这是一条时间轴"的语义。
装进同一个胶囊里之后：
    · 玩家一眼就知道这四格是一组、谁在谁前面
    · 底色统一压暗，战斗特效再亮也不会糊掉文字
    · 头像常驻显示"现在是谁的轴"，切人时视觉上立刻跟上

性能设计
--------
    1. 面板（阴影/玻璃/分隔线）缓存成 QPixmap，只在尺寸或透明度变化时重建。
    2. 格子池化 + 动画对象常驻复用（v1.1 的老规矩，继续保留）。
    3. 图标不做中间缩放，直接用画笔变换绘制（见 widgets.ActionWidget）。
    4. 只有"当前格"画柔光与外阴影，其余格省掉。
"""

from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation,
                            QRect, QRectF, QSize, Qt, Signal)
from PySide6.QtGui import (QAction, QBrush, QColor, QFontMetricsF, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QWidget

import ui.theme as theme
from ui.widgets import ActionWidget, get_cached_pixmap
from utils.character_meta import element_of, name_cn
from utils.config_manager import config

# ============================================================ 尺寸常量
MARGIN = 16              # 四周留白，给柔和外阴影
PANEL_W, PANEL_H = 470, 128
PANEL_RADIUS = 34

# 面板内各元素的几何（相对面板左上角）
GEO_AVATAR = QRect(20, 37, 54, 54)
DIVIDER_X = 88
GEO_INFO = QRect(386, 30, 68, 62)

GEO_HIS = QRect(100, 42, 44, 44)
GEO_CUR = QRect(150, 18, 92, 92)
GEO_NXT = QRect(250, 34, 60, 60)
GEO_FUT = QRect(316, 42, 44, 44)

# 静止态的格子透明度：由近到远逐级压低
OP_HIS, OP_CUR, OP_NXT, OP_FUT = 0.45, 1.0, 0.85, 0.60
OP_IDLE = 0.84       # 未激活时整块面板的亮度（退后但不至于看不清预览）


class ParallelTrackWindow(QWidget):
    """
    并行轨小窗：在主悬浮窗**上方**单独浮一条"另一条时间线"。

    为什么是独立窗口
    --------------
    主窗是固定尺寸的胶囊布局，滑入/滑出动画全靠 geometry 算坐标。
    在里面挤第二行会把布局和动画一起搅乱，而且那条空白要一直占着。
    独立窗口只在真出现支线时才创建、才显示，普通轴一分钱不花。

    为什么不吃鼠标事件
    ----------------
    它浮在游戏画面上，接收鼠标就会挡住点击，也没法跟着主窗拖动。
    """

    MARGIN = 12
    PANEL_W, PANEL_H = 248, 56
    OFFSET_X = -2       # 相对主窗"当前格"的偏移，视觉上与当前格左对齐
    OFFSET_Y = -8       # 负数 = 浮在主窗上方

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            # WindowTransparentForInput 在 Windows 上映射成 WS_EX_TRANSPARENT，
            # 这是唯一能让顶层窗口真正"点得穿"的可靠方式；
            # 只设 WA_TransparentForMouseEvents 对顶层窗口不生效。
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(self.PANEL_W + self.MARGIN * 2,
                          self.PANEL_H + self.MARGIN * 2)

        self._slot = {}
        self._icon_pm = None
        self._btn_pm = None
        self._plate = None
        self._theme_gen = -1

    # ------------------------------------------------------------ 数据

    def set_slot(self, slot):
        """填入支线那一步的数据。"""
        self._slot = slot or {}
        icon = self._slot.get("icon_path")
        btn = self._slot.get("btn_path")
        self._icon_pm = get_cached_pixmap(icon) if icon else None
        self._btn_pm = get_cached_pixmap(btn) if btn else None
        self.update()

    # ------------------------------------------------------------ 绘制

    def _build_plate(self):
        """玻璃底 + 外阴影，缓存一次。"""
        dpr = self.devicePixelRatioF() or 1.0
        pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)

        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.MARGIN, self.MARGIN, self.PANEL_W, self.PANEL_H)
        theme.draw_panel(p, rect, radius=18, shadow_spread=10, shimmer=True)

        # 左侧青色竖条：并行轨的"身份色"
        bar = QRectF(rect.left() + 13, rect.center().y() - 13, 3, 26)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.rgba(theme.CYAN, 0.85))
        p.drawPath(theme.squircle(bar, 1.5))
        p.end()

        self._plate = pm
        self._theme_gen = theme.generation()

    def paintEvent(self, event):
        if self._plate is None or self._theme_gen != theme.generation():
            self._build_plate()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawPixmap(0, 0, self._plate)

        rect = QRectF(self.MARGIN, self.MARGIN, self.PANEL_W, self.PANEL_H)

        # ---- 图标 ----
        icon_rect = QRectF(rect.left() + 26, rect.top() + 9, 38, 38)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.TILE_PLATE))
        p.drawPath(theme.squircle(icon_rect, 11))
        if self._icon_pm is not None and not self._icon_pm.isNull():
            p.save()
            p.setClipPath(theme.squircle(icon_rect, 11))
            scale = max(icon_rect.width() / self._icon_pm.width(),
                        icon_rect.height() / self._icon_pm.height())
            p.translate(icon_rect.center())
            p.scale(scale, scale)
            p.drawPixmap(-self._icon_pm.width() / 2, -self._icon_pm.height() / 2, self._icon_pm)
            p.restore()
        pen = QPen(theme.rgba(theme.CYAN, 0.55))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(theme.squircle(icon_rect, 11))

        # ---- 标题 / 动作名 ----
        title_font = theme.font(10.5, 600, 1.2)
        p.setFont(title_font)
        p.setPen(theme.rgba(theme.CYAN, 0.80))
        p.drawText(QRectF(rect.left() + 74, rect.top() + 8, 120, 13),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "可同时按")

        desc = self._display_desc()
        p.setFont(theme.font(13.5, 600))
        p.setPen(QColor(theme.IVORY))
        p.drawText(QRectF(rect.left() + 74, rect.top() + 24, 110, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   theme.elide(desc, theme.font(13, 600), 110))

        # ---- 按键帽 ----
        if self._btn_pm is not None and not self._btn_pm.isNull():
            k = 22.0
            krect = QRectF(rect.right() - 13 - k, rect.center().y() - k / 2, k, k)
            p.setBrush(theme.rgba("#05070A", 0.82))
            p.setPen(QPen(theme.rgba("#FFFFFF", 0.20), 1.0))
            p.drawPath(theme.squircle(krect, 7))
            inner = krect.adjusted(3.5, 3.5, -3.5, -3.5)
            p.save()
            scale = min(inner.width() / self._btn_pm.width(),
                        inner.height() / self._btn_pm.height())
            p.translate(inner.center())
            p.scale(scale, scale)
            p.drawPixmap(-self._btn_pm.width() / 2, -self._btn_pm.height() / 2, self._btn_pm)
            p.restore()

        p.end()

    def _display_desc(self):
        slot = self._slot
        desc = slot.get("desc", "") or ""
        if slot.get("type") == "intro":
            target = name_cn(slot.get("char_name", ""))
            if target:
                return f"切 · {target}"
        return desc

    # ------------------------------------------------------------ 跟随

    def follow(self, main_window):
        """贴到主窗上方；主窗太靠屏幕顶时改放到下方，避免被裁掉。"""
        anchor = main_window.pos() + QPoint(MARGIN + GEO_CUR.x() - 24, MARGIN)

        x = anchor.x()
        y = anchor.y() - self.height() + self.OFFSET_Y
        if y < 0:
            y = main_window.pos().y() + main_window.height() - MARGIN + 4

        screen = QApplication.screenAt(QPoint(x + self.width() // 2, y))
        if screen is not None:
            avail = screen.availableGeometry()
            x = max(avail.left() + 4, min(x, avail.right() - self.width() - 4))

        self.move(x, y)

    def showEvent(self, event):
        self._plate = None      # DPI 可能变了，重画底板
        super().showEvent(event)


class HekiliOverlay(QMainWindow):
    """
    游戏内的透明悬浮窗。

    推进时所有格子整体左移一档，最右侧补入新的一格，最左侧淡出回收。
    飞出的格子不飞出面板（否则会画到玻璃外面），而是在历史位原地缩小淡出。
    """

    open_settings_signal = Signal()
    return_to_menu_signal = Signal()

    SLOT_COUNT = 4        # 屏幕上同时可见的格子数
    ANIM_MS = 240         # 滑动动画时长，越短越跟手

    def __init__(self):
        super().__init__()
        self.setWindowTitle("WuWa Hekili Overlay")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.setFixedSize(PANEL_W + MARGIN * 2, PANEL_H + MARGIN * 2)

        old_x = config.get("settings.window_x", 100)
        old_y = config.get("settings.window_y", 100)
        self.move(old_x, old_y)
        self._drag_pos = QPoint()

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # 面板缓存 / 头像缓存 / 当前显示的信息
        self._plate = None
        self._theme_gen = -1
        self._opacity = OP_IDLE         # 未激活时整体退后
        self._active = False
        self._cur_slot = {}
        self._meta = None
        self._avatar_pm = None
        self._avatar_key = None
        self._avatar_dpr = 0.0

        self.widgets = []           # 当前在台上的格子：[历史, 当前, 下一个, 未来]
        self.exiting_widget = None  # 本轮淡出、待回收的格子
        self._pool = []             # 空闲格子池
        self.parallel_win = None    # 并行轨小窗（懒创建）

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(200)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._setup_animation()

        # 主题切换：玻璃面板是缓存图，必须重画
        theme.bus.changed.connect(self._on_theme_changed)

    # ============================================================ 动画对象池

    def _setup_animation(self):
        """
        预先创建好常驻的动画对象。

        5 个"物理槽位"（淡出位 + 4 个静止位），每个槽位一对动画：
        一个驱动 geometry（同时完成位移+缩放），一个驱动 opacity。
        之后每轮推进只改 target / startValue / endValue，不再 new 对象。
        """
        from PySide6.QtCore import QParallelAnimationGroup
        easing = QEasingCurve(QEasingCurve.Type.OutExpo)
        self._anim_group = QParallelAnimationGroup(self)
        self._animators = []

        for _ in range(self.SLOT_COUNT + 1):
            anim_geo = QPropertyAnimation(self._anim_group)
            anim_geo.setPropertyName(b"geometry")
            anim_geo.setDuration(self.ANIM_MS)
            anim_geo.setEasingCurve(easing)
            self._anim_group.addAnimation(anim_geo)

            anim_op = QPropertyAnimation(self._anim_group)
            anim_op.setPropertyName(b"opacity")
            anim_op.setDuration(self.ANIM_MS)
            anim_op.setEasingCurve(easing)
            self._anim_group.addAnimation(anim_op)

            self._animators.append((anim_geo, anim_op))

        self._anim_group.finished.connect(self._on_anim_finished)

    def _stop_anim(self):
        """已有动画在跑就停掉（stops 不触发 finished，不会误回收格子）。"""
        from PySide6.QtCore import QParallelAnimationGroup
        if self._anim_group.state() == QParallelAnimationGroup.State.Running:
            self._anim_group.stop()

    # ============================================================ 格子池

    def _take_widget(self):
        """从池里取一个空闲格子，池空时才真正构造新的。"""
        if self._pool:
            w = self._pool.pop()
        else:
            w = ActionWidget(self.central_widget)
        w.show()
        return w

    def _recycle_widget(self, widget):
        widget.hide()
        self._pool.append(widget)

    def _drop_exiting(self):
        """回收上一轮淡出的格子（动画被打断时也要兜底调用，否则会漏）。"""
        if self.exiting_widget is not None:
            self._recycle_widget(self.exiting_widget)
            self.exiting_widget = None

    # ================================================================ 对外接口

    def update_ui(self, visual_data, is_advance=False, is_rollback=False,
                  parallel_slot=None, meta=None):
        """
        刷新悬浮窗。

        :param visual_data:   [历史, 当前, 下一个, 未来] 四个槽位的数据
        :param is_advance:    True 表示"正常推进一格"，走滑动动画；False 走瞬间重排
        :param is_rollback:   True 表示回退，直接重排（避免动画方向错乱）
        :param parallel_slot: 并行轨要显示的那一步；None 表示当前没有支线
        :param meta:          {"phase","index","total"}，右上角"在轴的哪儿"
        """
        data = list(visual_data) if visual_data else []
        while len(data) < self.SLOT_COUNT:
            data.append({})

        self._stop_anim()
        self._drop_exiting()

        if not is_advance or is_rollback or len(self.widgets) < self.SLOT_COUNT:
            self._rebuild(data)
        else:
            self._slide(data)

        self._cur_slot = data[1]
        self._meta = meta
        self._sync_avatar(data[1])
        self.update()

        self._sync_parallel_track(parallel_slot)

    # ------------------------------------------------------------ 状态

    def set_active(self, active):
        """脚本是否已经激活。未激活时整块面板压暗后退，激活后点亮。"""
        active = bool(active)
        if active == self._active:
            return
        self._active = active
        self._opacity = 1.0 if active else OP_IDLE
        self._plate = None
        self.update()

    def play_activate(self):
        """激活瞬间：当前格放一圈金色波纹。"""
        if len(self.widgets) > 1:
            self.widgets[1].set_activated_style()

    def flash_reject(self, reason=""):
        """
        键按对了、但"按的时间不对"时给一次视觉反馈。

        :param reason: "hold" 该长按没按够 / "tap" 该轻按按太久
        """
        if len(self.widgets) > 1:
            self.widgets[1].flash_reject(reason)

    def update_gate_progress(self, remain, total):
        """
        刷新"当前动作还要占位多久"的环形进度。

        由主窗口的时间轴心跳调用。动作结束后归零，玩家看到金环收满
        就知道"现在可以按了"，不需要盯着提示猜。
        """
        if len(self.widgets) <= 1:
            return
        ratio = (remain / total) if total > 0 else 0.0
        self.widgets[1].set_gate_progress(ratio)

    # ------------------------------------------------------------ 头像

    def _sync_avatar(self, slot):
        """
        切人时换头像。头像用角色立绘裁圆，外面套一圈金环 + 元素弧。
        只在角色真的变了才重新裁图（裁一次要重建 QPixmap）。
        """
        path = slot.get("char_avatar")
        dpr = self.devicePixelRatioF() or 1.0
        key = (path, dpr)
        if key == self._avatar_key:
            return

        self._avatar_key = key
        self._avatar_dpr = dpr
        pm = get_cached_pixmap(path)
        if pm is not None and not pm.isNull():
            # zoom 1.16：立绘素材自带一圈圆形底框，放大一点把它挤出画面
            self._avatar_pm = theme.cover_pixmap(pm, GEO_AVATAR.width(),
                                                 radius=GEO_AVATAR.width() / 2,
                                                 dpr=dpr, zoom=1.16)
        else:
            self._avatar_pm = None

    # ------------------------------------------------------------ 瞬间重排

    def _rebuild(self, data):
        """把四个槽位瞬间摆到静止位置（启动、回退、切换设备时使用）。"""
        tiers = ("history", "current", "next", "far")
        geos = (GEO_HIS, GEO_CUR, GEO_NXT, GEO_FUT)
        ops = (OP_HIS, OP_CUR, OP_NXT, OP_FUT)

        while len(self.widgets) > self.SLOT_COUNT:
            self._recycle_widget(self.widgets.pop())

        for i in range(self.SLOT_COUNT):
            if i < len(self.widgets):
                w = self.widgets[i]
            else:
                w = ActionWidget(self.central_widget)
                self.widgets.append(w)

            w.set_data(data[i])
            w.set_gate_progress(0.0)
            self._apply_geo(w, geos[i], ops[i])
            w.update_style(data[i].get("variant"), i == 1,
                           data[i].get("parallel_hint", False), tier=tiers[i])
            w.show()

    def _apply_geo(self, widget, geo: QRect, opacity: float):
        """把面板内坐标换算成窗口坐标并落位。"""
        widget.setGeometry(geo.translated(MARGIN, MARGIN))
        widget.set_opacity(opacity)

    # -------------------------------------------------------------- 滑动动画

    def _slide(self, data):
        """
        正常推进：整体左移一档，最右补入新格子，最左原地淡出。

        注意飞出的格子**不能飞出面板**（会画到玻璃外面），
        所以让它在历史位附近缩小淡出，视觉上就是"被时间吃掉了"。
        """
        w_his = self.widgets[0]  # 原历史 -> 淡出
        w_out = self.widgets[1]  # 原当前 -> 变历史
        w_cur = self.widgets[2]  # 原下一个 -> 变当前
        w_nxt = self.widgets[3]  # 原未来 -> 变下一个

        # 新格子从"未来"位的右后方轻轻晕开
        w_fut = self._take_widget()
        w_fut.set_data(data[3])
        w_fut.update_style(data[3].get("variant"), False,
                           data[3].get("parallel_hint", False), tier="far")
        w_fut.setGeometry(QRect(GEO_FUT.x() + 10, GEO_FUT.y() - 4,
                                GEO_FUT.width() + 8, GEO_FUT.height() + 8)
                          .translated(MARGIN, MARGIN))
        w_fut.set_opacity(0.0)

        # 旧格子的数据同步刷新（变体可能不同，图标可能换）
        w_out.set_data(data[0])
        w_cur.set_data(data[1])
        w_nxt.set_data(data[2])
        w_out.update_style(data[0].get("variant"), False,
                           data[0].get("parallel_hint", False), tier="history")
        w_cur.update_style(data[1].get("variant"), True,
                           data[1].get("parallel_hint", False), tier="current")
        w_nxt.update_style(data[2].get("variant"), False,
                           data[2].get("parallel_hint", False), tier="next")

        # 新一轮开始，进度环从零算起（旧进度属于上一格，不能留在新格上）
        for w in (w_out, w_cur, w_nxt, w_fut):
            w.set_gate_progress(0.0)

        self.exiting_widget = w_his
        self.widgets = [w_out, w_cur, w_nxt, w_fut]

        # 复用常驻动画：只重新绑定目标与起止值
        targets = [
            (w_his, GEO_HIS.adjusted(2, 2, -8, -8), 0.0),   # 原地缩小淡出
            (w_out, GEO_HIS, OP_HIS),
            (w_cur, GEO_CUR, OP_CUR),
            (w_nxt, GEO_NXT, OP_NXT),
            (w_fut, GEO_FUT, OP_FUT),
        ]

        for (anim_geo, anim_op), (widget, end_geo, end_op) in zip(self._animators, targets):
            end_rect = QRect(end_geo).translated(MARGIN, MARGIN)

            anim_geo.setTargetObject(widget)
            anim_geo.setStartValue(widget.geometry())
            anim_geo.setEndValue(end_rect)

            anim_op.setTargetObject(widget)
            anim_op.setStartValue(widget.get_opacity())
            anim_op.setEndValue(end_op)

        self._anim_group.start()

    def _on_anim_finished(self):
        """动画结束：把淡出的格子收回池子，供下一次复用。"""
        self._drop_exiting()

    # ============================================================ 主题

    def _on_theme_changed(self):
        """主题切换：丢掉缓存的玻璃面板，下一帧按新配色重画。"""
        self._plate = None
        if self.parallel_win is not None:
            self.parallel_win._plate = None
        for w in self.widgets:
            w.update()
        self.update()

    # ============================================================ 面板绘制

    def _build_plate(self):
        """
        整块玻璃胶囊只画一次，之后每帧贴图。

        阴影 16 层描边 + 470x128 的渐变与噪点，每帧重画会明显掉帧；
        而它只在窗口尺寸或透明度变化时才需要更新。
        """
        dpr = self.devicePixelRatioF() or 1.0
        pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)

        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(MARGIN, MARGIN, PANEL_W, PANEL_H)
        theme.draw_panel(p, rect, radius=PANEL_RADIUS, opacity=self._opacity,
                         shadow_spread=16)

        # ---- 当前位上的一盏暖光 ----
        # 当前格的位置永远不变，所以这层光可以烘进缓存里，一分钱不花。
        # 作用是给"现在按这里"一个视觉焦点，格子滑进滑出时像舞台追光。
        spot = QRectF(GEO_CUR).translated(MARGIN, MARGIN)
        glow = QRadialGradient(spot.center(), spot.width() * 1.15)
        glow.setColorAt(0.0, theme.rgba(theme.GOLD, 0.16 * self._opacity))
        glow.setColorAt(0.55, theme.rgba(theme.GOLD, 0.06 * self._opacity))
        glow.setColorAt(1.0, theme.rgba(theme.GOLD, 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawPath(theme.squircle(rect.adjusted(1, 1, -1, -1), PANEL_RADIUS - 1))

        # ---- 头像右侧的分隔线：金线 + 菱形（鸣潮 UI 的标志性分隔） ----
        x = MARGIN + DIVIDER_X
        grad = QLinearGradient(x, MARGIN + 34, x, MARGIN + 94)
        grad.setColorAt(0.0, theme.rgba(theme.GOLD, 0.0))
        grad.setColorAt(0.5, theme.rgba(theme.GOLD, 0.38 * self._opacity))
        grad.setColorAt(1.0, theme.rgba(theme.GOLD, 0.0))
        p.setPen(QPen(grad, 1.0))
        p.drawLine(x, MARGIN + 34, x, MARGIN + 94)

        theme.draw_diamond(p, QRectF(x - 4.5, MARGIN + 64 - 4.5, 9, 9).center(),
                           4.0, theme.rgba(theme.GOLD, 0.75 * self._opacity))

        p.end()
        self._plate = pm
        self._theme_gen = theme.generation()

    def paintEvent(self, event):
        if self._plate is None or self._theme_gen != theme.generation():
            self._build_plate()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawPixmap(0, 0, self._plate)

        self._paint_avatar(p)
        self._paint_info(p)
        p.end()

    def _paint_avatar(self, p: QPainter):
        """左侧头像：立绘 + 金环 + 元素弧 + 元素徽记。"""
        rect = QRectF(GEO_AVATAR).translated(MARGIN, MARGIN)
        opacity = self._opacity

        if self._avatar_pm is not None:
            p.drawPixmap(rect.topLeft(), self._avatar_pm)
        else:
            # 没有立绘也要有个像样的占位，不能留个黑洞
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.rgba("#12161D", 0.95))
            p.drawEllipse(rect)
            p.setPen(theme.rgba(theme.IVORY, 0.35))
            p.setFont(theme.font(15, 600))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                       (self._cur_slot.get("char_name") or "?")[:1].upper())

        # 金环
        pen = QPen(theme.rgba(theme.GOLD, 0.55 * opacity))
        pen.setWidthF(1.4)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect.adjusted(0.5, 0.5, -0.5, -0.5))

        # 元素弧：环的底部一段染上元素色，纯装饰但一眼能认出属性
        element = element_of(self._cur_slot.get("char_name"))
        if element:
            color = theme.element_color(element)
            pen = QPen(theme.rgba(color.name(), 0.95 * opacity))
            pen.setWidthF(2.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            arc_rect = rect.adjusted(-1.6, -1.6, 1.6, 1.6)
            p.drawArc(arc_rect, 200 * 16, 140 * 16)

            # 元素徽记：右下角小圆牌
            badge = QRectF(rect.right() - 13, rect.bottom() - 13, 19, 19)
            p.setPen(QPen(theme.rgba(color.name(), 0.65 * opacity), 1.0))
            p.setBrush(theme.rgba("#05070A", 0.92 * opacity))
            p.drawEllipse(badge)
            theme.draw_element_glyph(p, badge.adjusted(5.0, 5.0, -5.0, -5.0),
                                     element, theme.rgba(color.name(), 0.95 * opacity), 1.2)

    def _paint_info(self, p: QPainter):
        """
        右侧信息列：阶段+进度 / 动作名 / 手势要求。

        三行文字由 QFontMetrics 垂直居中排布，任何字号下都不会错位。
        """
        rect = QRectF(GEO_INFO).translated(MARGIN, MARGIN)
        slot = self._cur_slot or {}
        opacity = self._opacity

        # ---- 第一行：启动轴 / 循环轴 + 第几步 ----
        meta = self._meta or {}
        phase = ""
        if not self._active:
            phase = "待命中"
        elif meta.get("phase") == "opener":
            phase = f"启动轴 {meta.get('index', 0) + 1:02d}/{meta.get('total', 0):02d}"
        elif meta.get("phase") == "loop":
            phase = f"循环轴 {meta.get('index', 0) + 1:02d}/{meta.get('total', 0):02d}"

        y = rect.top()
        if phase:
            f = theme.font(10, 600, 1.0)
            p.setFont(f)
            p.setPen(theme.rgba(theme.GOLD, 0.52 * opacity))
            p.drawText(QRectF(rect.left(), y, rect.width(), 14),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, phase)
            y += 15

        # ---- 第二行：动作名 ----
        desc = self._display_desc(slot)
        f = theme.font(15, 600)
        p.setFont(f)
        p.setPen(QColor(theme.IVORY) if self._active else theme.rgba(theme.IVORY, 0.75))
        p.drawText(QRectF(rect.left(), y, rect.width(), 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   theme.elide(desc, f, rect.width()))
        y += 24

        # ---- 第三行：手势要求 ----
        text, color = self._press_hint(slot)
        if text:
            f = theme.font(11, 500, 0.4)
            p.setFont(f)
            p.setPen(theme.rgba(color, (0.9 if self._active else 0.55) * opacity))
            p.drawText(QRectF(rect.left(), y, rect.width(), 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

    def _display_desc(self, slot):
        """
        把剧本里的黑话 desc 翻成人话。

        剧本里切人是 "切-Mornye" 这种写法（写轴时方便），
        界面上应该显示"切 · 莫宁"。
        """
        desc = slot.get("desc", "") or ""
        if slot.get("type") == "intro":
            target = name_cn(slot.get("char_name", ""))
            if target:
                return f"切 · {target}"
        return desc or "—"

    def _press_hint(self, slot):
        """返回 (提示文字, 颜色)。"""
        if not self._active:
            return "按启动键开始", theme.GOLD

        if slot.get("parallel_hint"):
            return "可提前按", theme.CYAN

        mode = slot.get("press_mode")
        if mode == "hold":
            threshold = slot.get("hold_threshold") or 0
            if threshold:
                return f"长按 {threshold:.2f}".rstrip("0").rstrip(".") + "s", theme.AMBER
            return "长按", theme.AMBER
        if mode == "tap":
            return "轻点", theme.TEXT_DIM
        if slot.get("type") in ("intro", "dodge", "jump"):
            return "立即", theme.TEXT_DIM
        return "—", theme.TEXT_FAINT

    # ============================================================ 并行轨

    def _sync_parallel_track(self, slot):
        """
        维护并行轨小窗：没有支线就收起，有就显示并贴到主窗上方。

        窗口本身是懒创建的 —— 只有剧本里真的出现过并行动作，才会出现第二个窗口。
        """
        if not slot:
            self._hide_parallel_track()
            return

        if self.parallel_win is None:
            self.parallel_win = ParallelTrackWindow()

        self.parallel_win.set_slot(slot)
        self.parallel_win.follow(self)
        if not self.parallel_win.isVisible():
            self.parallel_win.show()

    def _hide_parallel_track(self):
        if self.parallel_win is not None and self.parallel_win.isVisible():
            self.parallel_win.hide()

    # ================================================================ 右键菜单

    def show_context_menu(self, pos):
        menu = QMenu(self)
        # 无边框 + 半透明才能吃到圆角；Windows 上按窗口逐个试过，
        # 只有 FramelessWindowHint + TranslucentBackground 这一组不会留方角
        menu.setWindowFlags(menu.windowFlags()
                            | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setStyleSheet(theme.menu_qss())

        settings_action = QAction("按键设置", self)
        settings_action.triggered.connect(lambda: self.open_settings_signal.emit())
        menu.addAction(settings_action)

        # 日间模式就地切换：打游戏时不用先回主菜单翻设置
        day_action = QAction("日间模式", self)
        day_action.setCheckable(True)
        day_action.setChecked(theme.current() == "light")
        day_action.toggled.connect(self._toggle_day_mode)
        menu.addAction(day_action)

        return_action = QAction("停止并返回主菜单", self)
        return_action.triggered.connect(lambda: self.return_to_menu_signal.emit())
        menu.addAction(return_action)

        menu.addSeparator()

        exit_action = QAction("退出程序", self)
        exit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(exit_action)

        menu.exec(self.mapToGlobal(pos))

    def _toggle_day_mode(self, on: bool):
        """右键菜单里的日间模式开关。"""
        theme.apply("light" if on else "dark")
        config.update_setting("settings.theme", theme.current())

    # ================================================================== 拖拽

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def moveEvent(self, event):
        """
        主窗一移动，支线小窗就跟着挪。

        放在 moveEvent 而不是鼠标拖拽里，是因为主窗还可能被代码移动
        （初始化定位、多分辨率适配），只挂在拖拽上迟早会脱节。
        """
        super().moveEvent(event)
        if self.parallel_win is not None and self.parallel_win.isVisible():
            self.parallel_win.follow(self)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            current_pos = self.pos()
            config.update_settings({
                "settings.window_x": current_pos.x(),
                "settings.window_y": current_pos.y(),
            })
            event.accept()

    # ------------------------------------------------------------ 生命周期

    def _clamp_to_screen(self):
        """拖到屏幕外就拉回来；换了分辨率也要保证面板完整可见。"""
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        x = max(avail.left() + 4, min(self.x(), avail.right() - self.width() - 4))
        y = max(avail.top() + 4, min(self.y(), avail.bottom() - self.height() - 4))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def showEvent(self, event):
        self._plate = None          # DPI 可能变了，重画底板
        self._avatar_key = None     # 头像也要按新 DPR 重裁
        self._sync_avatar(self._cur_slot)
        self._clamp_to_screen()
        super().showEvent(event)

        # 轻轻淡入，避免"啪"地一下出现在画面里
        self.setWindowOpacity(0.0)
        self._fade_anim.stop()
        self._fade_anim.start()

    def hideEvent(self, event):
        """主窗收起时，支线小窗必须一起收起，否则会孤零零留在屏幕上。"""
        self._hide_parallel_track()
        super().hideEvent(event)

    def closeEvent(self, event):
        """关闭主窗时连支线小窗一起关掉，避免残留顶层窗口让进程退不干净。"""
        self._hide_parallel_track()
        if self.parallel_win is not None:
            self.parallel_win.deleteLater()
            self.parallel_win = None
        super().closeEvent(event)
