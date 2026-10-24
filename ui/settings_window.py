"""
按键映射设置窗。

分「手柄 / 键盘」两页，每行一个动作：中文名 + 当前按键小图 + 下拉框。
候选项直接扫 assets/input/<device>/ 下的 png 文件名得来，
所以素材换了一套，设置窗自动跟着变。

设计上做了两点改动（v2.0）：
    1. 每行左边补一张真实按键小图 —— 只看英文文件名根本不知道是什么键；
    2. 两页做成"分段控件"而不是系统 Tab，跟整体玻璃风格一致。
"""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QTabWidget, QVBoxLayout, QWidget)

import ui.theme as theme
from ui.frame import GlassWindow
from ui.widgets import get_cached_pixmap
from utils.config_manager import config
from utils.paths import project_root

# 动作清单：中文名 / 说明 / 配置键
ACTIONS = [
    ("启动 · 重置", "发令键", "start_trigger"),
    ("回退一步", "倒带重练", "rollback"),
    ("普通攻击", "轻点", "basic"),
    ("共鸣技能", "E / RT", "skill"),
    ("共鸣解放", "R / LT", "ult"),
    ("跳跃", "", "jump"),
    ("闪避", "", "dodge"),
    ("声骸技能", "", "echo"),
    ("处决 / 核心", "", "execution"),
    ("切换 1 号位", "", "intro_1"),
    ("切换 2 号位", "", "intro_2"),
    ("切换 3 号位", "", "intro_3"),
    ("锁定目标", "", "lock"),
]


