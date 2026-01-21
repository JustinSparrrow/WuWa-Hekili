from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout
from PySide6.QtCore import Qt, QPoint

from ui.widgets import ActionWidget
from utils.config_manager import config


class HekiliOverlay(QMainWindow):
    def __init__(self):
        super().__init__()

        # === 窗口设置 (核心) ===
        self.setWindowTitle("WuWa Hekili Overlay")

        # 1. 无边框 | 置顶 | 工具窗口模式(不在任务栏显示)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )

        # 2. 背景透明
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 3. 尺寸与位置
        old_x = config.get("settings.window_x")
        old_y = config.get("settings.window_y")
        self.setGeometry(old_x, old_y, 400, 150)

        self._drag_pos = QPoint()

        # === 布局容器 ===
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.layout = QHBoxLayout(self.central_widget)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(15)  # 图标之间的间距

        # === 初始化 3 个格子 ===
        # Slot 1: 当前动作 (大)
        self.slot_current = ActionWidget(size=80, is_current=True)
        # Slot 2: 下一个 (中)
        self.slot_next = ActionWidget(size=64, is_current=False)
        # Slot 3: 再下一个 (小)
        self.slot_future = ActionWidget(size=48, is_current=False)

        self.layout.addWidget(self.slot_current)
        self.layout.addWidget(self.slot_next)
        self.layout.addWidget(self.slot_future)

        # 挤压布局，靠左对齐 (类似于 Hekili)
        self.layout.addStretch()

    def update_ui(self, visual_data):
        """
        接收 Director 传来的数据列表，更新界面
        visual_data: list [data1, data2, data3]
        """
        # 安全检查：确保数据够3个，不够就补 None
        while len(visual_data) < 3:
            visual_data.append({"icon_path": None, "btn_path": None})

        # 更新三个槽位
        self.slot_current.set_data(visual_data[0])
        self.slot_next.set_data(visual_data[1])
        self.slot_future.set_data(visual_data[2])

    def mousePressEvent(self, event):
        """当鼠标左键按下时，记录当前点击位置相对于窗口左上角的偏移"""
        if event.button() == Qt.MouseButton.LeftButton:
            # 记录相对位置：鼠标全局坐标 - 窗口左上角坐标
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """当鼠标移动时，根据偏移量移动窗口"""
        if event.buttons() & Qt.MouseButton.LeftButton:
            # 窗口新位置 = 鼠标当前全局坐标 - 刚才记录的偏移
            new_pos = event.globalPosition().toPoint() - self._drag_pos
            self.move(new_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        """当鼠标松开时，将当前坐标保存到 config.json"""
        if event.button() == Qt.MouseButton.LeftButton:
            current_pos = self.pos()
            # 自动持久化保存
            config.update_setting("settings.window_x", current_pos.x())
            config.update_setting("settings.window_y", current_pos.y())
            print(f"📍 窗口位置已保存: {current_pos.x()}, {current_pos.y()}")
            event.accept()