import os
import json
import sys
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QLineEdit, QTextEdit, QPushButton, QComboBox,
                               QStackedWidget, QFormLayout, QGroupBox, QMessageBox, QProgressBar, QInputDialog,
                               QScrollArea)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPixmap

import ui.theme as theme
from core.script_parser import ScriptParser
from ui.frame import GlassWindow, SectionTitle
from utils.asset_manager import AssetManager
from utils.logger import log


class RoutineUploaderWindow(GlassWindow):
    """
    连招流程编辑器（两页式）。

    第 1 页：填队伍 1/2/3 号位与代称，再输入「黑话」脚本
             （如 "爱aaaa莫aaazr2..."），点解析交给 core.script_parser.ScriptParser。
    第 2 页：逐行预览解析结果，每一步可以下拉换图标、纠正匹配错的素材，
             确认后保存成 configs/routines/<名字>.json。

    保存的 JSON 同时保留黑话原文（original_opener/original_loop），
    方便下次进来继续编辑。
    """

    routine_saved = Signal(str)

    CONTENT_W = 720
    CONTENT_H = 760

    def __init__(self):
        super().__init__("连招流程编辑器", self.CONTENT_W, self.CONTENT_H,
                         subtitle="黑话 → 可执行的剧本 JSON")
        self.setStyleSheet(theme.window_qss())

        # 老代码里到处引用 self.layout，这里保留别名，避免大面积改动
        self.layout = self.body_layout
        self.stacked_widget = QStackedWidget()
        self.layout.addWidget(self.stacked_widget)

        # 状态
        self.is_edit_mode = False
        self.current_editing_filename = ""
        self.parsed_opener = []
        self.parsed_loop = []
        self.temp_team_mapping = {}

        # 资源管理器复用实例：每次预览都新建会重复读 Character_Occupation.txt，
        # 且丢掉 AssetManager 内部的路径缓存
        self.asset_mgr = None

        self.init_input_page()
        self.init_preview_page()

    def init_input_page(self):
        self.input_page = QWidget()
        layout = QVBoxLayout(self.input_page)

        char_group = QGroupBox("1. 队伍配置 (1/2/3 号位)")
        char_layout = QFormLayout(char_group)
        self.available_chars = self._scan_characters()
        self.char_inputs = []
        for i in range(3):
            row = QHBoxLayout()
            combo = QComboBox();
            combo.addItems(self.available_chars)
            alias = QLineEdit();
            alias.setPlaceholderText("代称 (如: 忌, 莫)")
            row.addWidget(combo, stretch=2);
            row.addWidget(alias, stretch=1)
            self.char_inputs.append((combo, alias))
            char_layout.addRow(f"{i + 1} 号位:", row)
        layout.addWidget(char_group)

        text_group = QGroupBox("2. 连招脚本 (黑话/简写)")
        text_layout = QVBoxLayout(text_group)

        # 语法速查：字母后跟数字表示变体，跟 + 表示长按
        tip = QLabel("a普攻 e技能 r解放 q声骸 z重击 f处决 s闪避 j跳跃 ｜ "
                     "字母后加数字=变体(a2) ｜ 加 + = 长按(e+) ｜ 中文名=切人")
        tip.setWordWrap(True)
        tip.setObjectName("Hint")
        text_layout.addWidget(tip)

        text_layout.addWidget(QLabel("启动轴 (Opener):"))
        self.opener_edit = QTextEdit()
        self.opener_edit.setPlaceholderText("例如: 爱aaaa莫aa...")
        text_layout.addWidget(self.opener_edit)

        text_layout.addWidget(QLabel("循环轴 (Loop):"))
        self.loop_edit = QTextEdit()
        self.loop_edit.setPlaceholderText("例如: 莫raaa...")
        text_layout.addWidget(self.loop_edit)
        layout.addWidget(text_group)

        self.progress_bar = QProgressBar();
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.btn_parse = QPushButton("解析并预览图标")
        self.btn_parse.setObjectName("Primary")
        self.btn_parse.setMinimumHeight(40)
        self.btn_parse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_parse.clicked.connect(self.start_parsing_animation)
        parse_row = QHBoxLayout()
        parse_row.addStretch(1)
        self.btn_parse.setMinimumWidth(200)
        parse_row.addWidget(self.btn_parse)
        layout.addLayout(parse_row)

        self.stacked_widget.addWidget(self.input_page)

    def init_preview_page(self):
        self.preview_page = QWidget()
        layout = QVBoxLayout(self.preview_page)

        head = QLabel("解析结果")
        head.setObjectName("H1")
        layout.addWidget(head)
        sub = QLabel("逐行核对图标：下拉框可以换掉匹配错的素材，选完再保存。")
        sub.setObjectName("Hint")
        layout.addWidget(sub)

        # 可滚动的区域显示图标列表
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_list_layout = QVBoxLayout(self.scroll_content)
        self.scroll_area.setWidget(self.scroll_content)
        layout.addWidget(self.scroll_area)

        btn_layout = QHBoxLayout()
        self.btn_back = QPushButton("返回修改")
        self.btn_back.setMinimumHeight(36)
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0))

        self.btn_save = QPushButton("保存流程")
        self.btn_save.setObjectName("Primary")
        self.btn_save.setMinimumHeight(36)
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.clicked.connect(self.save_routine)

        btn_layout.addWidget(self.btn_back);
        btn_layout.addStretch();
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)
        self.stacked_widget.addWidget(self.preview_page)

    def _scan_characters(self):
        if getattr(sys, 'frozen', False):
            root_dir = os.path.dirname(sys.executable)
        else:
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assets_path = os.path.join(base_dir, "assets", "characters")
        if not os.path.exists(assets_path): return ["Unknown"]
        chars = sorted(
            [d for d in os.listdir(assets_path) if os.path.isdir(os.path.join(assets_path, d)) and d != "_general"])
        return chars

    def load_existing_routine(self, json_path):
        """编辑模式：回填数据"""
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.is_edit_mode = True
            self.current_editing_filename = os.path.basename(json_path)

            team_cfg = data.get("team_config", {})
            team_aliases = data.get("team_aliases", {})
            for i in range(3):
                name = team_cfg.get(str(i + 1))
                idx = self.char_inputs[i][0].findText(name)
                if idx >= 0: self.char_inputs[i][0].setCurrentIndex(idx)
                self.char_inputs[i][1].setText(team_aliases.get(str(i + 1), ""))

            self.opener_edit.setPlainText(data.get("original_opener", ""))
            self.loop_edit.setPlainText(data.get("original_loop", ""))
            self.stacked_widget.setCurrentIndex(0)
            self.btn_save.setText("覆盖保存")
            self.show()
        except Exception as e:
            log.error(f"加载流程失败: {e}")

    def start_parsing_animation(self):
        """播放进度条动画"""
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.btn_parse.setEnabled(False)

        # 准备映射数据
        self.temp_team_mapping = {}
        for i, (combo, alias_input) in enumerate(self.char_inputs):
            name = combo.currentText()
            aliases = [x.strip() for x in alias_input.text().replace("，", ",").split(",") if x.strip()]
            self.temp_team_mapping[name] = (i + 1, name, aliases)

        self.timer = QTimer()
        self.timer.timeout.connect(self._update_anim)
        self.anim_val = 0
        self.timer.start(5)

    def _update_anim(self):
        self.anim_val += 5
        self.progress_bar.setValue(self.anim_val)
        if self.anim_val >= 100:
            self.timer.stop()
            self.progress_bar.hide()
            self.btn_parse.setEnabled(True)
            self._execute_parse()

    def _execute_parse(self):
        """执行解析并渲染可视化列表"""
        try:
            parser = ScriptParser(self.temp_team_mapping)
            self.parsed_opener = parser.parse(self.opener_edit.toPlainText())
            self.parsed_loop = parser.parse(self.loop_edit.toPlainText())

            self.render_all_previews()
            self.stacked_widget.setCurrentIndex(1)
        except Exception as e:
            QMessageBox.critical(self, "解析失败", str(e))

    def render_all_previews(self):
        """渲染带图标的可视化预览行"""

        # 1. 💡 暴力清空布局 (防止重复显示)
        # 这种 reversed 迭代并 setParent(None) 是 Qt 最稳妥的清空方式
        for i in reversed(range(self.scroll_list_layout.count())):
            item = self.scroll_list_layout.itemAt(i)
            if item.widget():
                item.widget().setParent(None)
            elif item.layout():
                # 如果里面有子布局也要处理，但这里我们主要是层叠 Widget
                pass
            else:
                self.scroll_list_layout.removeItem(item)

        # 2. 复用资源管理器（首次预览时创建，之后沿用其路径缓存）
        if self.asset_mgr is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            assets_path = os.path.join(base_dir, "assets", "characters")
            self.asset_mgr = AssetManager(assets_path)

        self.opener_widgets = []
        self.loop_widgets = []

        # 3. 内部填充函数
        def fill_section(script, widget_list, title):
            # 添加分区标题
            header = SectionTitle(f"{title}  ·  {len(script)} 步")
            self.scroll_list_layout.addWidget(header)

            # 模拟状态
            current_char_id = 1
            team_dict = {str(cid): name for name, (cid, name, al) in self.temp_team_mapping.items()}

            from ui.widgets import ActionEditorRow  # 局部导入防止循环引用

            for i, act in enumerate(script):
                char_name = team_dict.get(str(current_char_id), "Unknown")

                # 如果是切人，先更新指针再取名字
                if act["type"] == "intro":
                    current_char_id = act.get("next_char", current_char_id)
                    char_name = team_dict.get(str(current_char_id), "Unknown")

                # 创建编辑器组件
                row = ActionEditorRow(i, act, char_name, self.asset_mgr)
                self.scroll_list_layout.addWidget(row)
                widget_list.append(row)

        # 4. 执行渲染
        if self.parsed_opener:
            fill_section(self.parsed_opener, self.opener_widgets, "启动轴")

        # 加个分割空隙
        self.scroll_list_layout.addSpacing(28)

        if self.parsed_loop:
            fill_section(self.parsed_loop, self.loop_widgets, "循环轴")

        self.scroll_list_layout.addStretch()  # 把内容顶到最上面


    def save_routine(self):
        """保存逻辑"""
        default = self.current_editing_filename.replace(".json", "") if self.is_edit_mode else ""
        name, ok = QInputDialog.getText(self, "保存流程", "起个名字:", QLineEdit.EchoMode.Normal, default)
        if not (ok and name): return

        def update_script_with_choices(original_script, widgets):
            new_script = []
            for i, act in enumerate(original_script):
                final_act = dict(act)
                selected_file = widgets[i].get_selected_filename()

                if selected_file and selected_file != "None":
                    # 把用户选的精确文件名存下来，运行时直接按名字取图
                    final_act["custom_icon"] = selected_file

                    # 变体只管逻辑，不管图片
                    if "heavy" in final_act.get("variant", "").lower() or final_act.get("desc", "").startswith("重击"):
                        final_act["variant"] = "heavy"
                    elif "forte" in final_act.get("variant", "").lower() or final_act.get("desc", "").startswith(
                            "核心"):
                        final_act["variant"] = "forte"
                new_script.append(final_act)
            return new_script

        final_opener = update_script_with_choices(self.parsed_opener, self.opener_widgets)
        final_loop = update_script_with_choices(self.parsed_loop, self.loop_widgets)

        save_data = {
            "name": name,
            "team_config": {str(cid): name for name, (cid, name, al) in self.temp_team_mapping.items()},
            "team_aliases": {str(cid): ",".join(al) for name, (cid, name, al) in self.temp_team_mapping.items()},
            "original_opener": self.opener_edit.toPlainText(),
            "original_loop": self.loop_edit.toPlainText(),
            "opener_script": final_opener,
            "loop_script": final_loop,
            "initial_char_index": 1
        }

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        routines_dir = os.path.join(base_dir, "configs", "routines")
        os.makedirs(routines_dir, exist_ok=True)

        file_path = os.path.join(routines_dir, f"{name}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=4)

        QMessageBox.information(self, "完成", "流程已保存。")
        self.routine_saved.emit(file_path)
        self.close()