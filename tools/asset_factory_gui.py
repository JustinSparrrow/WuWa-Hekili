import sys
import os
import cv2
import json
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QLabel, QComboBox, QPushButton,
                               QSlider, QFormLayout, QGroupBox, QLineEdit, QFileDialog, QMessageBox)
from PySide6.QtCore import Qt, QTimer, Signal, QRect
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QColor

# ---------------- 配置与常量 ----------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(BASE_DIR, "assets", "assets")
MAPPING_FILE = os.path.join(ASSETS_DIR, "Character_Occupation.txt")
FACTORY_CONFIG = os.path.join(BASE_DIR, "tools", "factory_config.json")

# 1-7 对应的文件夹和文件前缀
CATEGORIES = [
    ("normal_attack", "normal"),  # 1
    ("jump", "jump"),  # 2
    ("resonance_skill", "skill"),  # 3
    ("resonance_liberation", "liberation"),  # 4
    ("echo", "echo"),  # 5
    ("character", "avatar"),  # 6
    ("energy_bar", "energy")  # 7
]

WEAPONS = ["sword", "broadblade", "pistols", "gauntlets", "rectifier"]


# ---------------- 自定义视频画板 ----------------
class VideoLabel(QLabel):
    # 信号：当用户画完一个框时发出 (x, y, w, h)
    roi_drawn = Signal(int, int, int, int)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(960, 540)  # 16:9
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: black;")

        self.drawing = False
        self.start_pt = None
        self.current_pt = None
        self.active_roi_index = -1  # 当前正在设置第几个框
        self.rois = {}  # 存储 1-7 的真实坐标 (相对于原图)

        self.frame_qimage = None
        self.scale_factor = 1.0
        self.x_offset = 0
        self.y_offset = 0

    def set_image(self, qimg, orig_w, orig_h):
        self.frame_qimage = qimg
        # 计算缩放比例和黑边偏移量，以便将鼠标坐标准确映射到原图
        lbl_w, lbl_h = self.width(), self.height()
        scale_w, scale_h = lbl_w / orig_w, lbl_h / orig_h
        self.scale_factor = min(scale_w, scale_h)

        new_w, new_h = int(orig_w * self.scale_factor), int(orig_h * self.scale_factor)
        self.x_offset = (lbl_w - new_w) // 2
        self.y_offset = (lbl_h - new_h) // 2

        self.setPixmap(QPixmap.fromImage(qimg).scaled(
            new_w, new_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def start_drawing(self, index):
        self.active_roi_index = index
        self.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, event):
        if self.active_roi_index != -1 and event.button() == Qt.MouseButton.LeftButton:
            self.drawing = True
            self.start_pt = event.pos()
            self.current_pt = event.pos()

    def mouseMoveEvent(self, event):
        if self.drawing:
            self.current_pt = event.pos()
            self.update()  # 触发 paintEvent 画红框

    def mouseReleaseEvent(self, event):
        if self.drawing and event.button() == Qt.MouseButton.LeftButton:
            self.drawing = False
            self.setCursor(Qt.CursorShape.ArrowCursor)

            # 屏幕坐标 -> 原图坐标
            x1 = int((min(self.start_pt.x(), self.current_pt.x()) - self.x_offset) / self.scale_factor)
            y1 = int((min(self.start_pt.y(), self.current_pt.y()) - self.y_offset) / self.scale_factor)
            x2 = int((max(self.start_pt.x(), self.current_pt.x()) - self.x_offset) / self.scale_factor)
            y2 = int((max(self.start_pt.y(), self.current_pt.y()) - self.y_offset) / self.scale_factor)

            w, h = x2 - x1, y2 - y1
            if w > 10 and h > 10:
                self.rois[self.active_roi_index] = (x1, y1, w, h)
                self.roi_drawn.emit(*self.rois[self.active_roi_index])
            self.active_roi_index = -1
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(QColor(0, 255, 0), 2, Qt.PenStyle.SolidLine))

        # 画已经保存的框
        for idx, (x, y, w, h) in self.rois.items():
            # 原图坐标 -> 屏幕坐标
            sx = int(x * self.scale_factor + self.x_offset)
            sy = int(y * self.scale_factor + self.y_offset)
            sw = int(w * self.scale_factor)
            sh = int(h * self.scale_factor)
            painter.drawRect(sx, sy, sw, sh)
            painter.drawText(sx, sy - 5, f"[{idx + 1}] {CATEGORIES[idx][0]}")

        # 画正在拖动的框
        if self.drawing and self.start_pt and self.current_pt:
            painter.setPen(QPen(QColor(255, 0, 0), 2, Qt.PenStyle.DashLine))
            painter.drawRect(QRect(self.start_pt, self.current_pt))


