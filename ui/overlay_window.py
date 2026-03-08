from PySide6.QtWidgets import QMainWindow, QWidget, QMenu, QApplication
from PySide6.QtCore import Qt, QPoint, Signal, QPropertyAnimation, QParallelAnimationGroup, QEasingCurve, QRect
from PySide6.QtGui import QAction

from ui.widgets import ActionWidget
from utils.config_manager import config


class HekiliOverlay(QMainWindow):
    open_settings_signal = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("WuWa Hekili Overlay")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        old_x = config.get("settings.window_x", 100)
        old_y = config.get("settings.window_y", 100)
        self.setGeometry(old_x, old_y, 400, 150)
        self._drag_pos = QPoint()

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # 💡 核心动画参数定义：5个槽位的位置和透明度
        self.widgets = []
        self.anim_group = None
        self.exiting_widget = None

        # [位置0] 退出的位置 (往左飞出并缩小)
        self.POS_OUT = QRect(-80, 20, 80, 80)
        self.OP_OUT = 0.0
        # [位置1] 当前技能 (最大、最高亮)
        self.POS_CUR = QRect(10, 20, 80, 80)
        self.OP_CUR = 1.0
        # [位置2] 下一个技能 (中等)
        self.POS_NXT = QRect(110, 28, 64, 64)
        self.OP_NXT = 0.8
        # [位置3] 未来技能 (偏小)
        self.POS_FUT = QRect(190, 36, 48, 48)
        self.OP_FUT = 0.6
        # [位置4] 备用进场位置 (从右侧淡入)
        self.POS_IN = QRect(260, 44, 32, 32)
        self.OP_IN = 0.0

    def update_ui(self, visual_data, is_advance=False):
        """
        :param is_advance: 是否是连招推进 (True执行滑动动画，False瞬间重置排版)
        """
        while len(visual_data) < 3:
            visual_data.append({})

        # 💡 防连按机制：如果上一个动画还没播完，用户又按了键
        # 我们就强制中断上一个动画，瞬间把图对齐，然后开始新动画
        if self.anim_group and self.anim_group.state() == QParallelAnimationGroup.State.Running:
            self.anim_group.stop()
            if self.exiting_widget:
                self.exiting_widget.deleteLater()
                self.exiting_widget = None
            if len(self.widgets) == 3:
                self.widgets[0].setGeometry(self.POS_CUR)
                self.widgets[0].graphicsEffect().setOpacity(self.OP_CUR)
                self.widgets[1].setGeometry(self.POS_NXT)
                self.widgets[1].graphicsEffect().setOpacity(self.OP_NXT)
                self.widgets[2].setGeometry(self.POS_FUT)
                self.widgets[2].graphicsEffect().setOpacity(self.OP_FUT)

        if not is_advance or len(self.widgets) < 3:
            # === 静态刷新 (开机、或者按X重置时) ===
            for w in self.widgets: w.deleteLater()
            self.widgets.clear()

            for i in range(3):
                w = ActionWidget(self.central_widget)
                w.set_data(visual_data[i])
                if i == 0:
                    w.setGeometry(self.POS_CUR)
                    w.graphicsEffect().setOpacity(self.OP_CUR)
                    w.update_style(visual_data[i].get("variant"), True)
                elif i == 1:
                    w.setGeometry(self.POS_NXT)
                    w.graphicsEffect().setOpacity(self.OP_NXT)
                    w.update_style(visual_data[i].get("variant"), False)
                elif i == 2:
                    w.setGeometry(self.POS_FUT)
                    w.graphicsEffect().setOpacity(self.OP_FUT)
                    w.update_style(visual_data[i].get("variant"), False)
                w.show()
                self.widgets.append(w)
        else:
            # === 🍏 苹果级平滑滑动动画 ===
            w_out = self.widgets[0]  # 即将飞出去的当前动作
            w_cur = self.widgets[1]  # 即将变成当前动作的
            w_nxt = self.widgets[2]  # 即将前移的

            # 在最右侧秘密生成一个新的动作
            w_fut = ActionWidget(self.central_widget)
            w_fut.set_data(visual_data[2])
            w_fut.setGeometry(self.POS_IN)
            w_fut.graphicsEffect().setOpacity(self.OP_IN)
            w_fut.update_style(visual_data[2].get("variant"), False)
            w_fut.show()

            self.exiting_widget = w_out
            self.widgets = [w_cur, w_nxt, w_fut]

            # 同步数据和边框样式 (边框瞬间变色，反馈感更强)
            w_cur.set_data(visual_data[0])
            w_cur.update_style(visual_data[0].get("variant"), True)
            w_nxt.set_data(visual_data[1])
            w_nxt.update_style(visual_data[1].get("variant"), False)

            # 建立并行组合动画
            self.anim_group = QParallelAnimationGroup(self)

            # 使用 OutExpo 曲线：起步极快，结尾极其平滑 (标准苹果阻尼感)
            easing = QEasingCurve.Type.OutExpo
            duration = 300  # 动画时长 300ms

            def add_anim(widget, end_geo, end_op):
                # 几何平移 + 尺寸缩放 动画
                anim_geo = QPropertyAnimation(widget, b"geometry")
                anim_geo.setDuration(duration)
                anim_geo.setEndValue(end_geo)
                anim_geo.setEasingCurve(easing)
                self.anim_group.addAnimation(anim_geo)

                # 透明度渐变动画
                anim_op = QPropertyAnimation(widget.graphicsEffect(), b"opacity")
                anim_op.setDuration(duration)
                anim_op.setEndValue(end_op)
                anim_op.setEasingCurve(easing)
                self.anim_group.addAnimation(anim_op)

            # 分配动画目标
            add_anim(w_out, self.POS_OUT, self.OP_OUT)  # 飞出变透明
            add_anim(w_cur, self.POS_CUR, self.OP_CUR)  # 就位并放大
            add_anim(w_nxt, self.POS_NXT, self.OP_NXT)  # 就位并放大
            add_anim(w_fut, self.POS_FUT, self.OP_FUT)  # 进场并浮现

            self.anim_group.finished.connect(self._on_anim_finished)
            self.anim_group.start()

    def _on_anim_finished(self):
        """动画结束时的垃圾回收"""
        if self.exiting_widget:
            self.exiting_widget.deleteLater()
            self.exiting_widget = None

    # ... 右键菜单与鼠标拖拽逻辑保持不变 (复制你原来的即可) ...
    def show_context_menu(self, pos):
        menu = QMenu(self)
        settings_action = QAction("⚙️ 按键设置", self)
        settings_action.triggered.connect(lambda: self.open_settings_signal.emit())
        menu.addAction(settings_action)
        exit_action = QAction("❌ 退出程序", self)
        exit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(exit_action)
        menu.setStyleSheet("QMenu { background-color: white; border: 1px solid gray; }")
        menu.exec(self.mapToGlobal(pos))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            current_pos = self.pos()
            config.update_setting("settings.window_x", current_pos.x())
            config.update_setting("settings.window_y", current_pos.y())
            event.accept()