import os
from PySide6.QtWidgets import (QWidget, QLabel, QFrame, QHBoxLayout,
                               QComboBox, QGraphicsOpacityEffect)
from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtGui import QPixmap


# ============================================================
# 组件 1: ActionWidget (用于游戏内的透明悬浮窗)
# ============================================================
class ActionWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)

        # 为透明度动画做准备
        self.op_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.op_effect)
        self.op_effect.setOpacity(1.0)

        self.default_border = "#808080"
        self.heavy_border = "#FF4500"
        self.current_border = "#FFD700"
        self.current_variant = None

        self.icon_label = QLabel(self)
        self.icon_label.setScaledContents(True)

        self.btn_label = QLabel(self)
        self.btn_label.setScaledContents(True)
        self.btn_label.setStyleSheet("background: transparent;")

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
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        self.icon_label.setGeometry(2, 2, w - 4, h - 4)
        btn_size = int(w * 0.35)
        self.btn_label.setFixedSize(btn_size, btn_size)
        self.btn_label.move(w - btn_size - 2, h - btn_size - 2)
        self.status_label.setGeometry(2, 2, w - 4, int(h * 0.25))

    def update_style(self, variant=None, is_current=False):
        self.current_variant = variant
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
        desc = data.get("desc", "")

        # 💡 设置技能大图（核心修改）
        if icon_path and os.path.exists(icon_path):
            self.icon_label.setPixmap(QPixmap(icon_path))
            self.icon_label.setText("")
            self.icon_label.setStyleSheet("background: transparent;")  # 恢复透明
        else:
            self.icon_label.clear()

            # 判断显示什么字
            display_text = "ACT"
            if "处决" in desc or data.get("type") == "execution":
                display_text = "F"  # 处决显示个大大的F
            elif "闪" in desc or data.get("type") == "dodge":
                display_text = "闪"
            elif "跳" in desc or data.get("type") == "jump":
                display_text = "跳"
            else:
                display_text = desc[:1] if desc else "?"

            self.icon_label.setText(display_text)
            self.icon_label.setStyleSheet("""
                color: #CCCCCC; 
                font-family: 'Microsoft YaHei';
                font-weight: bold;
                font-size: 28px;
                background-color: #1a1a1a;
                border-radius: 6px;
            """)
            self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 设置按键
        if btn_path:
            self.btn_label.setPixmap(QPixmap(btn_path))
            self.btn_label.show()
        else:
            self.btn_label.hide()

        # 处理变体文本
        if variant:
            v_lower = variant.lower()
            if "heavy" in v_lower:
                self.status_label.setText("重击 HOLD"); self.status_label.show()
            elif "forte" in v_lower:
                self.status_label.setText("处决"); self.status_label.show()
            else:
                self.status_label.hide()
        else:
            self.status_label.hide()


