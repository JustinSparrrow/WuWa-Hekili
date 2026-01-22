import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from utils.asset_manager import AssetManager
from utils.input_listener import InputListener
from core.preset.director import Director
from ui.overlay_window import HekiliOverlay
from configs.team_gabriella_lupa_moning import TEAM_CONFIG, OPENER_SCRIPT, LOOP_SCRIPT, INITIAL_CHAR_INDEX


def main():
    app = QApplication(sys.argv)

    # 1. 初始化逻辑
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

    is_active = False

    def refresh_ui():
        data = director.get_visual_data(preview_count=3)
        window.update_ui(data)

    refresh_ui()

    # 3. 输入处理逻辑
    def on_action(action_name, is_down):
        nonlocal is_active

        # === 核心：X 键 (start_trigger) 逻辑 ===
        if is_down and action_name == "start_trigger":
            # 无论是否已激活，按 X 键统统重置到起手轴开头
            director.reset()
            is_active = True
            # 给 UI 一个激活反馈边框 (金色)
            window.slot_current.setStyleSheet(
                "ActionWidget { border: 4px solid #FFD700; background-color: rgba(0,0,0,180); }")
            refresh_ui()
            return

        # 如果未按 X 激活，则忽略其他所有输入
        if not is_active:
            return

        # 正常连招判定
        if director.input_received(action_name, is_down):
            refresh_ui()

    # 4. 时间驱动跳转
    def timer_tick():
        if is_active and director.check_auto_advance():
            refresh_ui()

    heartbeat_timer = QTimer()
    heartbeat_timer.timeout.connect(timer_tick)
    heartbeat_timer.start(50)

    # 5. 启动监听
    input_thread = InputListener()
    input_thread.action_detected.connect(on_action)
    input_thread.start()

    # 静默启动
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
