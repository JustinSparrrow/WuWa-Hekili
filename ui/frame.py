"""
管理窗口的无边框玻璃外壳。

所有非游戏内窗口（启动器 / 设置 / 选择 / 编辑器）都套这一层：
    · 无边框 + 半透明背景，系统标题栏那一条灰色太出戏
    · 整块圆角玻璃卡片，柔和外阴影
    · 顶部一条自绘标题栏：左标题、右关闭、整条可拖动
    · 内容放进 self.body，子类只管往里塞控件

为什么不给每个窗口单独写绘制
------------------------
四个窗口如果各画各的，圆角半径、阴影浓度、标题字号迟早不一致。
一致感就是"贵"的来源，所以统一收在这里。
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QFontMetricsF, QPainter, QPixmap
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

import ui.theme as theme

SHADOW = 18          # 四周留给外阴影的空白
HEADER_H = 60        # 自绘标题栏高度
TITLE_RADIUS = 26


class GlassWindow(QWidget):
    """
    无边框玻璃窗口基类。

    子类用法：
        class Foo(GlassWindow):
            def __init__(self):
                super().__init__("标题", 460, 600)
                self.setStyleSheet(theme.window_qss())
                self.body_layout.addWidget(...)
    """

    def __init__(self, title: str, width: int, height: int,
                 subtitle: str = "", closable_by_esc: bool = True,
                 parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(width + SHADOW * 2, height + SHADOW * 2)
        self.setWindowTitle(title)

        self._title = title
        self._subtitle = subtitle
        self._closable_by_esc = closable_by_esc
        self._plate = None
        self._theme_gen = -1          # 缓存底图对应的主题代数
        self._drag_offset = None

        # 内容区：标题栏之下
        self.body = QWidget(self)
        self.body.setGeometry(SHADOW, SHADOW + HEADER_H,
                              width, height - HEADER_H)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(20, 4, 20, 18)
        self.body_layout.setSpacing(12)

        # 关闭按钮
        self.btn_close = QPushButton("✕", self)
        self.btn_close.setObjectName("Close")
        self.btn_close.setFixedSize(26, 26)
        self.btn_close.move(SHADOW + width - 40, SHADOW + 10)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setToolTip("关闭")
        self.btn_close.clicked.connect(self.close)
        self.btn_close.setStyleSheet(theme.window_qss())

        # 主题一换，皮肤和缓存的玻璃底图都得重来
        theme.bus.changed.connect(self._on_theme_changed)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(160)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ------------------------------------------------------------ 绘制

    def panel_rect(self) -> QRectF:
        return QRectF(SHADOW, SHADOW,
                      self.width() - SHADOW * 2, self.height() - SHADOW * 2)

    def paintEvent(self, event):
        if self._plate is None or self._theme_gen != theme.generation():
            self._build_plate()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.drawPixmap(0, 0, self._plate)
        self.paint_content(p)
        p.end()

    def _build_plate(self):
        """玻璃底 + 标题栏分隔线，缓存成一张图。"""
        dpr = self.devicePixelRatioF() or 1.0
        pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)

        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.panel_rect()
        theme.draw_panel(p, rect, radius=TITLE_RADIUS, shadow_spread=18)

        # 标题栏下沿的细线：把"标题"和"内容"分开，但不喧宾夺主
        y = rect.top() + HEADER_H
        p.setPen(theme.rgba(theme.DIVIDER, 0.05 if theme.is_dark() else 0.10))
        p.drawLine(rect.left() + 20, y, rect.right() - 20, y)

        self._paint_title(p, rect)
        p.end()
        self._plate = pm
        self._theme_gen = theme.generation()

    def _paint_title(self, p: QPainter, rect: QRectF):
        """
        标题：小字号 + 放宽字距，像 macOS 的窗口标题。

        注意 drawText(QRectF, ...) 会把文字**裁在矩形内**，
        所以矩形高度必须取 QFontMetricsF.height()，不能凭感觉给。
        中文字形的 ascent 比同字号英文更高，随手给个 14px 会把字顶削掉。
        """
        x = rect.left() + 22
        width = rect.width() - 70

        f_title = theme.font(12.5, 600, 1.6)
        h_title = QFontMetricsF(f_title).height()
        f_sub = theme.font(11, 500, 0.8) if self._subtitle else None
        h_sub = QFontMetricsF(f_sub).height() if f_sub else 0

        # 两行文字在标题栏里整体垂直居中，而不是各自拍一个 y
        gap = 2
        total = h_title + (gap + h_sub if f_sub else 0)
        y = rect.top() + (HEADER_H - total) / 2.0

        p.setFont(f_title)
        p.setPen(theme.rgba(theme.IVORY, 0.92))
        p.drawText(QRectF(x, y, width, h_title),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._title)

        if f_sub:
            p.setFont(f_sub)
            p.setPen(theme.rgba(theme.GOLD, 0.58))
            p.drawText(QRectF(x, y + h_title + gap, width, h_sub),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       self._subtitle)

    def paint_content(self, p: QPainter):
        """给子类留的装饰槽（画在标题之下、内容控件之上）。"""
        pass

    def on_theme_changed(self):
        """子类可以在主题切换后做额外处理（默认什么都不用做）。"""
        pass

    def _on_theme_changed(self):
        """主题切换：换控件皮肤 → 丢缓存底图 → 通知子类 → 重绘。"""
        self.setStyleSheet(theme.window_qss())
        self.btn_close.setStyleSheet(theme.window_qss())
        self._plate = None

        # 子控件里自己 setStyleSheet 过的（剧本编辑器的每一行），也要跟着换
        from PySide6.QtWidgets import QWidget as _QWidget
        for child in self.findChildren(_QWidget):
            if child.objectName() == "EditorRow":
                child.setStyleSheet(theme.row_qss())

        self.on_theme_changed()
        self.update()

    # ------------------------------------------------------------ 交互

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            local = event.position().toPoint()
            if local.y() < SHADOW + HEADER_H:
                self._drag_offset = event.globalPosition().toPoint() - self.pos()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if self._closable_by_esc and event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def showEvent(self, event):
        self._plate = None
        super().showEvent(event)
        self.setWindowOpacity(0.0)
        self._fade.stop()
        self._fade.start()

    # ------------------------------------------------------------ 工具

    def add_widget(self, widget, stretch=0):
        self.body_layout.addWidget(widget, stretch)
        return widget

    def add_stretch(self, stretch=1):
        self.body_layout.addStretch(stretch)


class SectionTitle(QWidget):
    """
    小标题 + 细横线。用于在表单里分组，比 QGroupBox 更轻。
    """

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text
        self.setFixedHeight(24)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setFont(theme.font(10.5, 600, 1.4))
        p.setPen(theme.rgba(theme.GOLD, 0.75))
        p.drawText(QRectF(2, 0, self.width() - 4, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._text)

        from PySide6.QtGui import QFontMetricsF
        w = QFontMetricsF(theme.font(10.5, 600, 1.4)).horizontalAdvance(self._text)
        p.setPen(theme.rgba(theme.DIVIDER, 0.08 if theme.is_dark() else 0.12))
        p.drawLine(int(w) + 12, self.height() // 2,
                   self.width() - 2, self.height() // 2)
        p.end()