# ---------------- 主窗口 ----------------
class AssetFactory(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WuWa Asset Factory (一键素材收割机)")
        self.resize(1400, 800)

        self.cap = None
        self.is_playing = False
        self.orig_frame = None

        # 加载角色和配置
        self.char_weapons = {}
        self._load_character_mapping()
        self._load_config()

        self._init_ui()
        self._setup_timer()

    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)

        # === 左侧：视频播放区域 ===
        left_layout = QVBoxLayout()

        # 控制栏
        video_ctrl = QHBoxLayout()
        self.btn_load_vid = QPushButton("📂 打开视频")
        self.btn_load_vid.clicked.connect(self.load_video)
        self.btn_play = QPushButton("⏸️ 播放/暂停 (Space)")
        self.btn_play.clicked.connect(self.toggle_play)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderMoved.connect(self.seek_video)

        video_ctrl.addWidget(self.btn_load_vid)
        video_ctrl.addWidget(self.btn_play)
        video_ctrl.addWidget(self.slider)

        # 视频画板
        self.video_label = VideoLabel()
        self.video_label.rois = self.config.get("rois", {})  # 恢复上次的框
        # 修复字典的 key 从 string 转回 int
        self.video_label.rois = {int(k): v for k, v in self.video_label.rois.items()}
        self.video_label.roi_drawn.connect(self.on_roi_drawn)

        left_layout.addLayout(video_ctrl)
        left_layout.addWidget(self.video_label, stretch=1)
        layout.addLayout(left_layout, stretch=3)

        # === 右侧：控制面板 ===
        right_layout = QVBoxLayout()

        # 1. 角色选择与录入
        group_char = QGroupBox("1. 角色选择与录入")
        form_char = QFormLayout(group_char)

        self.combo_char = QComboBox()
        self.combo_char.addItems(sorted(list(self.char_weapons.keys())))
        form_char.addRow("当前角色:", self.combo_char)

        self.edit_new_char = QLineEdit()
        self.edit_new_char.setPlaceholderText("英文名 (如 Jinhsi)")
        self.combo_weapon = QComboBox()
        self.combo_weapon.addItems(WEAPONS)
        self.btn_add_char = QPushButton("➕ 添加新角色")
        self.btn_add_char.clicked.connect(self.add_character)

        form_char.addRow("新角色名:", self.edit_new_char)
        form_char.addRow("武器类型:", self.combo_weapon)
        form_char.addRow("", self.btn_add_char)
        right_layout.addWidget(group_char)

        # 2. ROI 框选设定
        group_roi = QGroupBox("2. 设定截取区域 (框选一次，永久有效)")
        roi_layout = QVBoxLayout(group_roi)
        self.roi_labels = []
        for i, (cat, _) in enumerate(CATEGORIES):
            row = QHBoxLayout()
            lbl = QLabel(f"[{i + 1}] {cat}")
            btn = QPushButton("✏️ 画框")
            # 使用默认参数绑定闭包，避免 i 变量泄露
            btn.clicked.connect(lambda checked=False, idx=i: self.video_label.start_drawing(idx))
            row.addWidget(lbl)
            row.addWidget(btn)
            roi_layout.addLayout(row)
        right_layout.addWidget(group_roi)

        # 3. 日志区
        group_log = QGroupBox("3. 操作日志")
        log_layout = QVBoxLayout(group_log)
        self.log_text = QLabel("等待操作...\n(在视频暂停时，按下数字键 1-7 一键抓取)")
        self.log_text.setWordWrap(True)
        self.log_text.setStyleSheet("color: green; font-weight: bold;")
        log_layout.addWidget(self.log_text)
        right_layout.addWidget(group_log)

        right_layout.addStretch()
        layout.addLayout(right_layout, stretch=1)

    def _setup_timer(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)

    # ---------------- 业务逻辑 ----------------
    def _load_character_mapping(self):
        if not os.path.exists(ASSETS_DIR): os.makedirs(ASSETS_DIR)
        if os.path.exists(MAPPING_FILE):
            with open(MAPPING_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if "=" in line:
                        c, w = line.strip().split("=", 1)
                        self.char_weapons[c.strip()] = w.strip()

    def add_character(self):
        name = self.edit_new_char.text().strip()
        weapon = self.combo_weapon.currentText()
        if name:
            self.char_weapons[name] = weapon
            with open(MAPPING_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n{name}={weapon}")
            self.combo_char.addItem(name)
            self.combo_char.setCurrentText(name)
            self.edit_new_char.clear()
            self.log(f"已添加新角色: {name}")

    def _load_config(self):
        if os.path.exists(FACTORY_CONFIG):
            with open(FACTORY_CONFIG, "r") as f:
                self.config = json.load(f)
        else:
            self.config = {"rois": {}}

    def on_roi_drawn(self, x, y, w, h):
        # 画完框后，保存配置
        self.config["rois"] = self.video_label.rois
        with open(FACTORY_CONFIG, "w") as f:
            json.dump(self.config, f)
        self.log("区域保存成功！")

    def load_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择视频文件", "", "Video (*.mp4 *.mkv *.avi)")
        if path:
            if self.cap: self.cap.release()
            self.cap = cv2.VideoCapture(path)
            self.slider.setRange(0, int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)))
            self.is_playing = True
            self.timer.start(30)
            self.log(f"已加载视频: {os.path.basename(path)}")

    def toggle_play(self):
        self.is_playing = not self.is_playing

    def seek_video(self, pos):
        if self.cap:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            self.next_frame(force=True)

    def next_frame(self, force=False):
        if self.cap and (self.is_playing or force):
            ret, frame = self.cap.read()
            if ret:
                self.orig_frame = frame
                # BGR to RGB
                rgb_img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_img.shape
                qimg = QImage(rgb_img.data, w, h, ch * w, QImage.Format.Format_RGB888)
                self.video_label.set_image(qimg, w, h)
                if not force:
                    self.slider.blockSignals(True)
                    self.slider.setValue(int(self.cap.get(cv2.CAP_PROP_POS_FRAMES)))
                    self.slider.blockSignals(False)

    # ---------------- 核心：快捷键截取 ----------------
    def keyPressEvent(self, event):
        key = event.key()

        # 空格键播放/暂停
        if key == Qt.Key.Key_Space:
            self.toggle_play()
            return

        # 1-7 键一键提取
        if Qt.Key.Key_1 <= key <= Qt.Key.Key_7:
            if self.orig_frame is None: return

            idx = key - Qt.Key.Key_1

            # 检查这个编号的框画了没
            if idx not in self.video_label.rois:
                self.log(f"❌ 错误：尚未画框！请先点击右侧【[{idx + 1}]】的画框按钮。")
                return

            char_name = self.combo_char.currentText()
            if not char_name:
                self.log("❌ 错误：请先在右上角选择或添加一个角色。")
                return

            folder_name, prefix = CATEGORIES[idx]
            x, y, w, h = self.video_label.rois[idx]

            # 裁剪图片
            crop = self.orig_frame[y:y + h, x:x + w]

            # 创建文件夹
            save_dir = os.path.join(ASSETS_DIR, char_name, folder_name)
            os.makedirs(save_dir, exist_ok=True)

            # 自动编号寻找：找 normal_1, normal_2...
            count = 1
            while True:
                filename = f"{prefix}_{count}.png" if count > 1 else f"{prefix}.png"
                save_path = os.path.join(save_dir, filename)
                if not os.path.exists(save_path):
                    break
                count += 1

            cv2.imwrite(save_path, crop)
            self.log(f"📸 成功截取并保存:\n{char_name}/{folder_name}/{filename}")

    def log(self, text):
        self.log_text.setText(text)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AssetFactory()
    window.show()
    sys.exit(app.exec())