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
from core.preset.director import Director

# 导入默认剧本 (未来这里应该由"流程选择"动态加载)
from configs.team_gabriella_lupa_moning import TEAM_CONFIG, OPENER_SCRIPT, LOOP_SCRIPT, INITIAL_CHAR_INDEX


def main():
    app = QApplication(sys.argv)

    # ==========================================
    # 1. 全局变量占位 (初始化为 None)
    # ==========================================
    # 这些变量只有在点击"开始"后才会被赋值
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

    def refresh_ui():
        """刷新悬浮窗 UI"""
        if window and director:
            data = director.get_visual_data(preview_count=3)
            window.update_ui(data)

    def start_execution():
        """
        【核心启动函数】
        当在菜单点击"流程选择"(暂代开始键)时调用
        负责：隐藏菜单 -> 加载资源 -> 显示悬浮窗 -> 启动监听
        """
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
        # 把设置信号连回去 (允许在悬浮窗右键打开设置)
        window.open_settings_signal.connect(settings_win.show)
        window.show()

        # D. 定义交互回调 (Action Handler)
        def on_action(action_name, is_down):
            nonlocal is_active

            # --- 激活逻辑 ---
            if not is_active:
                if is_down and action_name == "start_trigger":
                    is_active = True
                    print("🚀 [System] 脚本正式激活！")
                    window.slot_current.setStyleSheet("ActionWidget { border: 4px solid #00FF00; }")
                    director.reset()  # 确保重置
                    refresh_ui()
                return

            # --- 运行逻辑 ---
            if is_down:
                print(f"🎮 输入: {action_name}")

            if director.input_received(action_name, is_down):
                refresh_ui()

        # E. 定义时间回调 (Timer)
        def timer_tick():
            if is_active and director.check_auto_advance():
                refresh_ui()

        # F. 启动定时器
        heartbeat_timer = QTimer()
        heartbeat_timer.timeout.connect(timer_tick)
        heartbeat_timer.start(50)

        # G. 启动监听线程
        input_thread = InputListener()
        input_thread.action_detected.connect(on_action)
        input_thread.start()

        # 初始刷新一下
        refresh_ui()
        print("✅ 悬浮窗已启动，请按 X 激活...")

    # ==========================================
    # 4. 连接设置相关信号
    # ==========================================

    def on_config_reload():
        print("🔄 [System] 配置已修改，正在重载...")
        # 只有当监听器已经运行时，才需要热重载
        if input_thread and input_thread.isRunning():
            input_thread.reload_mapping()

        # 如果悬浮窗已经显示，刷新一下图标
        if window:
            refresh_ui()

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
        # 目前暂时把"流程选择"按钮当作"开始运行"按钮
        print("🔘 选择默认流程 -> 启动悬浮窗")
        start_execution()

    menu.open_settings.connect(show_settings)
    menu.open_upload.connect(show_upload)
    menu.open_select.connect(show_select_routine)  # 👈 这里连接启动逻辑

    # ==========================================
    # 6. 启动程序
    # ==========================================
    menu.show()  # 只显示菜单

    ret = app.exec()

    # 退出清理
    if input_thread:
        input_thread.stop()
    sys.exit(ret)


if __name__ == "__main__":
    main()