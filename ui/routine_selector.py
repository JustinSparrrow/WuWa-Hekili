import os
import json
from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QPushButton, QLabel
from PySide6.QtCore import Signal


class RoutineSelector(QWidget):
    # 信号：传递被选中的 json 文件的完整路径
    routine_selected = Signal(str)
    edit_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("选择连招流程")
        self.resize(300, 400)

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        layout.addWidget(QLabel("已保存的连招流程:"))
        layout.addWidget(self.list_widget)

        # 增加修改按钮
        btn_edit = QPushButton("📝 查看 / 修改轴内容")
        btn_edit.setStyleSheet("background-color: #607D8B; color: white; padding: 8px; margin-top: 5px;")
        btn_edit.clicked.connect(self.on_edit_clicked)

        btn_start = QPushButton("🚀 启动选中流程")
        btn_start.setStyleSheet("background-color: #2196F3; color: white; padding: 10px; font-weight: bold;")
        btn_start.clicked.connect(self.on_start_clicked)

        layout.addWidget(btn_edit)
        layout.addWidget(btn_start)

        self.refresh_list()

    def showEvent(self, event):
        """ 当窗口显示时，自动触发刷新 """
        self.refresh_list()
        super().showEvent(event)

    def refresh_list(self):
        """扫描 routines 文件夹"""
        self.list_widget.clear()
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        routines_dir = os.path.join(base_dir, "configs", "routines")

        if not os.path.exists(routines_dir): return

        for f in os.listdir(routines_dir):
            if f.endswith(".json"):
                self.list_widget.addItem(f)

    def on_start_clicked(self):
        item = self.list_widget.currentItem()
        if item:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            file_path = os.path.join(base_dir, "configs", "routines", item.text())
            self.routine_selected.emit(file_path)
            self.close()

    def on_edit_clicked(self):
        item = self.list_widget.currentItem()
        if item:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            file_path = os.path.join(base_dir, "configs", "routines", item.text())
            self.edit_requested.emit(file_path) # 发出信号
            self.close() # 关掉选择窗
