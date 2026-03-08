import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

# 导入 UI
from ui.start_menu import StartMenu
from ui.overlay_window import HekiliOverlay
from ui.settings_window import SettingsWindow

# 导入逻辑核心
from utils.asset_manager import AssetManager
from utils.input_listener import InputListener
from utils.logger import log
from core.preset.director import Director

# 导入默认剧本 (未来这里应该由"流程选择"动态加载)
from configs.team_gabriella_lupa_moning import TEAM_CONFIG, OPENER_SCRIPT, LOOP_SCRIPT, INITIAL_CHAR_INDEX


def main():
    app = QApplication(sys.argv)

    # ==========================================
    # 1. 全局变量占位 (初始化为 None)
    # ==========================================
    window = None
    director = None
    input_thread = None
    heartbeat_timer = None
    is_active = False

    # ==========================================
    # 2. 初始化 菜单 和 设置窗口
    # ==========================================
    menu = StartMenu()
    settings_win = SettingsWindow()

    # ==========================================
    # 3. 定义核心逻辑 (闭包函数)
    # ==========================================

    # 💡 修改 1：增加 is_advance 参数
    def refresh_ui(is_advance=False):
        """刷新悬浮窗 UI"""
        if window and director:
            data = director.get_visual_data(preview_count=3)
            # 传给 UI 引擎，决定是播放动画还是瞬间对齐
            window.update_ui(data, is_advance=is_advance)

    log.info("============== 🚀 Hekili 启动 ==============")

    def start_execution():
        log.info("正在初始化核心逻辑...")
        nonlocal window, director, input_thread, heartbeat_timer, is_active

        print("🚀 正在初始化核心逻辑...")

        # A. 隐藏菜单
        menu.hide()

        # B. 初始化资源与导演
        base_dir = os.path.dirname(os.path.abspath(__file__))
        assets_path = os.path.join(base_dir, "assets", "assets")
        asset_mgr = AssetManager(assets_path)

        director = Director(
            team_config=TEAM_CONFIG,
            opener_script=OPENER_SCRIPT,
            loop_script=LOOP_SCRIPT,
            start_char_index=INITIAL_CHAR_INDEX,
            asset_mgr=asset_mgr
        )

        # C. 初始化并显示悬浮窗
        window = HekiliOverlay()
        window.open_settings_signal.connect(settings_win.show)
        window.show()

        # D. 定义交互回调
        def on_action(action_name, is_down):
            nonlocal is_active

            if not is_active:
                if is_down and action_name == "start_trigger":
                    is_active = True
                    log.info("✅ 脚本正式激活！(触发了 start_trigger)")
                    window.slot_current.setStyleSheet("ActionWidget { border: 4px solid #00FF00; }")
                    director.reset()
                    refresh_ui(is_advance=False)
                else:
                    if is_down:
                        log.debug(f"尚未激活，忽略输入: {action_name}")
                return

            # 如果已激活
            if is_down:
                log.debug(f"🎮 收到输入: {action_name}")

            # 导演判定
            success = director.input_received(action_name, is_down)
            if success:
                log.info(f"✅ 动作执行成功: {action_name}")
                refresh_ui(is_advance=True)
            elif is_down:
                # 判定失败，记录案发现场
                expected_type = director.get_current_script()[director.step_index].get("type")
                variant = director.get_current_script()[director.step_index].get("variant", "")
                log.warning(f"❌ 动作错误: 期待 {expected_type}({variant})，实际收到 {action_name}")

        def timer_tick():
            if is_active and director.check_auto_advance():
                log.info("⏱️ 长按时间达标，自动推进！")
                refresh_ui(is_advance=True)

        log.info("✅ 悬浮窗已启动，等待激活按键...")

        heartbeat_timer = QTimer()
        heartbeat_timer.timeout.connect(timer_tick)
        heartbeat_timer.start(50)

        # G. 启动监听线程
        input_thread = InputListener()
        input_thread.action_detected.connect(on_action)
        input_thread.start()

        # 💡 修改 5：开机第一眼看到的画面，静态铺好
        refresh_ui(is_advance=False)
        print("✅ 悬浮窗已启动，请按启动键(X)激活...")

    # ==========================================
    # 4. 连接设置相关信号
    # ==========================================

    def on_config_reload():
        print("🔄 [System] 配置已修改，正在重载...")
        if input_thread and input_thread.isRunning():
            input_thread.reload_mapping()

        if window:
            # 💡 修改 6：设置改完后，图标可能会变，瞬间刷新不要动画
            refresh_ui(is_advance=False)

    settings_win.config_saved.connect(on_config_reload)

    # ==========================================
    # 5. 连接菜单按钮信号
    # ==========================================

    def show_settings():
        print("🔘 打开设置窗口")
        settings_win.show()

    def show_upload():
        print("🔘 [TODO] 流程上传功能开发中...")

    def show_select_routine():
        print("🔘 选择默认流程 -> 启动悬浮窗")
        start_execution()

    menu.open_settings.connect(show_settings)
    menu.open_upload.connect(show_upload)
    menu.open_select.connect(show_select_routine)

    # ==========================================
    # 6. 启动程序
    # ==========================================
    menu.show()

    ret = app.exec()

    if input_thread:
        input_thread.stop()
    sys.exit(ret)


if __name__ == "__main__":
    main()