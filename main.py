import json
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

# 导入 UI
from ui import theme
from ui.start_menu import StartMenu
from ui.overlay_window import HekiliOverlay
from ui.settings_window import SettingsWindow
from ui.routine_uploader import RoutineUploaderWindow
from ui.routine_selector import RoutineSelector

# 导入逻辑核心
from utils.asset_manager import AssetManager
from utils.config_manager import config
from utils.input_listener import InputListener
from utils.logger import log
from core.director import Director


class HekiliApp:
    """
    应用控制器：把各个窗口和后台线程串成一条完整链路。

    典型使用流程
    -----------
        启动器 -> 流程选择 -> 加载剧本 JSON
              -> 创建 Director(状态机) + HekiliOverlay(悬浮窗) + InputListener(监听线程)
              -> 玩家按启动键激活 -> 每次按键喂给 Director -> 推进则刷新悬浮窗
              -> 右键悬浮窗可回主菜单 / 退出

    v1.1 优化点
    ----------
    - 子窗口改为懒加载：启动时只创建主菜单，设置/编辑器/选择器在真正点开时
      才构造。其中"流程编辑器"要扫描 46 个角色目录并生成 3 个下拉框，
      是启动阶段最重的一步，现在完全不占用启动时间。
    - AssetManager 复用同一个实例（每次开新流程只清缓存不重建），
      避免重复读取 Character_Occupation.txt。
    """

    def __init__(self, app_instance):
        self.app = app_instance
        self.is_active = False

        self.overlay = None
        self.director = None
        self.input_thread = None
        self.asset_mgr = None

        # 时间轴心跳（v1.2）：把"预输入"在动作结束的瞬间兑现成真正的推进。
        # 只在悬浮窗激活期间运行，30Hz，空缓冲时立即返回，开销可忽略。
        self._tick_timer = QTimer()
        self._tick_timer.setInterval(30)
        self._tick_timer.timeout.connect(self.on_tick)
        self._gate_visible = False

        # 子窗口：按需创建（见 _get_xxx_win）
        self.settings_win = None
        self.uploader_win = None
        self.selector_win = None

        self.menu = StartMenu()
        self._connect_signals()

    # ============================================================ 懒加载窗口

    def _get_settings_win(self):
        if self.settings_win is None:
            self.settings_win = SettingsWindow()
            self.settings_win.config_saved.connect(self.on_config_reload)
        return self.settings_win

    def _get_uploader_win(self):
        if self.uploader_win is None:
            self.uploader_win = RoutineUploaderWindow()
        return self.uploader_win

    def _get_selector_win(self):
        if self.selector_win is None:
            self.selector_win = RoutineSelector()
            self.selector_win.routine_selected.connect(self.start_execution)
            self.selector_win.edit_requested.connect(
                lambda path: self._get_uploader_win().load_existing_routine(path))
        return self.selector_win

    def _connect_signals(self):
        self.menu.open_settings.connect(lambda: self._get_settings_win().show())
        self.menu.open_upload.connect(lambda: self._get_uploader_win().show())
        self.menu.open_select.connect(lambda: self._get_selector_win().show())

    # ================================================================ 生命周期

    def run(self):
        log.info("============== Hekili 启动 ==============")
        self.menu.show()
        return self.app.exec()

    def cleanup(self):
        """程序退出前的收尾：确保监听线程已经停下。"""
        if self.input_thread:
            self.input_thread.stop()
            self.input_thread.wait()
            self.input_thread = None

    # ================================================================ 界面刷新

    def refresh_ui(self, is_advance=False):
        """
        把 Director 的最新状态推给悬浮窗。

        :param is_advance: True 走滑动动画；False 瞬间重排（启动/回退/切设备）
        """
        if self.overlay and self.director:
            data = self.director.get_visual_data(preview_count=3)
            # 并行轨：有支线时上方会多出一个小窗，没有就传 None 让它收起
            self.overlay.update_ui(
                data, is_advance=is_advance,
                parallel_slot=self.director.get_parallel_slot(),
                meta=self.director.get_overlay_meta())

    # ================================================================ 流程控制

    def stop_execution(self):
        """停止战斗悬浮窗，返回主菜单。"""
        log.info("正在停止悬浮窗，返回主菜单...")

        # 0. 先停时间轴心跳，避免它继续往即将销毁的界面推数据
        self._tick_timer.stop()
        self._gate_visible = False

        # 1. 先停后台线程，避免它继续往已销毁的界面发信号
        self.is_active = False
        if self.input_thread:
            self.input_thread.stop()
            self.input_thread.wait()
            self.input_thread = None

        # 2. 关掉悬浮窗前，把这局观察到的动作节奏打出来，方便调 timing 配置
        if self.director:
            summary = self.director.timing_summary()
            if summary:
                log.info(f"[Timing] 本局观测到的动作节奏(毫秒)，可填入 config 的 timing.durations_ms: {summary}")

        # 3. 关闭悬浮窗
        if self.overlay:
            self.overlay.close()
            self.overlay.deleteLater()
            self.overlay = None

        self.director = None

        # 4. 回到主菜单
        self.menu.show()

    def _preflight(self, json_path):
        """
        加载前的剧本体检。

        只拦 **error**（会导致崩溃或明显错图的问题），warning 只写日志——
        否则每次进悬浮窗都弹一堆提示，玩家会直接学会无脑点"是"。

        体检本身异常时一律放行：辅助工具的故障不能挡住正常游玩。

        :return: True 表示可以继续加载
        """
        try:
            from tools.checks.routine_lint import lint_routine
            report = lint_routine(json_path, self.asset_mgr)
        except Exception as e:
            log.warning(f"剧本体检跳过（检查器自身异常）: {e}")
            return True

        if not report.errors:
            if report.warnings:
                log.info(f"剧本体检: {len(report.warnings)} 条警告（不影响加载），"
                         f"想看详情运行 tools/routine_lint.py")
            return True

        log.warning(f"剧本体检发现 {len(report.errors)} 个错误")
        shown = "\n".join(i.render().strip() for i in report.errors[:5])
        more = f"\n… 还有 {len(report.errors) - 5} 条" if len(report.errors) > 5 else ""

        answer = QMessageBox.warning(
            self.menu, "剧本有问题",
            f"检测到 {len(report.errors)} 个会导致崩溃或显示错乱的问题：\n\n"
            f"{shown}{more}\n\n"
            f"建议先修好再加载。完整报告：python tools/routine_lint.py <剧本>\n\n"
            f"仍然加载吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def start_execution(self, json_path):
        """加载剧本 JSON 并启动核心链路。"""
        log.info(f"正在加载流程: {json_path}")

        base_dir = os.path.dirname(os.path.abspath(__file__))
        assets_path = os.path.join(base_dir, "assets", "characters")

        # 复用同一个 AssetManager，只清掉旧的路径缓存
        # （素材工厂可能新增了图，每次开新流程重新扫一次最稳妥）
        if self.asset_mgr is None:
            self.asset_mgr = AssetManager(assets_path)
        else:
            self.asset_mgr.clear_cache()

        # 加载前体检：剧本里的引用错误以前只会表现为"图不对"或崩溃，
        # 现在先跑一遍静态检查，把问题用人话列出来让玩家决定。
        if not self._preflight(json_path):
            log.info("用户取消了加载（剧本体检未通过）")
            return

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            log.error(f"剧本加载失败: {e}")
            QMessageBox.critical(self.menu, "加载失败", f"无法读取剧本文件：\n{e}")
            return

        # 实例化导演
        self.director = Director(
            team_config={int(k): v for k, v in data["team_config"].items()},
            opener_script=data["opener_script"],
            loop_script=data["loop_script"],
            start_char_index=data["initial_char_index"],
            asset_mgr=self.asset_mgr
        )

        # 悬浮窗
        self.overlay = HekiliOverlay()
        self.overlay.open_settings_signal.connect(lambda: self._get_settings_win().show())
        self.overlay.return_to_menu_signal.connect(self.stop_execution)
        self.overlay.set_active(False)      # 先以"待命"的样子出现，激活后点亮
        self.overlay.show()

        self.menu.hide()

        # 输入监听线程
        self.input_thread = InputListener()
        self.input_thread.action_detected.connect(self.on_action_detected)
        # 切设备时不用播动画，原地换掉角落的按键图标即可
        self.input_thread.device_switched.connect(lambda name: self.refresh_ui(is_advance=False))
        self.input_thread.start()

        self.refresh_ui(is_advance=False)
        self._tick_timer.start()
        log.info("悬浮窗已就绪，按启动键(X)激活...")

    # ================================================================ 输入回调

    def on_action_detected(self, action_name, is_down, duration=-1.0):
        """
        输入线程发来的动作事件。

        未激活状态下只认启动键；激活后所有非回退动作都交给 Director 判定。

        :param duration: 按住时长（秒），仅 is_down=False 时有意义；-1 表示未知
        """
        if self.director is None:
            return

        # 回退键在任何时候都可用（包括未激活），方便玩家倒带重练
        if is_down and action_name == "rollback":
            if self.director.rollback():
                self.refresh_ui(is_advance=False)
            return

        # 还没启动：只等发令枪
        if not self.is_active:
            if is_down and action_name == "start_trigger":
                self.is_active = True
                log.info("[System] 脚本正式激活！")

                self.director.reset()
                self.refresh_ui(is_advance=False)

                # 面板从"待命"点亮，并在当前格上放一圈金色波纹
                self.overlay.set_active(True)
                self.overlay.play_activate()
            # 未激活时其它按键全部丢弃
            return

        # 已激活：交给状态机判定是否需要推进
        advanced = self.director.input_received(
            action_name, is_down,
            duration=(duration if duration is not None and duration >= 0 else None))
        if advanced:
            self.refresh_ui(is_advance=True)
            return

        # 键按对了、但按的时间不对（该长按却轻点 / 该轻点却按太久）：
        # 不推进，只闪一下红框。没有这个反馈，玩家会以为程序卡住了。
        reason = self.director.last_press_reject
        if reason and self.overlay:
            self.director.last_press_reject = None
            self.overlay.flash_reject(reason)

    def on_tick(self):
        """
        时间轴心跳：把到期的预输入兑现掉，并把动作占位进度画出来。

        为什么需要这一拍
        --------------
        预输入是"按键发生的时刻"和"动作结束的时刻"对不上造成的。按键事件
        不会在动作刚好结束的那一帧到来，所以必须有一个轻量心跳，在闸门打开
        的瞬间去看缓冲里还有没有有效输入。
        """
        if not self.is_active or self.director is None or self.overlay is None:
            return

        # 缓冲兑现（推进了就走滑动动画）
        if self.director.tick():
            self.refresh_ui(is_advance=True)
            return

        # 动作进行中才刷新进度条；已经结束就让它归零一次然后停手，避免空转
        remain, total = self.director.get_gate_state()
        if total > 0 and remain > 0:
            self.overlay.update_gate_progress(remain, total)
            self._gate_visible = True
        elif self._gate_visible:
            self.overlay.update_gate_progress(0.0, 0.0)
            self._gate_visible = False

    def on_config_reload(self):
        """设置界面保存后的回调：热重载按键映射并刷新图标。"""
        if self.input_thread and self.input_thread.isRunning():
            self.input_thread.reload_mapping()
        # 按键映射变了，之前解析出的按键小图路径需要重新确定
        if self.asset_mgr:
            self.asset_mgr.clear_cache()
        if self.overlay:
            self.refresh_ui(is_advance=False)


if __name__ == "__main__":
    # 打包后把工作目录切到 exe 所在位置，保证相对路径正确
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))

    app = QApplication(sys.argv)
    # 菜单被隐藏时不能自动退出，否则启动悬浮窗的瞬间程序就结束了
    app.setQuitOnLastWindowClosed(False)
    # 全局字体：Segoe UI + 微软雅黑，QSS 没覆盖到的地方（比如系统对话框）也保持一致
    app.setFont(theme.font(13))
    # 外观：夜间（默认）/ 日间，在设置窗里可以随时切，这里只负责开机时恢复
    theme.apply(config.get("settings.theme", "dark"))

    controller = HekiliApp(app)
    ret_code = controller.run()
    controller.cleanup()
    sys.exit(ret_code)
