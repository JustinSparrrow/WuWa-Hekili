import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from utils.asset_manager import AssetManager
from utils.input_listener import InputListener  # <-- 导入新写的监听器
from core.preset.director import Director
from ui.overlay_window import HekiliOverlay
from configs.team_gabriella_lupa_moning import TEAM_CONFIG, OPENER_SCRIPT, LOOP_SCRIPT, INITIAL_CHAR_INDEX


def main():
    app = QApplication(sys.argv)

    # 1. 资源与逻辑初始化
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

    # 2. UI 初始化
    window = HekiliOverlay()
    window.show()

    # 3. 核心刷新函数
    def refresh_ui():
        data = director.get_visual_data(preview_count=3)
        window.update_ui(data)

    # 先刷第一帧
    refresh_ui()

    # 4. 启动手柄监听线程
    # ------------------------------------------------
    input_thread = InputListener()

    # 定义回调：当收到信号时执行什么
    def on_action(action_name, is_down):
        # 导演现在需要知道是按下还是松开
        success = director.input_received(action_name, is_down)
        if success:
            refresh_ui()

    # 2. ✨ 新增：处理“时间驱动”的自动跳转
    def timer_tick():
        # 问导演：时间到了吗？
        if director.check_auto_advance():
            # 如果是因为时间到了而跳转的，刷新 UI
            refresh_ui()

    # 3. 启动心跳定时器 (每 50 毫秒检查一次)
    heartbeat_timer = QTimer()
    heartbeat_timer.timeout.connect(timer_tick)
    heartbeat_timer.start(50)

    # 连接信号与槽
    input_thread.action_detected.connect(on_action)

    # 线程启动！
    input_thread.start()
    # ------------------------------------------------

    print("✅ 系统已启动，请按手柄操作...")

    ret = app.exec()

    # 程序退出时，停止线程
    input_thread.stop()
    sys.exit(ret)


if __name__ == "__main__":
    main()