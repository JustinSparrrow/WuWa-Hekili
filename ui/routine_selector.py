"""
剧本选择窗：列出 configs/routines/ 下所有连招流程。

两个入口：
    启动流程     把 json 路径发给主控，进入实战提示
    查看 / 修改  把路径发给流程编辑器，回填后可改图重存

每一行除了文件名，还显示两条轴各有多少步 —— 选轴时最想知道的就是
"这条轴有多长、要不要练"，而不是文件名里那几个字。
"""

from __future__ import annotations

import json
import os

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

import ui.theme as theme
from ui.frame import GlassWindow
from utils.paths import project_root

_META_ROLE = Qt.ItemDataRole.UserRole + 1


class _RoutineDelegate(QStyledItemDelegate):
    """自绘列表项：轴名一行、步数一行，选中时整行淡金底。"""

    def sizeHint(self, option, index):
        return QSize(0, 54)

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(option.rect).adjusted(2, 2, -2, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.rgba(theme.GOLD, 0.13))
            painter.drawPath(theme.squircle(rect, 11))
            painter.setPen(QPen(theme.rgba(theme.GOLD, 0.35), 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(theme.squircle(rect, 11))
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.rgba(theme.DIVIDER, 0.04 if theme.is_dark() else 0.05))
            painter.drawPath(theme.squircle(rect, 11))

        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        meta = index.data(_META_ROLE) or ""

        name_font = theme.font(13, 600)
        painter.setFont(name_font)
        painter.setPen(theme.rgba(theme.GOLD if selected else theme.IVORY, 0.95))
        painter.drawText(rect.adjusted(14, 6, -14, -26),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         theme.elide(name, name_font, rect.width() - 30))

        painter.setFont(theme.font(10, 400, 0.4))
        painter.setPen(theme.rgba(theme.IVORY, 0.40))
        painter.drawText(rect.adjusted(14, 26, -14, -6),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, meta)

        # 选中项左侧一颗青点，比整行高亮更克制
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.rgba(theme.CYAN, 0.9))
            painter.drawEllipse(QRectF(rect.left() + 5, rect.center().y() - 2, 4, 4))

        painter.restore()


class RoutineSelector(GlassWindow):
    """
    剧本选择窗。

    - routine_selected(path) 让主控启动
    - edit_requested(path)   打开编辑器回填
    """

    routine_selected = Signal(str)
    edit_requested = Signal(str)

    CONTENT_W = 450
    CONTENT_H = 432

    def __init__(self):
        super().__init__("流程选择", self.CONTENT_W, self.CONTENT_H,
                         subtitle="挑一条轴，进入实战提示")
        self.setStyleSheet(theme.window_qss())

        self._routines_dir = os.path.join(str(project_root()), "configs", "routines")

        self.list_widget = QListWidget()
        self.list_widget.setItemDelegate(_RoutineDelegate(self.list_widget))
        self.list_widget.setMouseTracking(True)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_widget.itemDoubleClicked.connect(lambda _: self.on_start_clicked())
        self.body_layout.addWidget(self.list_widget, 1)

        self.empty_label = QLabel("configs/routines 里还没有剧本。\n先去「流程上传」写一条。")
        self.empty_label.setObjectName("Hint")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body_layout.addWidget(self.empty_label)

        foot = QWidget()
        foot_layout = QHBoxLayout(foot)
        foot_layout.setContentsMargins(0, 4, 0, 0)
        foot_layout.setSpacing(10)

        self.btn_edit = QPushButton("查看 / 修改")
        self.btn_edit.setMinimumSize(QSize(108, 34))
        self.btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit.clicked.connect(self.on_edit_clicked)
        foot_layout.addWidget(self.btn_edit)

        foot_layout.addStretch(1)

        self.btn_start = QPushButton("启动流程")
        self.btn_start.setObjectName("Primary")
        self.btn_start.setMinimumSize(QSize(120, 34))
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.clicked.connect(self.on_start_clicked)
        foot_layout.addWidget(self.btn_start)

        self.body_layout.addWidget(foot)

        self.refresh_list()

    # ------------------------------------------------------------ 数据

    def showEvent(self, event):
        """每次显示都重新扫一次目录，新建的剧本立刻可见。"""
        self.refresh_list()
        super().showEvent(event)

    def refresh_list(self):
        self.list_widget.clear()
        if not os.path.isdir(self._routines_dir):
            self.empty_label.show()
            return

        files = sorted(f for f in os.listdir(self._routines_dir) if f.endswith(".json"))
        for filename in files:
            item = QListWidgetItem(os.path.splitext(filename)[0])
            item.setData(_META_ROLE, self._describe(os.path.join(self._routines_dir, filename)))
            item.setData(Qt.ItemDataRole.UserRole, filename)
            self.list_widget.addItem(item)

        has_items = self.list_widget.count() > 0
        self.list_widget.setVisible(has_items)
        self.empty_label.setVisible(not has_items)
        if has_items:
            self.list_widget.setCurrentRow(0)

    @staticmethod
    def _describe(path: str) -> str:
        """读出两条轴的长度，拼成一行副标题。"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            opener = len(data.get("opener_script", []))
            loop = len(data.get("loop_script", []))
            team = " / ".join(data.get("team_config", {}).values())
            parts = [f"启动 {opener} 步", f"循环 {loop} 步"]
            if team:
                parts.append(team)
            return "  ·  ".join(parts)
        except Exception:
            return "读取失败"

    # ------------------------------------------------------------ 交互

    def _current_path(self):
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return os.path.join(self._routines_dir, item.data(Qt.ItemDataRole.UserRole))

    def on_start_clicked(self):
        path = self._current_path()
        if path:
            self.routine_selected.emit(path)
            self.close()

    def on_edit_clicked(self):
        path = self._current_path()
        if path:
            self.edit_requested.emit(path)
            self.close()
