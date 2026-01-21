from PySide6.QtWidgets import QWidget, QLabel, QFrame
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QColor


class ActionWidget(QFrame):
    def __init__(self, size=64, is_current=False):
        super().__init__()
        self.current_variant = None
        self.setFixedSize(size, size)
        self.is_current = is_current
        self.size_px = size

        # 默认样式颜色
        self.default_border = "#FFD700" if is_current else "#808080"
        self.heavy_border = "#FF4500"  # 橙红色，用于重击

        # 1. 技能图标
        self.icon_label = QLabel(self)
        self.icon_label.setGeometry(2, 2, size - 4, size - 4)
        self.icon_label.setScaledContents(True)

        # 2. 按键图标 (右下角)
        btn_size = int(size * 0.4)
        self.btn_label = QLabel(self)
        self.btn_label.setFixedSize(btn_size, btn_size)
        self.btn_label.setScaledContents(True)
        self.btn_label.move(size - btn_size - 2, size - btn_size - 2)

        # 3. ✨ 新增：状态标签 (左上角或顶部)
        # 用来写“重击”、“强化”等文字
        self.status_label = QLabel(self)
        self.status_label.setGeometry(2, 2, size - 4, int(size * 0.3))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("""
            background-color: rgba(255, 0, 0, 150); 
            color: white; 
            font-weight: bold; 
            font-size: 10px;
            border-radius: 2px;
        """)
        self.status_label.hide()  # 默认隐藏

    def update_style(self, variant=None):
        # 基础透明度
        opacity = 1.0 if self.is_current else 0.7

        # 根据 variant 决定边框颜色
        border_color = self.default_border
        if variant == "heavy":
            border_color = self.heavy_border

        border_width = 3 if self.is_current else 1

        self.setStyleSheet(f"""
            ActionWidget {{
                background-color: rgba(0, 0, 0, 180);
                border: {border_width}px solid {border_color};
                border-radius: 8px;
            }}
        """)
        self.setWindowOpacity(opacity)

    def set_hold_progress(self, progress):
        """
        progress: 0.0 到 1.0
        可以用来改变边框颜色深浅，或者让一个进度条 Label 变长
        """
        if progress > 0:
            # 比如：长按时边框变红
            self.setStyleSheet(f"""
                ActionWidget {{
                    background-color: rgba(255, 69, 0, {int(progress * 150)});
                    border: 4px solid #FF4500;
                    border-radius: 8px;
                }}
            """)
        else:
            self.update_style(self.current_variant)

    def set_data(self, data):
        """
        data 格式: {"icon_path": ..., "btn_path": ..., "variant": ...}
        """
        icon_path = data.get("icon_path")
        btn_path = data.get("btn_path")
        variant = data.get("variant")

        # 1. 设置图标
        if icon_path:
            self.icon_label.setPixmap(QPixmap(icon_path))
        else:
            self.icon_label.clear()

        # 2. 设置按键
        if btn_path:
            self.btn_label.setPixmap(QPixmap(btn_path))
            self.btn_label.show()
        else:
            self.btn_label.hide()

        # 3. ✨ 处理重击和其他变体的视觉区分
        self.update_style(variant)

        if variant == "heavy":
            self.status_label.setText("重击 HOLD")
            self.status_label.show()
        elif variant == "forte":
            self.status_label.setText("核心")
            self.status_label.show()
        elif variant == "liberation":
            self.status_label.setText("爆发")
            self.status_label.show()
        else:
            self.status_label.hide()