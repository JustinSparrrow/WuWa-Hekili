import pygame
from PySide6.QtCore import QThread, Signal
from utils.config_manager import config


class InputListener(QThread):
    # ✅ 信号定义：动作名 (str), 是否按下 (bool)
    action_detected = Signal(str, bool)

    def __init__(self):
        super().__init__()
        self.running = True
        self.joystick = None

        # 缓存映射表
        self.button_id_to_action = {}
        self.hat_val_to_action = {}
        self.axis_id_to_action = {}
        self.axis_states = {}  # 记录轴的状态 (LT/RT)

        self._build_lookup_table()

    def _build_lookup_table(self):
        device = config.get("settings.current_device", "xbox")
        action_map = config.get(f"keymaps.{device}", {})
        physical_to_action = {v: k for k, v in action_map.items()}

        # 1. Button 映射
        hw_map = config.get("controller.hardware_mapping", {})
        for btn_id_str, phy_name in hw_map.items():
            if phy_name in physical_to_action:
                self.button_id_to_action[int(btn_id_str)] = physical_to_action[phy_name]

        # 2. Hat (D-Pad) 映射
        hat_map = config.get("controller.hat_mapping", {})
        for val_str, phy_name in hat_map.items():
            if phy_name in physical_to_action:
                self.hat_val_to_action[val_str] = physical_to_action[phy_name]

        # 3. Axis (LT/RT) 映射
        axis_map = config.get("controller.axis_mapping", {})
        for axis_id_str, phy_name in axis_map.items():
            if phy_name in physical_to_action:
                self.axis_id_to_action[int(axis_id_str)] = physical_to_action[phy_name]

        print(f"🎮 输入监听已就绪 (设备: {device})")

    def run(self):
        pygame.init()
        pygame.joystick.init()

        while self.running:
            if pygame.joystick.get_count() > 0 and self.joystick is None:
                self.joystick = pygame.joystick.Joystick(0)
                self.joystick.init()
                print(f"✅ [Listener] 已连接: {self.joystick.get_name()}")

            elif pygame.joystick.get_count() == 0 and self.joystick is not None:
                self.joystick = None
                print("⚠️ [Listener] 手柄已断开")

            if self.joystick:
                for event in pygame.event.get():
                    # --- 1. 处理普通按键按下 ---
                    if event.type == pygame.JOYBUTTONDOWN:
                        action = self.button_id_to_action.get(event.button)
                        if action:
                            # ✅ 修正：传入两个参数 (动作名, True)
                            self.action_detected.emit(action, True)

                    # --- 2. 处理普通按键松开 ---
                    elif event.type == pygame.JOYBUTTONUP:
                        action = self.button_id_to_action.get(event.button)
                        if action:
                            # ✅ 修正：传入两个参数 (动作名, False)
                            self.action_detected.emit(action, False)

                    # --- 3. 处理轴 (LT/RT 扳机键) ---
                    elif event.type == pygame.JOYAXISMOTION:
                        action = self.axis_id_to_action.get(event.axis)
                        if action:
                            is_pressed = event.value > 0.5
                            was_pressed = self.axis_states.get(event.axis, False)

                            if is_pressed and not was_pressed:
                                # 触发按下信号
                                self.action_detected.emit(action, True)
                            elif not is_pressed and was_pressed:
                                # 触发松开信号
                                self.action_detected.emit(action, False)

                            self.axis_states[event.axis] = is_pressed

                    # --- 4. 处理十字键 (D-Pad) ---
                    elif event.type == pygame.JOYHATMOTION:
                        val_str = f"{event.value[0]},{event.value[1]}"
                        action = self.hat_val_to_action.get(val_str)
                        if action:
                            # 十字键切人通常不需要长按，但为了逻辑一致性，也传 True
                            self.action_detected.emit(action, True)
                        elif event.value == (0, 0):
                            # 这里可以处理松开十字键，如果需要的话
                            pass

            self.msleep(5)

    def stop(self):
        self.running = False
        pygame.quit()
        self.wait()