class KeyMapRow(QWidget):
    """
    一行映射：名称 / 按键预览 / 下拉框。

    按键预览是关键 —— 素材文件名是 keyboard_a / xbox_button_a 这种，
    玩家选完之后光看名字并不能确认，看到图标才算数。
    """

    def __init__(self, label: str, hint: str, device: str, options: list[str],
                 current: str, parent=None):
        super().__init__(parent)
        self._device = device
        self._folder = os.path.join(str(project_root()), "assets", "input", device)
        self.setFixedHeight(38)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 3, 2, 3)
        layout.setSpacing(8)

        name = QLabel(label)
        name.setFixedWidth(104)
        name.setObjectName("RowName")
        layout.addWidget(name)

        if hint:
            tip = QLabel(hint)
            tip.setFixedWidth(64)
            tip.setObjectName("Hint")
            layout.addWidget(tip)
        else:
            spacer = QLabel("")
            spacer.setFixedWidth(64)
            layout.addWidget(spacer)

        self.preview = QLabel()
        self.preview.setFixedSize(22, 22)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.preview)

        self.combo = QComboBox()
        self.combo.setMinimumHeight(26)
        # 每个下拉框用独立列表，避免为某个动作补的"孤儿值"污染其它下拉框
        opts = list(options)
        if current and current not in opts:
            opts.insert(0, current)     # 配置里的图被删了也要能显示，否则一保存就丢绑定
        self.combo.addItems(opts)
        if current:
            self.combo.setCurrentText(current)
        self.combo.currentTextChanged.connect(self._refresh_preview)
        layout.addWidget(self.combo, 1)

        self._refresh_preview(self.combo.currentText())

    def _refresh_preview(self, filename: str):
        # 按键素材是"白色字形 + 透明底"，直接贴到白底主题上会看不见，
        # 所以永远垫一块深色键帽底板（两种主题都适用，也更像真按键）。
        self.preview.setStyleSheet(
            f"background: {theme.KEYCAP_BG}; border-radius: 6px;")

        pm = get_cached_pixmap(os.path.join(self._folder, f"{filename}.png"))
        if pm is not None and not pm.isNull():
            self.preview.setPixmap(pm.scaled(
                17, 17, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            self.preview.clear()

    def value(self) -> str:
        return self.combo.currentText()


class SettingsWindow(GlassWindow):
    """
    按键映射设置窗。

    保存后发出 config_saved 信号，主控会热重载监听线程的映射表。
    """

    config_saved = Signal()

    CONTENT_W = 470
    CONTENT_H = 596

    def __init__(self):
        super().__init__("按键设置", self.CONTENT_W, self.CONTENT_H,
                         subtitle="键鼠 · 手柄双端映射")
        self.setStyleSheet(theme.window_qss())

        self.rows = {"xbox": [], "keyboard": []}

        # ---- 外观：夜间 / 日间 ----
        # 放最上面，因为它是"整体观感"而不是某个动作的绑定，
        # 而且切完立刻能看见效果（整个窗口会跟着变）。
        look_bar = QWidget()
        look_layout = QHBoxLayout(look_bar)
        look_layout.setContentsMargins(0, 0, 0, 0)
        look_layout.setSpacing(6)

        cap = QLabel("外观")
        cap.setObjectName("Hint")
        look_layout.addWidget(cap)

        self.btn_dark = QPushButton("夜间")
        self.btn_light = QPushButton("日间")
        for btn in (self.btn_dark, self.btn_light):
            btn.setObjectName("Seg")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumWidth(64)
            look_layout.addWidget(btn)

        self.btn_dark.clicked.connect(lambda: self.switch_theme("dark"))
        self.btn_light.clicked.connect(lambda: self.switch_theme("light"))

        look_layout.addStretch(1)
        self.body_layout.addWidget(look_bar)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.body_layout.addWidget(self.tabs, 1)

        self.tabs.addTab(self._build_page("xbox"), "手柄")
        self.tabs.addTab(self._build_page("keyboard"), "键盘")

        # ---- 底部操作条 ----
        foot = QWidget()
        foot_layout = QHBoxLayout(foot)
        foot_layout.setContentsMargins(0, 4, 0, 0)
        foot_layout.setSpacing(10)

        hint = QLabel("保存后立即生效，不用重开游戏")
        hint.setObjectName("Hint")
        foot_layout.addWidget(hint)
        foot_layout.addStretch(1)

        self.btn_save = QPushButton("保存并应用")
        self.btn_save.setObjectName("Primary")
        self.btn_save.setMinimumSize(QSize(120, 34))
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.clicked.connect(self.save_config)
        foot_layout.addWidget(self.btn_save)

        self.body_layout.addWidget(foot)

        self._sync_theme_buttons()

    # ------------------------------------------------------------ 构建

    def _build_page(self, device: str) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 6, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        scroll.setWidget(content)

        col = QVBoxLayout(content)
        col.setContentsMargins(10, 6, 10, 6)
        col.setSpacing(2)

        options = self._scan_available_icons(device)
        if not options:
            warn = QLabel(f"assets/input/{device} 里没有找到任何按键图标。\n"
                          f"检查该目录是否存在、里面是否有 png。")
            warn.setStyleSheet(f"color: {theme.rgba(theme.ALERT, 0.9).name()}; font-size: 12px;")
            col.addWidget(warn)
            col.addStretch(1)
            page_layout.addWidget(scroll)
            return page

        current_map = config.get(f"keymaps.{device}", {})

        for label, hint, key in ACTIONS:
            row = KeyMapRow(label, hint, device, options, current_map.get(key, ""))
            self.rows[device].append((key, row))
            col.addWidget(row)

        col.addStretch(1)
        page_layout.addWidget(scroll)
        return page

    # ------------------------------------------------------------ 主题

    def switch_theme(self, mode: str):
        """
        切夜间 / 日间。

        立刻生效并写进 config，不用等"保存并应用"——
        外观是随手试的东西，要求用户再点一次保存很反直觉。
        """
        theme.apply(mode)
        config.update_setting("settings.theme", theme.current())
        self._sync_theme_buttons()

    def _sync_theme_buttons(self):
        dark = theme.current() == "dark"
        self.btn_dark.setChecked(dark)
        self.btn_light.setChecked(not dark)

    def on_theme_changed(self):
        """GlassWindow 换完皮肤后会回调这里。"""
        self._sync_theme_buttons()

    def _scan_available_icons(self, device: str) -> list[str]:
        """去 assets/input/<device> 文件夹里找所有的按键图。"""
        target = os.path.join(str(project_root()), "assets", "input", device)
        if not os.path.exists(target):
            return []
        try:
            return sorted(f[:-4] for f in os.listdir(target) if f.lower().endswith(".png"))
        except OSError:
            return []

    # ------------------------------------------------------------ 保存

    def save_config(self):
        """遍历两页的所有行，写回配置。"""
        for device, items in self.rows.items():
            for key, row in items:
                value = row.value()
                if value:
                    config.update_setting(f"keymaps.{device}.{key}", value)

        print("💾 双端按键配置已保存！")
        self.config_saved.emit()
        self.close()
