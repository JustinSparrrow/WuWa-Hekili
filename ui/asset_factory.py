"""
素材工坊：从游戏录像里批量裁切角色技能图标。

为什么需要它
------------
技能图标不该靠手工一帧帧截图 —— 慢，而且很难抠准。
正确做法是"区域定义一次，之后反复取图"：把每个动作在画面上的位置框好，
换一份录像只要按 1-8，就能把当前帧对应区域切成图标存进素材目录。

设计
----
镜头画面用一块自绘画布承载：等比居中、四周留深色底板（像播放器）。
框选矩形按主题着色 ——
    1-6 角色专属（普攻/技能/大招/头像/回路…）用**金色**
    7-8 全员通用（协奏值）用**青色**
一眼就能看出哪些图是所有角色共享的，避免把它们错放进角色目录。

和其它窗口一样套 `GlassWindow`：无边框、可整窗拖动、Esc 关闭、跟随主题切换。
"""

from __future__ import annotations

import json
import os
import sys

import cv2
import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QImage, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSlider, QVBoxLayout,
                               QWidget)

import ui.theme as theme
from ui.frame import GlassWindow, SectionTitle
from utils.paths import project_root


# ================================================================ 常量

# 顺序即键盘 1-8 的顺序，改这里要同步 tools/scaffold.py 的 STANDARD_SUBS
# (文件夹名, 文件前缀, 中文描述)
CATEGORIES = [
    ("normal_attack", "normal", "普攻图标"),
    ("jump", "jump", "跳跃图标"),
    ("resonance_skill", "skill", "共鸣技能"),
    ("resonance_liberation", "liberation", "共鸣解放"),
    ("echo", "echo", "声骸技能"),
    ("character", "avatar", "变奏头像"),
    ("forte_circuit", "forte", "共鸣回路"),      # 角色专属
    ("concerto_energy", "concerto", "协奏值"),   # 全员通用，落到 _general
]

WEAPONS = ["sword", "broadblade", "pistols", "gauntlets", "rectifier"]

# 落到 _general 的栏目（所有角色共享的图）
GENERAL_CATEGORIES = {"concerto_energy"}

PREVIEW_PAD = 10          # 画布四周留白，别让画面贴边


def _assets_dir() -> str:
    """素材根目录。打包后资源在 _internal 下，开发时在项目根。"""
    if getattr(sys, "frozen", False):
        exe_root = os.path.dirname(sys.executable)
        internal = os.path.join(exe_root, "_internal")
        if os.path.isdir(os.path.join(internal, "assets")):
            return os.path.join(internal, "assets", "characters")
        return os.path.join(exe_root, "assets", "characters")
    return os.path.join(str(project_root()), "assets", "characters")


def _factory_config() -> str:
    """ROI 配置跟脚本放一起，移动脚本目录不会失效。"""
    if getattr(sys, "frozen", False):
        exe_root = os.path.dirname(sys.executable)
        internal = os.path.join(exe_root, "_internal", "tools", "factory")
        if os.path.isdir(internal):
            return os.path.join(internal, "factory_config.json")
        return os.path.join(exe_root, "tools", "factory", "factory_config.json")
    return os.path.join(str(project_root()), "tools", "factory", "factory_config.json")


# ================================================================ 画面画布