# ============================================================
# 组件 2: ActionEditorRow (用于流程编辑器的每一行)
# ============================================================
class ActionEditorRow(QWidget):
    image_changed = Signal(int, str)

    def __init__(self, index, action_data, char_name, asset_mgr, parent=None):
        super().__init__(parent)
        self.index = index
        self.action_data = action_data
        self.char_name = char_name
        self.asset_mgr = asset_mgr
        self.current_search_path = ""  # 💡 新增：记录当前下拉框对应的文件夹路径

        self.setStyleSheet("background-color: white; border-bottom: 1px solid #eee;")
        layout = QHBoxLayout(self)

        self.lbl_idx = QLabel(f"<b>{index + 1:02d}</b>")
        self.lbl_idx.setFixedWidth(30)
        layout.addWidget(self.lbl_idx)

        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(45, 45)
        self.icon_preview.setScaledContents(True)
        layout.addWidget(self.icon_preview)

        desc_text = f"{action_data['desc']} ({char_name})"
        self.lbl_desc = QLabel(desc_text)
        layout.addWidget(self.lbl_desc)

        self.combo_img = QComboBox()
        self.combo_img.setFixedWidth(200)

        options = self._get_all_options()
        self.combo_img.addItems(options)

        current_path = asset_mgr.get_icon_path(
            char_name,
            action_data["type"],
            action_data.get("variant"),
            action_data.get("force_general", False),
            action_data.get("custom_icon")
        )

        # 💡 核心修改：针对图标预览的处理
        if current_path and current_path != "None" and os.path.exists(current_path):
            current_file = os.path.basename(current_path)
            self.combo_img.setCurrentText(current_file)
            self.icon_preview.setPixmap(
                QPixmap(current_path).scaled(45, 45, Qt.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.icon_preview.setText("")  # 清除文字
        else:
            # 💡 画黑框文字
            self.combo_img.setCurrentText("None")  # 设置下拉框为空
            self.icon_preview.clear()

            # 获取用来显示的文字（取动作类型的前几个大写字母）
            display_text = action_data.get("type", "ACT")[:3].upper()
            if action_data.get("type") == "execution":
                display_text = "处决"
            elif action_data.get("type") == "dodge":
                display_text = "闪避"

            self.icon_preview.setText(display_text)
            self.icon_preview.setStyleSheet("""
                        color: white; 
                        background-color: #2b2b2b; 
                        font-size: 12px; 
                        font-weight: bold; 
                        border-radius: 5px;
                    """)
            self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 3. 绑定切换事件
        self.combo_img.currentTextChanged.connect(self._on_change)
        layout.addWidget(self.combo_img)

    def _get_all_options(self):
        """核心：确定并保存搜索路径"""
        action_type = self.action_data["type"]
        folder_name = self.asset_mgr.folder_map.get(action_type, action_type)

        # 初始查找路径
        if self.action_data.get("force_general"):
            weapon = self.asset_mgr.weapon_map.get(self.char_name, "sword")
            path = os.path.join(self.asset_mgr.path, "AAA_general", "normal_attack", weapon)
        else:
            path = os.path.join(self.asset_mgr.path, self.char_name, folder_name)

        # 降级逻辑 (必须与 AssetManager 保持一致)
        if not os.path.exists(path):
            if "heavy" in action_type or (
                    self.action_data.get("variant") and "heavy" in self.action_data["variant"].lower()):
                path = os.path.join(self.asset_mgr.path, self.char_name, "normal_attack")
            elif action_type == "execution" or (
                    self.action_data.get("variant") and "forte" in self.action_data["variant"].lower()):
                path = os.path.join(self.asset_mgr.path, self.char_name, "resonance_skill")

        # 💡 保存这个确定好的路径！
        self.current_search_path = path

        if not os.path.exists(path): return ["None"]
        try:
            files = [f for f in os.listdir(path) if f.lower().endswith('.png')]
            return sorted(files) if files else ["None"]
        except:
            return ["None"]

    def _on_change(self, filename):
        """当用户手动选图时更新预览"""
        if filename == "None":
            # 💡 切换到 None 时，变成黑框
            self.icon_preview.clear()
            display_text = self.action_data.get("type", "ACT")[:3].upper()
            if self.action_data.get("type") == "execution":
                display_text = "处决"
            elif self.action_data.get("type") == "dodge":
                display_text = "闪避"
            self.icon_preview.setText(display_text)
            self.icon_preview.setStyleSheet(
                "color: white; background-color: #2b2b2b; font-size: 12px; font-weight: bold; border-radius: 5px;")
            self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            # 正常的切图逻辑
            folder_name = self.asset_mgr.folder_map.get(self.action_data["type"], self.action_data["type"])

            # 💡 直接使用保存好的路径拼接文件名
            new_path = os.path.join(self.current_search_path, filename)

            if os.path.exists(new_path):
                self.icon_preview.setPixmap(
                    QPixmap(new_path).scaled(45, 45, Qt.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self.icon_preview.setStyleSheet("")  # 💡 恢复样式，清除黑底
                self.icon_preview.setText("")

        # 发射信号通知外层记录选择
        self.image_changed.emit(self.index, filename)

    def get_selected_filename(self):
        return self.combo_img.currentText()