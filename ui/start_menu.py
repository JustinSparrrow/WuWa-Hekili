from PySide6.QtWidgets import (QWidget, QVBoxLayout,QPushButton,QApplication,QLabel,QSpacerItem,QSizePolicy)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

class StartMenu(QWidget):
    open_settings = Signal()        # 点击按键绑定
    open_upload = Signal()          # 点击流程上传
    open_select = Signal()          # 点击流程选择
    start_overlay = Signal()        # 预留

    def __init__(self):
        super().__init__()
        self.setWindowTitle("WuWa Hekili - 启动器")
        self.setFixedSize(300, 400)

        # 布局
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(40,40,40,40)

        # 标题
        title = QLabel("WuWa Hekili")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 字体
        front = QFont()
        front.setBold(True)
        front.setPointSize(24)
        title.setFont(front)
        title.setStyleSheet("color:#333;margin-bottom:20px;")

        layout.addWidget(title)

        # 按钮
        def create_btn(text, icon_emoji=""):
            btn = QPushButton(f"{icon_emoji}  {text}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(45)
            # 扁平化风格样式
            btn.setStyleSheet("""
                       QPushButton {
                           background-color: #f0f0f0;
                           border: 1px solid #ccc;
                           border-radius: 8px;
                           font-size: 14px;
                           color: #333;
                       }
                       QPushButton:hover {
                           background-color: #e0e0e0;
                           border: 1px solid #999;
                       }
                       QPushButton:pressed {
                           background-color: #d0d0d0;
                       }
                   """)
            return btn

        # 按钮 1: 按键绑定
        self.btn_bind = create_btn("按键绑定", "🎮")
        self.btn_bind.clicked.connect(self.open_settings.emit)
        layout.addWidget(self.btn_bind)

        # 按钮 2: 流程上传
        self.btn_upload = create_btn("流程上传", "☁️")
        self.btn_upload.clicked.connect(self.open_upload.emit)
        layout.addWidget(self.btn_upload)

        # 按钮 3: 流程选择
        self.btn_select = create_btn("流程选择", "📂")
        self.btn_select.clicked.connect(self.open_select.emit)
        layout.addWidget(self.btn_select)

        # 占位符，把按钮顶上去一点
        layout.addItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        version = QLabel("v1.0.0 Dev")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet("color: #999; font-size: 10px;")
        layout.addWidget(version)

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = StartMenu()
    window.show()
    sys.exit(app.exec())
