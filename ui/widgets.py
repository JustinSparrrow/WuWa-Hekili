"""
可复用控件：悬浮窗技能格（ActionWidget）、剧本编辑器行（ActionEditorRow）。

ActionWidget 是整份 UI 里唯一"每帧都可能重画"的控件，所有绘制逻辑
都按这个前提写：
    · 不建子控件，不解析 QSS，全部 QPainter 直接画
    · 图标不在每帧重采样成中间 QPixmap，直接用画笔变换绘制
    · 只有"当前格"才画外阴影和柔光，其余格省掉
"""

from __future__ import annotations

import math
import os

from PySide6.QtCore import (Property, QEasingCurve, QPointF, QRectF, Qt,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import ui.theme as theme
from utils.character_meta import element_of

# ============================================================
# 图片缓存：路径 -> QPixmap
# ============================================================
# QPixmap 从磁盘加载要解 PNG，悬浮窗在连招高频推进时会反复请求同样几张图，
# 所以保留一份进程级缓存，命中后不再读盘。
# 容量估算：一张 100x100 的 ARGB 图约 40KB，300 张约 12MB，可接受；
# 超出上限直接整体清空（不做 LRU），逻辑简单且极少触发。
_PIXMAP_CACHE = {}
_PIXMAP_CACHE_LIMIT = 300


def get_cached_pixmap(path):
    """
    按路径取 QPixmap，带缓存。

    :return: QPixmap；路径为空时返回 None（加载失败会返回 isNull() 为 True 的空图）
    """
    if not path:
        return None

    pm = _PIXMAP_CACHE.get(path)
    if pm is None:
        pm = QPixmap(path)
        if len(_PIXMAP_CACHE) >= _PIXMAP_CACHE_LIMIT:
            _PIXMAP_CACHE.clear()
        _PIXMAP_CACHE[path] = pm
    return pm


def clear_pixmap_cache():
    """素材更新后可调用，释放已缓存的图片。"""
    _PIXMAP_CACHE.clear()


# ============================================================
# ActionWidget：悬浮窗里的一格
# ============================================================

# 格子外沿留白：给描边柔光、抖动反馈留出空间，否则会被控件边界切掉
_PAD = 5


class ActionWidget(QWidget):
    """
    一格技能提示。

    视觉分层（由下往上）
    -------------------
        外阴影(仅当前格) → 墨黑玻璃底 → 技能图标 → 底部压暗 → 描边/进度环
        → 右下角按键帽 → 左上角手势角标

    「当前格」和其余格的区别不只是大小：
        当前格：金色描边 + 柔光 + 外阴影 + 环形进度 + 手势角标
        预告格：细描边 + 半透明
        历史格：更暗、更小、不显示按键帽（它已经按过了，不需要再提示键位）
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 鼠标事件让给主窗：整块面板随处都能拖动
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._data = {}
        self._tier = "far"          # current / next / far / history
        self._variant = ""
        self._is_current = False
        self._parallel = False

        self._icon_path = None
        self._icon_pm = None
        self._btn_path = None
        self._btn_pm = None

        self._gate = 0.0            # 动作占位剩余比例 1→0（0 = 可以按了）
        self._flash = ""            # "" / "hold" / "tap"
        self._fx = 0.0              # 抖动衰减 1→0
        self._burst = 0.0           # 激活波纹 1→0

        # 自己维护不透明度，而不是套 QGraphicsOpacityEffect。
        # 原因：后者会把每一格先渲染到离屏 pixmap 再合成，
        # 连招时 4~5 格每秒 60 帧全都在做这件事；而且离屏合成会让
        # QWidget.render()（截图工具用）算错子控件偏移。
        self._opacity = 1.0

        # 两个轻量动画对象常驻复用（不要每次闪红都 new）
        self._fx_anim = QVariantAnimation(self)
        self._fx_anim.setDuration(300)
        self._fx_anim.setStartValue(1.0)
        self._fx_anim.setEndValue(0.0)
        self._fx_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fx_anim.valueChanged.connect(self._on_fx)

        self._burst_anim = QVariantAnimation(self)
        self._burst_anim.setDuration(620)
        self._burst_anim.setStartValue(1.0)
        self._burst_anim.setEndValue(0.0)
        self._burst_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._burst_anim.valueChanged.connect(self._on_burst)

    # ------------------------------------------------------------ 不透明度

    def get_opacity(self) -> float:
        return self._opacity

    def set_opacity(self, value: float):
        """推进动画会对这个属性做插值，所以变化超过阈值才重绘。"""
        value = max(0.0, min(1.0, float(value)))
        if abs(value - self._opacity) < 0.004:
            return
        self._opacity = value
        self.update()

    # Qt 属性名就叫 opacity，QPropertyAnimation(b"opacity") 才能驱动它
    opacity = Property(float, get_opacity, set_opacity)

    # ------------------------------------------------------------ 数据

    def set_data(self, data):
        """
        填入一格的数据并刷新显示。

        :param data: Director.get_visual_data() 产出的槽位字典
        """
        self._data = data or {}

        icon_path = self._data.get("icon_path")
        if icon_path != self._icon_path:
            self._icon_path = icon_path
            self._icon_pm = get_cached_pixmap(icon_path)

        btn_path = self._data.get("btn_path")
        if btn_path != self._btn_path:
            self._btn_path = btn_path
            self._btn_pm = get_cached_pixmap(btn_path)

        self.update()

    def update_style(self, variant=None, is_current=False, parallel_hint=False,
                     tier=None):
        """
        更新描边样式与层级。

        :param variant:       动作变体（含 heavy 时描边转暖橙）
        :param is_current:    是否是"现在该按"的那一格
        :param parallel_hint: 是否是"可以趁当前动作没结束就先按"的格
        :param tier:          current / next / far / history；不传则按 is_current 推断
        """
        self._variant = (variant or "").lower()
        self._is_current = is_current
        self._parallel = parallel_hint
        self._tier = tier or ("current" if is_current else "next")
        self.update()

    def set_gate_progress(self, ratio):
        """
        更新"这一步还要占位多久"。

        :param ratio: 剩余比例 1.0 → 0.0。0 表示动作已结束、可以按了。
        """
        ratio = 0.0 if ratio < 0 else (1.0 if ratio > 1 else ratio)

        # 抖动抑制：变化不到 2% 就不重画，避免 30Hz 心跳白白触发绘制
        if abs(ratio - self._gate) < 0.02 and not (ratio <= 0 < self._gate):
            return
        self._gate = ratio
        self.update()

    # ------------------------------------------------------------ 反馈动画

    def flash_reject(self, reason=""):
        """
        键按对了、但"按的时间不对"时闪一下红边并抖一下。

        场景：提示是重击（长按），玩家轻点了一下攻击键。
        不推进（否则普攻/重击就分不开了），但必须有反馈，
        否则玩家会以为"按了没反应，程序卡了"。

        :param reason: "hold" 该长按没按够 / "tap" 该轻按按太久
        """
        self._flash = "hold" if reason == "hold" else "tap"
        self._fx_anim.stop()
        self._fx_anim.start()

    def set_activated_style(self):
        """启动瞬间在当前格放一圈金色波纹，提示"脚本已激活"。"""
        self._burst_anim.stop()
        self._burst_anim.start()

    def _on_fx(self, value):
        self._fx = float(value)
        if self._fx <= 0.001:
            self._flash = ""
        self.update()

    def _on_burst(self, value):
        self._burst = float(value)
        self.update()

    # ------------------------------------------------------------ 绘制

    def _accent(self):
        """这一步的强调色：按错 > 并行 > 重击 > 金色。"""
        if self._flash:
            return QColor(theme.ALERT)
        if self._parallel and not self._is_current:
            return QColor(theme.CYAN)
        if "heavy" in self._variant:
            return QColor(theme.AMBER)
        return QColor(theme.GOLD)

    def _visual_rect(self) -> QRectF:
        """真正作画的区域（外沿留白给柔光），并叠加抖动偏移。"""
        pad = _PAD if min(self.width(), self.height()) >= 40 else 2
        rect = QRectF(self.rect()).adjusted(pad, pad, -pad, -pad)
        if self._fx > 0.001:
            rect.translate(math.sin(self._fx * math.pi * 6.0) * 3.4 * self._fx, 0)
        return rect

    def paintEvent(self, event):
        rect = self._visual_rect()
        if rect.width() < 6 or rect.height() < 6:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.setOpacity(self._opacity)

        size = rect.width()
        radius = size * (0.30 if self._is_current else 0.27)
        path = theme.squircle(rect, radius)
        accent = self._accent()

        # ---------------- 外阴影（只给"马上要看"的格，省开销） ----------------
        if self._tier in ("current", "next"):
            theme.draw_shadow(p, rect, radius, spread=7,
                              alpha=90 if self._is_current else 55)

        # ---------------- 底板 + 图标 ----------------
        p.save()
        p.setClipPath(path)
        p.fillPath(path, QColor(theme.TILE_PLATE))

        if self._icon_pm is not None and not self._icon_pm.isNull():
            self._draw_cover(p, self._icon_pm, rect)
        else:
            self._draw_placeholder(p, rect)
        p.restore()

        # ---------------- 底部压暗（保证按键帽可读） ----------------
        p.save()
        p.setClipPath(path)
        from PySide6.QtGui import QLinearGradient
        grad = QLinearGradient(rect.bottomLeft(), QPointF(rect.left(), rect.top()))
        grad.setColorAt(0.0, QColor(0, 0, 0, 150))
        grad.setColorAt(0.42, QColor(0, 0, 0, 0))
        p.fillPath(path, grad)

        # 历史格整体压暗，视线自然落在当前格上
        if self._tier == "history":
            p.fillPath(path, QColor(0, 0, 0, 110))
        p.restore()

        # ---------------- 描边 / 环形进度 ----------------
        if self._is_current:
            progress = None if self._gate <= 0.001 else max(0.0, 1.0 - self._gate)
            theme.draw_gold_ring(p, rect, radius, width=2.2, color=accent,
                                 progress=progress, glow=True, metal=True)
        else:
            width = 1.4 if self._parallel else 1.0
            alpha = 0.55 if self._parallel else (0.16 if self._tier == "history" else 0.26)
            theme.draw_gold_ring(p, rect, radius, width=width,
                                 color=accent, alpha=alpha)

        # ---------------- 激活波纹 ----------------
        if self._burst > 0.001:
            grow = (1.0 - self._burst) * 16.0
            pen = QPen(theme.rgba(theme.GOLD_HI, 0.55 * self._burst))
            pen.setWidthF(2.0)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(theme.squircle(rect.adjusted(-grow, -grow, grow, grow), radius + grow))

        # ---------------- 按键帽 ----------------
        if self._tier != "history":
            self._draw_keycap(p, rect)

        # ---------------- 手势角标 ----------------
        self._draw_badge(p, rect, accent)

        p.end()

    # -------------------------------------------------- 绘制细节

    @staticmethod
    def _draw_cover(p: QPainter, pm: QPixmap, rect: QRectF):
        """按较长边铺满绘制（居中裁切），不生成中间 QPixmap。"""
        if pm.width() <= 0 or pm.height() <= 0:
            return
        scale = max(rect.width() / pm.width(), rect.height() / pm.height())
        p.save()
        p.translate(rect.center())
        p.scale(scale, scale)
        p.drawPixmap(QPointF(-pm.width() / 2.0, -pm.height() / 2.0), pm)
        p.restore()

    def _draw_placeholder(self, p: QPainter, rect: QRectF):
        """没有素材时退化成"文字方块"，保证玩家仍能看出这一步是什么。"""
        desc = self._data.get("desc", "")
        action_type = self._data.get("type", "")
        if action_type == "execution" or "处决" in desc:
            text = "F"
        elif action_type == "dodge" or "闪" in desc:
            text = "闪"
        elif action_type == "jump" or "跳" in desc:
            text = "跳"
        elif desc == "START":
            text = "起"        # 轴还没开始，历史位只有这个占位
        else:
            text = desc[:1] if desc else "?"

        p.setPen(theme.rgba(theme.IVORY, 0.55))
        p.setFont(theme.font(rect.width() * 0.40, 600))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_keycap(self, p: QPainter, rect: QRectF):
        """右下角按键帽：深色小方块 + 按键图标。"""
        size = rect.width()
        ksize = max(13.0, min(24.0, size * 0.30))
        inset = max(2.5, size * 0.045)
        krect = QRectF(rect.right() - ksize - inset,
                       rect.bottom() - ksize - inset, ksize, ksize)

        p.setBrush(theme.rgba(theme.KEYCAP_BG, 0.82 if theme.is_dark() else 0.92))
        pen = QPen(theme.rgba(theme.KEYCAP_EDGE, 0.20 if theme.is_dark() else 0.35))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(theme.squircle(krect, ksize * 0.34))

        if self._btn_pm is not None and not self._btn_pm.isNull():
            inner = krect.adjusted(ksize * 0.16, ksize * 0.16, -ksize * 0.16, -ksize * 0.16)
            p.save()
            p.setOpacity(0.95)
            scale = min(inner.width() / self._btn_pm.width(),
                        inner.height() / self._btn_pm.height())
            p.translate(inner.center())
            p.scale(scale, scale)
            p.drawPixmap(QPointF(-self._btn_pm.width() / 2.0,
                                 -self._btn_pm.height() / 2.0), self._btn_pm)
            p.restore()
        else:
            p.setPen(QPen(theme.rgba(theme.IVORY, 0.55), 1.2))
            p.drawPoint(krect.center())

    def _draw_badge(self, p: QPainter, rect: QRectF, accent: QColor):
        """
        左上角角标。只在小尺寸以上才画 —— 44px 的格子里塞字等于没字。

        三种来源：按错反馈 > 需要长按 > 处决。
        """
        if self._flash:
            text, color = ("长按" if self._flash == "hold" else "轻按"), theme.ALERT
        elif self._data.get("press_mode") == "hold":
            text = "重击" if "heavy" in self._variant else "长按"
            color = theme.AMBER
        elif "forte" in self._variant:
            text, color = "处决", theme.GOLD
        else:
            return

        if rect.width() < 46:
            return

        f = theme.font(10, 600, 0.4)
        fm = QFontMetricsF(f)
        w = fm.horizontalAdvance(text) + 9
        h = 14.0
        brect = QRectF(rect.left() + 3.0, rect.top() + 3.0, w, h)

        tint = QColor(color)
        p.setBrush(theme.rgba(theme.BADGE_BG, 0.80 if theme.is_dark() else 0.90))
        pen = QPen(theme.rgba(tint.name(), 0.55))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(theme.squircle(brect, 4.5))

        p.setFont(f)
        p.setPen(tint)
        p.drawText(brect, Qt.AlignmentFlag.AlignCenter, text)


# ============================================================
# ActionEditorRow：剧本编辑器的每一行
# ============================================================
class ActionEditorRow(QWidget):
    """
    序号 + 图标预览 + 动作名 + 图标下拉框。

    用户在编辑器里为每一步挑选具体用哪张 png，选择结果写回剧本 JSON 的
    `custom_icon` 字段。
    """

    image_changed = Signal(int, str)

    def __init__(self, index, action_data, char_name, asset_mgr, parent=None):
        super().__init__(parent)
        self.index = index
        self.action_data = action_data
        self.char_name = char_name
        self.asset_mgr = asset_mgr
        self.current_search_path = ""

        self.setObjectName("EditorRow")
        # 皮肤放在 theme.row_qss() 里，跟着主题切换走；这里只管结构
        self.setStyleSheet(theme.row_qss())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(10)

        self.lbl_idx = QLabel(f"{index + 1:02d}")
        self.lbl_idx.setFixedWidth(26)
        self.lbl_idx.setObjectName("RowIdx")
        self.lbl_idx.setStyleSheet(
            f"color: {theme.qa(theme.GOLD, 0.75)}; font-weight: 600;"
            f" background: transparent; font-size: 11px;")
        layout.addWidget(self.lbl_idx)

        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(38, 38)
        self.icon_preview.setScaledContents(True)
        layout.addWidget(self.icon_preview)

        desc_text = action_data['desc'] + (f"  ·  {char_name}" if char_name else "")
        self.lbl_desc = QLabel(desc_text)
        layout.addWidget(self.lbl_desc, 1)

        self.combo_img = QComboBox()
        self.combo_img.setFixedWidth(190)
        self.combo_img.addItems(self._get_all_options())

        current_path = asset_mgr.get_icon_path(
            char_name,
            action_data["type"],
            action_data.get("variant"),
            action_data.get("force_general", False),
            action_data.get("custom_icon")
        )

        pixmap = get_cached_pixmap(current_path)
        if pixmap is not None and not pixmap.isNull():
            self.combo_img.setCurrentText(os.path.basename(current_path))
            self._set_preview(pixmap)
        else:
            self.combo_img.setCurrentText("None")
            self._set_placeholder()

        self.combo_img.currentTextChanged.connect(self._on_change)
        layout.addWidget(self.combo_img)

    # -------------------------------------------------- 预览

    def _set_preview(self, pixmap):
        self.icon_preview.setStyleSheet("background: transparent; border-radius: 8px;")
        self.icon_preview.setPixmap(
            pixmap.scaled(self.icon_preview.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                          Qt.TransformationMode.SmoothTransformation))

    def _set_placeholder(self):
        self.icon_preview.clear()
        self.icon_preview.setText(self._fallback_text())
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_preview.setStyleSheet(
            f"color: {theme.qa(theme.IVORY, 0.65)}; background: {theme.qa(theme.DIVIDER, 0.06)};"
            " font-size: 11px; font-weight: 600; border-radius: 8px;")

    def _fallback_text(self):
        action_type = self.action_data.get("type", "ACT")
        if action_type == "execution":
            return "处决"
        if action_type == "dodge":
            return "闪"
        if action_type == "jump":
            return "跳"
        return action_type[:3].upper()

    def _get_all_options(self):
        """扫描候选文件夹，返回可选图片名列表，并记录路径供后续拼接。"""
        action_type = self.action_data["type"]
        folder_name = self.asset_mgr.folder_map.get(action_type, action_type)

        if self.action_data.get("force_general"):
            weapon = self.asset_mgr.weapon_map.get(self.char_name, "sword")
            path = os.path.join(self.asset_mgr.path, "_general", "normal_attack", weapon)
        else:
            path = os.path.join(self.asset_mgr.path, self.char_name, folder_name)

        # 降级逻辑（必须与 AssetManager._resolve_icon 保持一致）
        if not os.path.exists(path):
            variant = self.action_data.get("variant") or ""
            if "heavy" in action_type or "heavy" in variant.lower():
                path = os.path.join(self.asset_mgr.path, self.char_name, "normal_attack")
            elif action_type == "execution" or "forte" in variant.lower():
                path = os.path.join(self.asset_mgr.path, self.char_name, "resonance_skill")

        self.current_search_path = path

        if not os.path.exists(path):
            return ["None"]
        try:
            files = [f for f in os.listdir(path) if f.lower().endswith('.png')]
            return sorted(files) if files else ["None"]
        except OSError:
            return ["None"]

    def _on_change(self, filename):
        """用户在下拉框里换图时，实时更新预览并通知外层。"""
        if filename == "None":
            self._set_placeholder()
        else:
            new_path = os.path.join(self.current_search_path, filename)
            pixmap = get_cached_pixmap(new_path)
            if pixmap is not None and not pixmap.isNull():
                self._set_preview(pixmap)

        self.image_changed.emit(self.index, filename)

    def get_selected_filename(self):
        return self.combo_img.currentText()
