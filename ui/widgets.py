from PySide6.QtWidgets import QWidget, QLabel, QFrame, QGraphicsOpacityEffect
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap


class ActionWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)

        # 💡 核心：为子控件启用独立的透明度特效，供动画引擎调用
        self.op_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.op_effect)
        self.op_effect.setOpacity(1.0)

        self.default_border = "#808080"
        self.heavy_border = "#FF4500"
        self.current_border = "#FFD700"

        # 1. 技能大图
        self.icon_label = QLabel(self)
        self.icon_label.setScaledContents(True)

        # 2. 右下角按键
        self.btn_label = QLabel(self)
        self.btn_label.setScaledContents(True)
        self.btn_label.setStyleSheet("background: transparent;")

        # 3. 状态文字 (重击/核心)
        self.status_label = QLabel(self)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("""
            background-color: rgba(255, 0, 0, 180); 
            color: white; 
            font-weight: bold; 
            font-size: 10px;
            border-radius: 2px;
        """)
        self.status_label.hide()

    def resizeEvent(self, event):
        """💡 核心：当外层控制大小发生动画变化时，内层组件自动计算比例缩放"""
        super().resizeEvent(event)
        w = self.width()
        h = self.height()

        # 图标铺满留边
        self.icon_label.setGeometry(2, 2, w - 4, h - 4)

        # 按键尺寸保持为整体宽度的 35%
        btn_size = int(w * 0.35)
        self.btn_label.setFixedSize(btn_size, btn_size)
        self.btn_label.move(w - btn_size - 2, h - btn_size - 2)

        # 状态标签占据上方 25%
        self.status_label.setGeometry(2, 2, w - 4, int(h * 0.25))

    def update_style(self, variant=None, is_current=False):
        """仅更新颜色，透明度和位置交给外层动画管理"""
        border_color = self.current_border if is_current else self.default_border
        if variant and "heavy" in variant.lower():
            border_color = self.heavy_border

        border_width = 3 if is_current else 1

        self.setStyleSheet(f"""
            ActionWidget {{
                background-color: rgba(0, 0, 0, 180);
                border: {border_width}px solid {border_color};
                border-radius: 8px;
            }}
        """)

    def set_data(self, data):
        icon_path = data.get("icon_path")
        btn_path = data.get("btn_path")
        variant = data.get("variant")

        if icon_path:
            self.icon_label.setPixmap(QPixmap(icon_path))
        else:
            self.icon_label.clear()

        if btn_path:
            self.btn_label.setPixmap(QPixmap(btn_path))
            self.btn_label.show()
        else:
            self.btn_label.hide()

        if variant:
            v_lower = variant.lower()
            if "heavy" in v_lower:
                self.status_label.setText("重击 HOLD")
                self.status_label.show()
            elif "forte" in v_lower:
                self.status_label.setText("核心")
                self.status_label.show()
            elif "liberation" in v_lower:
                self.status_label.setText("爆发")
                self.status_label.show()
            else:
                self.status_label.hide()
        else:
            self.status_label.hide()