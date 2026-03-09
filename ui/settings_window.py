import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QComboBox, QPushButton, QTabWidget, QFormLayout, QScrollArea)
from PySide6.QtCore import Qt, Signal
from utils.config_manager import config


class SettingsWindow(QWidget):
    config_saved = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("设置 - WuWa Hekili")
        self.setFixedSize(450, 600)

        # 💡 数据结构改变：按设备分类存储下拉框引用
        self.combos = {
            "xbox": {},
            "keyboard": {}
        }

        layout = QVBoxLayout(self)

        # 1. 选项卡控件
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # 2. 🎮 生成 Xbox 设置页
        tab_xbox = QWidget()
        self._build_mapping_form(tab_xbox, "xbox")
        self.tabs.addTab(tab_xbox, "🎮 手柄映射")

        # 3. ⌨️ 生成 键盘 设置页
        tab_kb = QWidget()
        self._build_mapping_form(tab_kb, "keyboard")
        self.tabs.addTab(tab_kb, "⌨️ 键盘映射")

        # 4. 底部按钮
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("💾 保存并应用")
        self.btn_save.setMinimumHeight(40)
        self.btn_save.clicked.connect(self.save_config)

        self.btn_save.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; font-weight: bold; border-radius: 5px; font-size: 14px;}
            QPushButton:hover { background-color: #45a049; }
        """)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

    def _build_mapping_form(self, parent_tab, device):
        """通用方法：为指定的 device 生成表单"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content_widget = QWidget()
        scroll.setWidget(content_widget)

        form_layout = QFormLayout(content_widget)
        form_layout.setSpacing(15)
        form_layout.setContentsMargins(15, 15, 15, 15)

        # 扫描图片名
        icon_options = self._scan_available_icons(device)

        if not icon_options:
            form_layout.addRow(
                QLabel(f"❌ 错误：在 assets/ui/{device} 未找到图标！\n请检查文件夹是否存在及是否有 .png 文件。"))
            layout = QVBoxLayout(parent_tab)
            layout.addWidget(scroll)
            return

        # 读取当前配置
        current_map = config.get(f"keymaps.{device}", {})

        actions = [
            ("🚀 启动/重置 (主发令键)", "start_trigger"),
            ("⚔️ 普通攻击 (Basic)", "basic"),
            ("✨ 共鸣技能 (Skill)", "skill"),
            ("💥 共鸣解放 (Ult)", "ult"),
            ("🦘 跳跃 (Jump)", "jump"),
            ("👻 闪避 (Dodge)", "dodge"),
            ("👾 声骸 (Echo)", "echo"),
            ("🔒 锁定 (Lock)", "lock"),
            ("🎯 处决/核心 (Execution)", "execution"),
            ("🔄 切人-1号位", "intro_1"),
            ("🔄 切人-2号位", "intro_2"),
            ("🔄 切人-3号位", "intro_3")
        ]

        # 遍历生成下拉框
        for label_text, key in actions:
            combo = QComboBox()
            combo.setMinimumHeight(28)
            combo.addItems(icon_options)

            # 选中已保存的值
            current_val = current_map.get(key, "")
            if current_val in icon_options:
                combo.setCurrentText(current_val)

            # 存入对应设备的字典中
            self.combos[device][key] = combo
            form_layout.addRow(QLabel(label_text), combo)

        # 把滚动区域添加到 Tab 布局中
        layout = QVBoxLayout(parent_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def _scan_available_icons(self, device):
        """去 assets/ui/device 文件夹里找所有的图片"""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target_path = os.path.join(base_dir, "assets", "ui", device)

        if not os.path.exists(target_path):
            return []

        files = []
        for f in os.listdir(target_path):
            if f.lower().endswith(".png"):
                files.append(f[:-4])

        files.sort()
        return files

    def save_config(self):
        """遍历两个设备的下拉框，全部保存到 JSON"""
        # 保存 Xbox 配置
        for action_key, combo in self.combos["xbox"].items():
            config.update_setting(f"keymaps.xbox.{action_key}", combo.currentText())

        # 保存 Keyboard 配置
        for action_key, combo in self.combos["keyboard"].items():
            config.update_setting(f"keymaps.keyboard.{action_key}", combo.currentText())

        print("💾 双端按键配置已保存！")
        self.config_saved.emit()
        self.close()