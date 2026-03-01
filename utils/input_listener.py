import pygame
import keyboard
import ctypes
from PySide6.QtCore import QThread, Signal
from utils.config_manager import config


class InputListener(QThread):
    action_detected = Signal(str, bool)

    def __init__(self):
        super().__init__()
        self.running = True
        self.joystick = None

        self.button_id_to_action = {}
        self.hat_val_to_action = {}
        self.axis_id_to_action = {}
        self.axis_states = {}

        self.key_to_action = {}
        self.mouse_to_action = {}
        self.mouse_states = {"left": False, "right": False, "middle": False}

        # 纯硬件探测（用于调试）
        self._raw_mouse_left = False

        self._build_lookup_table()

    def _build_lookup_table(self):
        print("\n🔍 --- 正在构建输入映射表 ---")

        # 1. 手柄映射 (略过日志)
        action_map_xbox = config.get("keymaps.xbox", {})
        physical_to_action_xbox = {v: k for k, v in action_map_xbox.items()}
        hw_map = config.get("controller.hardware_mapping", {})
        for k, v in hw_map.items():
            if v in physical_to_action_xbox: self.button_id_to_action[int(k)] = physical_to_action_xbox[v]
        hat_map = config.get("controller.hat_mapping", {})
        for val_str, phy_name in hat_map.items():
            if phy_name in physical_to_action_xbox: self.hat_val_to_action[val_str] = physical_to_action_xbox[phy_name]
        axis_map = config.get("controller.axis_mapping", {})
        for axis_id_str, phy_name in axis_map.items():
            if phy_name in physical_to_action_xbox: self.axis_id_to_action[int(axis_id_str)] = physical_to_action_xbox[
                phy_name]

        # 2. 键鼠映射
        action_map_kb = config.get("keymaps.keyboard", {})
        print(f"📄 当前 config.json 中记录的键盘配置: {action_map_kb}")

        for action, filename in action_map_kb.items():
            # 💡 修复点 1：匹配前缀改为 "keyboard_"
            if filename.startswith("keyboard_"):
                # 提取真实按键名：去掉前缀 (例如 "keyboard_f" -> "f")
                # 如果你的图标带后缀比如 "keyboard_f_outline"，也顺便去掉
                real_key = filename.replace("keyboard_", "").replace("_outline", "")

                self.key_to_action[real_key.lower()] = action
                print(f"   ⌨️ 成功绑定: 键盘 [{real_key.lower()}] -> {action}")

            elif filename.startswith("mouse_"):
                if "left" in filename:
                    self.mouse_to_action["left"] = action
                    print(f"   🖱️ 成功绑定: 鼠标左键 -> {action}")
                elif "right" in filename:
                    self.mouse_to_action["right"] = action
                    print(f"   🖱️ 成功绑定: 鼠标右键 -> {action}")
                elif "middle" in filename:
                    self.mouse_to_action["middle"] = action
                    print(f"   🖱️ 成功绑定: 鼠标中键 -> {action}")

        print(f"🔍 --- 映射构建完毕 ---\n")

    def reload_mapping(self):
        self.button_id_to_action.clear()
        self.hat_val_to_action.clear()
        self.axis_id_to_action.clear()
        self.key_to_action.clear()
        self.mouse_to_action.clear()
        self._build_lookup_table()

    def _switch_device_mode(self, device_name):
        current = config.get("settings.current_device")
        if current != device_name:
            config.update_setting("settings.current_device", device_name)

    def _on_keyboard_event(self, event):
        if not self.running: return
        action = self.key_to_action.get(event.name.lower())
        if action:
            self._switch_device_mode("keyboard")
            if event.event_type == "down":
                self.action_detected.emit(action, True)
            elif event.event_type == "up":
                self.action_detected.emit(action, False)

    def run(self):
        pygame.init()
        pygame.joystick.init()
        keyboard.hook(self._on_keyboard_event)

        mouse_vk_codes = {
            "left": 0x01,
            "right": 0x02,
            "middle": 0x04
        }

        while self.running:
            # === 硬件级鼠标探测 ===
            raw_left_state = ctypes.windll.user32.GetAsyncKeyState(0x01)
            is_raw_left_pressed = (raw_left_state & 0x8000) != 0
            if is_raw_left_pressed and not self._raw_mouse_left:
                # print("⚡ [HARDWARE] 检测到鼠标左键被物理按下！") # 这一行如果没打印，说明系统坏了
                self._raw_mouse_left = True
            elif not is_raw_left_pressed and self._raw_mouse_left:
                self._raw_mouse_left = False

            # === 逻辑级鼠标轮询 ===
            for btn_name, vk_code in mouse_vk_codes.items():
                action = self.mouse_to_action.get(btn_name)

                # 就算 action 是 None，硬件状态也在读取
                state = ctypes.windll.user32.GetAsyncKeyState(vk_code)
                is_pressed = (state & 0x8000) != 0
                was_pressed = self.mouse_states[btn_name]

                if is_pressed and not was_pressed:
                    self.mouse_states[btn_name] = True
                    if action:
                        self._switch_device_mode("keyboard")
                        self.action_detected.emit(action, True)

                elif not is_pressed and was_pressed:
                    self.mouse_states[btn_name] = False
                    if action:
                        self.action_detected.emit(action, False)

            # === 手柄逻辑 (略) ===
            if pygame.joystick.get_count() > 0 and self.joystick is None:
                try:
                    self.joystick = pygame.joystick.Joystick(0)
                    self.joystick.init()
                except:
                    pass

            if self.joystick:
                for event in pygame.event.get():
                    if event.type == pygame.JOYBUTTONDOWN:
                        action = self.button_id_to_action.get(event.button)
                        if action:
                            self._switch_device_mode("xbox")
                            self.action_detected.emit(action, True)
                    elif event.type == pygame.JOYBUTTONUP:
                        action = self.button_id_to_action.get(event.button)
                        if action: self.action_detected.emit(action, False)
                    elif event.type == pygame.JOYAXISMOTION:
                        action = self.axis_id_to_action.get(event.axis)
                        if action:
                            val = event.value
                            was_pressed = self.axis_states.get(event.axis, False)
                            if val > 0.6: self._switch_device_mode("xbox")
                            if val > 0.6 and not was_pressed:
                                self.axis_states[event.axis] = True
                                self.action_detected.emit(action, True)
                            elif val < 0.3 and was_pressed:
                                self.axis_states[event.axis] = False
                                self.action_detected.emit(action, False)
                    elif event.type == pygame.JOYHATMOTION:
                        val_str = f"{event.value[0]},{event.value[1]}"
                        action = self.hat_val_to_action.get(val_str)
                        if action:
                            self._switch_device_mode("xbox")
                            self.action_detected.emit(action, True)

            self.msleep(5)

    def stop(self):
        self.running = False
        keyboard.unhook_all()
        pygame.quit()
        self.wait()