class VideoCanvas(QWidget):
    """
    等比居中的画面 + 框选层。

    和普通 QLabel 放 pixmap 的区别：
        · 自己算缩放和偏移，鼠标坐标能精确反算回**原始视频像素**
        · 框选矩形与画面同层绘制，缩放窗口时框跟着走，不会错位
    """

    roi_drawn = Signal(int, int, int, int)     # 索引, x, y, w, h（原始像素）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(560, 360)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        # 显示用的缩略图（numpy）与它的 QImage 视图。
        # 1440p 原图直接交给 Qt 每帧缩放太贵，所以先 cv2 缩到画布大小再画；
        # QImage 只是包了 _disp 的指针，所以 _disp 必须挂在 self 上保命。
        self._raw: np.ndarray | None = None      # 原始帧（BGR 已转 RGB）
        self._orig_size = (1, 1)
        self._disp: np.ndarray | None = None
        self._img: QImage | None = None
        self._k = 1.0                            # 原图 / 缩略图 的像素比
        self._scale = 1.0                        # 缩略图在控件上的缩放
        self._ox = 0.0
        self._oy = 0.0

        self.rois: dict[int, tuple[int, int, int, int]] = {}
        self._active = -1            # 正在框选的栏目索引
        self._hover = -1             # 鼠标悬停在哪一栏的框上
        self._dragging = False
        self._start = None
        self._cur = None

        # 不按键也要收到 mouseMove，才能做悬停高亮
        self.setMouseTracking(True)

    # ------------------------------------------------------------ 数据

    def set_frame(self, rgb: np.ndarray, orig_w: int, orig_h: int):
        """rgb: 已是 RGB 顺序的 ndarray（cv2 转好的）。"""
        self._raw = rgb
        self._orig_size = (orig_w, orig_h)
        self._rebuild()
        self.update()

    def clear_frame(self):
        self._raw = None
        self._disp = None
        self._img = None
        self.update()

    def _rebuild(self):
        """
        按当前控件尺寸生成缩略图，并算好居中偏移。

        缩放目标封顶在控件大小：再大也画不出更多细节，只会白烧 CPU。
        """
        if self._raw is None:
            self._scale, self._ox, self._oy, self._k = 1.0, 0.0, 0.0, 1.0
            return

        orig_w, orig_h = self._orig_size
        avail_w = max(1, self.width() - PREVIEW_PAD * 2)
        avail_h = max(1, self.height() - PREVIEW_PAD * 2)

        fit = min(avail_w / orig_w, avail_h / orig_h)
        disp_w = max(1, int(orig_w * fit))
        disp_h = max(1, int(orig_h * fit))

        if (self._disp is None or self._disp.shape[1] != disp_w
                or self._disp.shape[0] != disp_h):
            self._disp = cv2.resize(self._raw, (disp_w, disp_h),
                                    interpolation=cv2.INTER_AREA)
            self._img = QImage(self._disp.data, disp_w, disp_h,
                               self._disp.strides[0], QImage.Format.Format_RGB888)

        self._k = orig_w / disp_w
        self._scale = 1.0          # 缩略图已是目标尺寸，直接 1:1 贴
        self._ox = (self.width() - disp_w) / 2.0
        self._oy = (self.height() - disp_h) / 2.0

    def resizeEvent(self, event):
        self._rebuild()
        super().resizeEvent(event)

    # ------------------------------------------------------------ 坐标换算

    def _to_image(self, pt) -> tuple[int, int]:
        """控件坐标 -> 原始视频像素。"""
        if self._raw is None:
            return 0, 0
        x = (pt.x() - self._ox) / self._scale * self._k
        y = (pt.y() - self._oy) / self._scale * self._k
        w, h = self._orig_size
        return int(max(0, min(w, x))), int(max(0, min(h, y)))

    # ------------------------------------------------------------ 框选

    def start_draw(self, index: int):
        """进入框选模式：等用户在画面上拖一个矩形。"""
        if self._raw is None:
            return False
        self._active = index
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()
        return True

    def clear_roi(self, index: int):
        if index in self.rois:
            del self.rois[index]
            self.update()
            return True
        return False

    def mousePressEvent(self, event):
        if self._active >= 0 and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._start = event.position()
            self._cur = self._start
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._cur = event.position()
            self.update()
            event.accept()
            return

        # 悬停到哪个框上，就把那一栏的名称显示出来 —— 平时只留编号，
        # 否则 8 个标签会互相压住（尤其底部那几个挨得很近的小框）。
        hit = -1
        for idx, rect in self._roi_rects().items():
            if rect.contains(event.position()):
                hit = idx
                break
        if hit != self._hover:
            self._hover = hit
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover != -1:
            self._hover = -1
            self.update()
        super().leaveEvent(event)

    def _roi_rects(self) -> dict[int, QRectF]:
        """把原始像素区域换算成控件坐标（绘制和命中检测共用）。"""
        out = {}
        for idx, (x, y, w, h) in self.rois.items():
            out[idx] = QRectF(x / self._k * self._scale + self._ox,
                              y / self._k * self._scale + self._oy,
                              w / self._k * self._scale,
                              h / self._k * self._scale)
        return out

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)

            x1, y1 = self._to_image(self._start)
            x2, y2 = self._to_image(self._cur)
            left, top = min(x1, x2), min(y1, y2)
            w, h = abs(x2 - x1), abs(y2 - y1)

            # 太小的框是手抖，不当真
            if w >= 8 and h >= 8:
                self.rois[self._active] = (left, top, w, h)
                self.roi_drawn.emit(self._active, left, top, w, h)

            self._active = -1
            self._start = self._cur = None
            self.update()
            return
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------ 绘制

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        full = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        plate = theme.squircle(full, 14)
        p.fillPath(plate, QColor(theme.TILE_PLATE))
        p.setClipPath(plate)

        # ---- 画面 ----
        if self._disp is not None and self._img is not None:
            target = QRectF(self._ox, self._oy, self._disp.shape[1], self._disp.shape[0])
            p.drawImage(target, self._img)

        # ---- 已保存的框（原始像素 -> 控件坐标）----
        rects = self._roi_rects()
        for idx, rect in sorted(rects.items()):
            color = theme.CYAN if idx >= 6 else theme.GOLD
            # 名称只在悬停/正在框选时展开，平时缩成一个编号角标
            expanded = (idx == self._hover or idx == self._active)
            self._draw_box(p, rect, color, idx, expanded)

        # ---- 正在拖的框 ----
        if self._dragging and self._start and self._cur:
            rect = QRectF(self._start, self._cur).normalized()
            pen = QPen(theme.rgba(theme.ALERT, 0.95))
            pen.setWidthF(1.6)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(theme.rgba(theme.ALERT, 0.10))
            p.drawRect(rect)

        p.setClipping(False)

        # ---- 画布描边 ----
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(theme.rgba(theme.DIVIDER, 0.10 if theme.is_dark() else 0.14), 1.0))
        p.drawPath(plate)

        # ---- 没画面时给一句提示 ----
        if self._raw is None:
            p.setFont(theme.font(12, 400, 0.6))
            p.setPen(theme.rgba(theme.IVORY, 0.35))
            p.drawText(full, Qt.AlignmentFlag.AlignCenter,
                       "打开一段录像，然后把每个技能在图上的位置框出来")

        p.end()

    def _draw_box(self, p: QPainter, rect: QRectF, color: str,
                  index: int, expanded: bool):
        """
        一个框 + 左上角的编号。

        编号画在框**内部**：底部那几个区域挨得很近，标签放外面必然互相压住。
        名称平时收起，鼠标移上去才展开成完整标签。
        """
        pen = QPen(theme.rgba(color, 0.92))
        pen.setWidthF(1.6)
        p.setPen(pen)
        p.setBrush(theme.rgba(color, 0.08))
        p.drawRect(rect)

        label = (f"[{index + 1}] {CATEGORIES[index][2]}" if expanded
                 else str(index + 1))

        f = theme.font(10 if expanded else 9.5, 600, 0.4)
        fm = QFontMetricsF(f)
        tw = fm.horizontalAdvance(label) + (10 if expanded else 8)
        th = fm.height() + 4

        # 框足够大就贴在内部左上角，太小就翻到框上方
        if rect.width() >= tw + 6 and rect.height() >= th + 4:
            tag = QRectF(rect.left() + 2, rect.top() + 2, tw, th)
        else:
            tag = QRectF(rect.left(), rect.top() - th - 1, tw, th)
            if tag.top() < 0:
                tag.moveTop(rect.top() + 2)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.rgba(theme.BADGE_BG, 0.88))
        p.drawPath(theme.squircle(tag, 4))

        p.setFont(f)
        p.setPen(theme.rgba(color, 0.98))
        p.drawText(tag, Qt.AlignmentFlag.AlignCenter, label)


