from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QMenu, QApplication
from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QAction

from ui.widgets import ActionWidget
from utils.config_manager import config


class HekiliOverlay(QMainWindow):
    # ✨ 新增信号：告诉 main.py "用户要开设置"
    open_settings_signal = Signal()

    def __init__(self):
        super().__init__()

        # === 窗口设置 ===
        self.setWindowTitle("WuWa Hekili Overlay")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 读取位置
        old_x = config.get("settings.window_x", 100)
        old_y = config.get("settings.window_y", 100)
        self.setGeometry(old_x, old_y, 400, 150)

        self._drag_pos = QPoint()

        # === ✨ 新增：启用右键菜单策略 ===
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        # === 布局容器 ===
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.layout = QHBoxLayout(self.central_widget)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(15)

        # === 初始化 3 个格子 ===
        self.slot_current = ActionWidget(size=80, is_current=True)
        self.slot_next = ActionWidget(size=64, is_current=False)
        self.slot_future = ActionWidget(size=48, is_current=False)

        self.layout.addWidget(self.slot_current)
        self.layout.addWidget(self.slot_next)
        self.layout.addWidget(self.slot_future)
        self.layout.addStretch()

    def update_ui(self, visual_data):
        while len(visual_data) < 3:
            visual_data.append({"icon_path": None, "btn_path": None})
        self.slot_current.set_data(visual_data[0])
        self.slot_next.set_data(visual_data[1])
        self.slot_future.set_data(visual_data[2])

    # === ✨ 新增：右键菜单逻辑 ===
    def show_context_menu(self, pos):
        """在鼠标点击位置显示右键菜单"""
        menu = QMenu(self)

        # 选项 1: 设置
        settings_action = QAction("⚙️ 按键设置 (Settings)", self)
        settings_action.triggered.connect(lambda: self.open_settings_signal.emit())
        menu.addAction(settings_action)

        # 选项 2: 退出
        exit_action = QAction("❌ 退出程序 (Exit)", self)
        exit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(exit_action)

        # 弹出菜单
        menu.setStyleSheet("QMenu { background-color: white; border: 1px solid gray; }")
        menu.exec(self.mapToGlobal(pos))

    # === 拖动逻辑 (保持不变) ===
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            new_pos = event.globalPosition().toPoint() - self._drag_pos
            self.move(new_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            current_pos = self.pos()
            config.update_setting("settings.window_x", current_pos.x())
            config.update_setting("settings.window_y", current_pos.y())
            event.accept()