# ================================================================ 栏目行


class CategoryRow(QWidget):
    """
    一行 "编号 + 名称 + 状态"。

    自己画而不是 QPushButton，是为了让 8 行挤得下、并且状态（已框/未框）
    能直接写在行尾，不用再摆一个标签。
    """

    clicked = Signal(int)
    cleared = Signal(int)

    def __init__(self, index: int, name: str, parent=None):
        super().__init__(parent)
        self._index = index
        self._name = name
        self._has_roi = False
        self._hover = 0.0
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_has_roi(self, value: bool):
        if value != self._has_roi:
            self._has_roi = value
            self.update()

    def enterEvent(self, event):
        self._hover = 1.0
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = 0.0
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.rect().contains(event.position().toPoint()):
            if event.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit(self._index)
            elif event.button() == Qt.MouseButton.RightButton and self._has_roi:
                self.cleared.emit(self._index)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(0, 1, -1, -2)
        if self._hover > 0.01:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.rgba(theme.GOLD, 0.09 * self._hover))
            p.drawPath(theme.squircle(rect, 9))

        # 编号徽章
        badge = QRectF(3, (self.height() - 18) / 2.0, 18, 18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.rgba(theme.GOLD, 0.16))
        p.drawPath(theme.squircle(badge, 5.5))
        p.setFont(theme.font(9.5, 600))
        p.setPen(theme.rgba(theme.GOLD, 0.95))
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(self._index + 1))

        # 名称
        p.setFont(theme.font(11.5, 500, 0.3))
        p.setPen(theme.rgba(theme.IVORY, 0.86 if self._has_roi else 0.55))
        p.drawText(QRectF(29, 0, rect.width() - 90, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._name)

        # 状态
        text = "已框选" if self._has_roi else "点击框选"
        color = theme.GOLD if self._has_roi else theme.TEXT_FAINT
        p.setFont(theme.font(10, 500, 0.4))
        p.setPen(theme.rgba(color, 0.85 if self._has_roi else 0.55))
        p.drawText(QRectF(rect.width() - 76, 0, 74, self.height()),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   text)

        p.end()


# ================================================================ 主窗口


class AssetFactoryWindow(GlassWindow):
    """素材工坊窗口。"""

    CONTENT_W = 1360
    CONTENT_H = 700

    def __init__(self):
        super().__init__("素材工坊", self.CONTENT_W, self.CONTENT_H,
                         subtitle="从录像里裁切技能图标 · 按 1-8 取图")
        self.setStyleSheet(theme.window_qss())

        self.assets_dir = _assets_dir()
        self.config_path = _factory_config()

        self.cap = None
        self.is_playing = False
        self.orig_frame = None
        self._ref_size: tuple[int, int] | None = None   # 框选时的视频尺寸

        self.char_weapons: dict[str, str] = {}
        self.config: dict = {"rois": {}}
        self._log_text = ""
        self._log_kind = "info"

        self._load_character_mapping()
        self._build()               # canvas / 下拉框都在这一步创建
        self._load_config()         # 再读区域配置（要用到 canvas）
        self._setup_timer()
        self._refresh_roi_rows()
        self._apply_log_style()

    # ------------------------------------------------------------ 构建

    def _build(self):
        row = QHBoxLayout()
        row.setSpacing(16)

        # ---------- 左：画面 ----------
        left = QVBoxLayout()
        left.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_open = QPushButton("打开视频")
        self.btn_open.setObjectName("Primary")
        self.btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open.setMinimumWidth(104)
        self.btn_open.clicked.connect(self.load_video)

        self.btn_play = QPushButton("暂停")
        self.btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play.setMinimumWidth(64)
        self.btn_play.setEnabled(False)
        self.btn_play.clicked.connect(self.toggle_play)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setEnabled(False)
        self.slider.sliderMoved.connect(self.seek_video)

        bar.addWidget(self.btn_open)
        bar.addWidget(self.btn_play)
        bar.addWidget(self.slider, 1)
        left.addLayout(bar)

        self.canvas = VideoCanvas()
        self.canvas.roi_drawn.connect(self.on_roi_drawn)
        left.addWidget(self.canvas, 1)

        hint = QLabel("视频暂停时按 1-8 直接取图；右键色块可清除该区域")
        hint.setObjectName("Hint")
        left.addWidget(hint)

        row.addLayout(left, 1)

        # ---------- 右：表单 ----------
        right = QVBoxLayout()
        right.setSpacing(8)

        right.addWidget(SectionTitle("1 · 角色"))
        self.combo_char = QComboBox()
        self.combo_char.addItems(sorted(self.char_weapons.keys()))
        right.addWidget(self.combo_char)

        new_row = QHBoxLayout()
        new_row.setSpacing(6)
        self.edit_new_char = QLineEdit()
        self.edit_new_char.setPlaceholderText("英文名，如 Jinhsi")
        self.combo_weapon = QComboBox()
        self.combo_weapon.addItems(WEAPONS)
        self.combo_weapon.setMinimumWidth(104)
        new_row.addWidget(self.edit_new_char, 1)
        new_row.addWidget(self.combo_weapon)
        right.addLayout(new_row)

        self.btn_add_char = QPushButton("添加角色")
        self.btn_add_char.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_char.clicked.connect(self.add_character)
        right.addWidget(self.btn_add_char)

        right.addSpacing(6)
        right.addWidget(SectionTitle("2 · 截取区域"))
        self.rows: list[CategoryRow] = []
        for i, (_folder, _prefix, desc) in enumerate(CATEGORIES):
            r = CategoryRow(i, desc)
            r.clicked.connect(self.start_draw)
            r.cleared.connect(self.clear_roi)
            self.rows.append(r)
            right.addWidget(r)

        right.addSpacing(6)
        right.addWidget(SectionTitle("3 · 状态"))
        self.lbl_log = QLabel("等待操作…")
        self.lbl_log.setWordWrap(True)
        self.lbl_log.setMinimumHeight(52)
        self.lbl_log.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        right.addWidget(self.lbl_log)

        right.addStretch(1)

        holder = QWidget()
        holder.setLayout(right)
        holder.setFixedWidth(330)
        row.addWidget(holder)

        self.body_layout.addLayout(row)

    def _setup_timer(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame)

    # ------------------------------------------------------------ 配置读写

    def _load_character_mapping(self):
        os.makedirs(self.assets_dir, exist_ok=True)
        path = os.path.join(self.assets_dir, "Character_Occupation.txt")
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    char, weapon = line.split("=", 1)
                    self.char_weapons[char.strip()] = weapon.strip()

    def _load_config(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except (OSError, ValueError):
            self.config = {"rois": {}}

        # 键在 JSON 里是字符串，统一转回 int
        raw = self.config.get("rois", {}) or {}
        rois = {}
        for k, v in raw.items():
            try:
                idx = int(k)
                x, y, w, h = (int(n) for n in v)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(CATEGORIES):
                rois[idx] = (x, y, w, h)
        self.canvas.rois = rois
        self._ref_size = tuple(self.config["ref_size"]) if self.config.get("ref_size") else None

    def _save_config(self):
        self.config["rois"] = {str(k): list(v) for k, v in self.canvas.rois.items()}
        if self._ref_size:
            self.config["ref_size"] = list(self._ref_size)
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False)

    def _refresh_roi_rows(self):
        for i, r in enumerate(self.rows):
            r.set_has_roi(i in self.canvas.rois)

    # ------------------------------------------------------------ 区域

    def start_draw(self, index: int):
        if not self.canvas.start_draw(index):
            self.log("先打开一段录像，才能框选区域。", "err")
            return
        self.log(f"在第 {index + 1} 栏「{CATEGORIES[index][2]}」上拖一个矩形。")

    def clear_roi(self, index: int):
        if self.canvas.clear_roi(index):
            self._save_config()
            self._refresh_roi_rows()
            self.log(f"已清除第 {index + 1} 栏的区域。")

    def on_roi_drawn(self, index: int, x: int, y: int, w: int, h: int):
        self._save_config()
        self._refresh_roi_rows()
        self.log(f"区域已保存：[{index + 1}] {CATEGORIES[index][2]}  {w}×{h}")

    # ------------------------------------------------------------ 视频

    def load_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择录像", "", "Video (*.mp4 *.mkv *.avi *.mov)")
        if not path:
            return

        if self.cap is not None:
            self.cap.release()

        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            self.log("这段视频打不开，换一个格式试试。", "err")
            self.cap = None
            return

        total = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.slider.setRange(0, max(1, total))
        self.slider.setEnabled(True)
        self.btn_play.setEnabled(True)

        self.is_playing = True
        self.btn_play.setText("暂停")
        self.timer.start(33)
        self.log(f"已加载：{os.path.basename(path)}（{total} 帧）")

    def toggle_play(self):
        if self.cap is None:
            return
        self.is_playing = not self.is_playing
        self.btn_play.setText("暂停" if self.is_playing else "播放")

    def seek_video(self, pos: int):
        if self.cap is None:
            return
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        self.next_frame(force=True)

    def next_frame(self, force: bool = False):
        if self.cap is None or not (self.is_playing or force):
            return

        ok, frame = self.cap.read()
        if not ok:
            self.is_playing = False
            self.btn_play.setText("播放")
            return

        self.orig_frame = frame
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]

        # 换了分辨率就把已存的框等比缩过去，免得一张 1080p 录像让框全错位
        self._rescale_rois_if_needed(w, h)

        self.canvas.set_frame(rgb, w, h)

        if not force:
            self.slider.blockSignals(True)
            self.slider.setValue(int(self.cap.get(cv2.CAP_PROP_POS_FRAMES)))
            self.slider.blockSignals(False)

    def _rescale_rois_if_needed(self, w: int, h: int):
        """
        框是按某个分辨率的像素存的。换分辨率后按比例缩放一次，然后记住新基准。

        不做这一步的话，用 1080p 录像框出来的区域裁 1440p 会整体偏，
        而用户很难判断是"框错了"还是"分辨率变了"。
        """
        if not self.canvas.rois:
            self._ref_size = (w, h)
            return
        if self._ref_size is None:
            self._ref_size = (w, h)
            return
        rw, rh = self._ref_size
        if rw == w and rh == h:
            return

        sx, sy = w / rw, h / rh
        self.canvas.rois = {
            i: (int(x * sx), int(y * sy), int(bw * sx), int(bh * sy))
            for i, (x, y, bw, bh) in self.canvas.rois.items()
        }
        self._ref_size = (w, h)
        self._save_config()
        self.canvas.update()
        self.log(f"录像分辨率变了（{rw}×{rh} → {w}×{h}），区域已按比例重算。")

    # ------------------------------------------------------------ 取图

    def keyPressEvent(self, event):
        key = event.key()

        if key == Qt.Key.Key_Space:
            self.toggle_play()
            return

        # Esc 交给 GlassWindow 关闭窗口
        if key == Qt.Key.Key_Escape:
            super().keyPressEvent(event)
            return

        if Qt.Key.Key_1 <= key <= Qt.Key.Key_8:
            self._capture(key - Qt.Key.Key_1)
            return

        super().keyPressEvent(event)

    def _capture(self, index: int):
        if self.orig_frame is None:
            self.log("先打开录像并暂停到想要的那一帧。", "err")
            return
        if index not in self.canvas.rois:
            self.log(f"第 {index + 1} 栏还没框选过。先用鼠标点它，然后在画面上拖一个框。", "err")
            return

        char_name = self.combo_char.currentText().strip()
        if not char_name:
            self.log("先在上面选一个角色，或者填名字添加一个。", "err")
            return

        folder, prefix, _desc = CATEGORIES[index]
        x, y, w, h = self.canvas.rois[index]

        fh, fw = self.orig_frame.shape[:2]
        x, y = max(0, x), max(0, y)
        w, h = min(w, fw - x), min(h, fh - y)
        if w <= 0 or h <= 0:
            self.log("这个框落在画面外面了，重新框一次。", "err")
            return
        crop = self.orig_frame[y:y + h, x:x + w]

        if folder in GENERAL_CATEGORIES:
            save_dir = os.path.join(self.assets_dir, "_general", folder)
        else:
            save_dir = os.path.join(self.assets_dir, char_name, folder)
        os.makedirs(save_dir, exist_ok=True)

        # 自动编号：forte.png / forte_2.png / forte_3.png…
        n = 1
        while True:
            filename = f"{prefix}.png" if n == 1 else f"{prefix}_{n}.png"
            save_path = os.path.join(save_dir, filename)
            if not os.path.exists(save_path):
                break
            n += 1

        cv2.imwrite(save_path, crop)
        rel = os.path.relpath(save_path, self.assets_dir)
        self.log(f"已保存  {rel}   （{w}×{h}）")

    # ------------------------------------------------------------ 角色

    def add_character(self):
        name = self.edit_new_char.text().strip()
        if not name:
            self.log("先填一个英文名，比如 Jinhsi。", "err")
            return
        if name in self.char_weapons:
            self.log(f"「{name}」已经在列表里了。", "err")
            return

        weapon = self.combo_weapon.currentText()
        self.char_weapons[name] = weapon

        # 这个文件是 wiki_spider 生成的，只能追加，不能重写
        path = os.path.join(self.assets_dir, "Character_Occupation.txt")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n{name}={weapon}")

        self.combo_char.addItem(name)
        self.combo_char.setCurrentText(name)
        self.edit_new_char.clear()
        self.log(f"已添加角色：{name}（{weapon}）")

    # ------------------------------------------------------------ 提示

    def log(self, text: str, kind: str = "ok"):
        self._log_text = text
        self._log_kind = kind
        self._apply_log_style()

    def _apply_log_style(self):
        color = {"ok": theme.GOLD, "err": theme.ALERT}.get(self._log_kind, theme.TEXT_DIM)
        self.lbl_log.setText(self._log_text or "等待操作…")
        self.lbl_log.setStyleSheet(
            f"color: {theme.qa(color, 0.92)};"
            f" background: {theme.qa(theme.CARD_BG, 0.05 if theme.is_dark() else 0.04)};"
            f" border-radius: 9px; padding: 8px 10px; font-size: 11px;")

    def on_theme_changed(self):
        """视频画布上的框是自绘的，主题一换要重上色。"""
        self._apply_log_style()
        self.canvas.update()

    def closeEvent(self, event):
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.timer.stop()
        super().closeEvent(event)


# ================================================================ 独立运行


def main():
    """`python tools/factory/asset_factory_gui.py` 走这里。"""
    from PySide6.QtWidgets import QApplication

    root = str(project_root())
    if root not in sys.path:
        sys.path.insert(0, root)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    app.setFont(theme.font(13))
    theme.apply("dark")

    win = AssetFactoryWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
