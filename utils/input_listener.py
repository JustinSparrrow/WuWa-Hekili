import ctypes
import time

import keyboard
import pygame
from PySide6.QtCore import QThread, Signal

from utils.config_manager import config
from utils.logger import log


class InputListener(QThread):
    """
    全局输入监听线程。

    三路输入统一抽象成「动作名 + 是否按下 + 按住时长」：
      - 手柄：pygame 事件循环（按键 / 线性扳机 / 十字键）
      - 键盘：keyboard 库的全局钩子（事件驱动，无轮询开销）
      - 鼠标：Win32 GetAsyncKeyState 轮询（keyboard 库不覆盖鼠标）

    线程模型：本类跑在独立 QThread 中，通过 Qt 信号把动作发给主线程的
    Director，跨线程 emit 由 Qt 自动排队，不需要加锁。

    为什么"按住时长"在**这一层**测量（v1.2）
    -------------------------------------
    以前这一层只上报"按下/松开"两个布尔值，时长由 Director 自己在主线程里
    记时间戳。但信号是排队投递的：主线程一忙（比如正在重排悬浮窗），
    按下和松开两个事件会一起晚到，时间戳就被主线程的卡顿污染了。
    监听线程是事件发生的第一现场，在这里打时间戳最准，所以把测量搬到这里，
    Director 只负责"裁决这个时长算不算数"。

    职责由此变得很干净：
        InputListener —— 测量（记录按下时刻，松手时算出时长）
        Director      —— 裁决（依据剧本要求判断手势是否合规）

    信号签名
    --------
        action_detected(str action, bool is_down, float duration)
            duration 只在 is_down=False 时有意义，单位秒；
            拿不到按下记录时给 -1.0（让 Director 自己决定怎么处理）。

    v1.1/v1.2 优化点
    ---------------
    1. 轮询间隔 10ms（100Hz），高于游戏 60fps 的帧间隔，判定精度无损，
       但待机 CPU 只有原来 200Hz 空转的一半。
    2. 修正十字键映射读错配置键（代码读 `controller.hats`，config.json 里
       实际叫 `controller.hat_`），此前一直靠字符串兜底才勉强生效。
    3. 删除 `_build_lookup_table` 中整段重复的映射分支。
    4. 退出时只移除自己注册的键盘钩子，不再 `unhook_all()` 误伤其它程序。
    5. 启动瞬间先同步一次鼠标真实状态，避免"进来时正按着左键"被误判成点击。
    6. 按键自动重复去重：Windows 对按住不放的键会持续产生 keydown，
       现在只在第一次按下时上报，否则长按会被当成连续点击。
    7. 十字键补上"松开"事件（hat 回中时上报 up），此前只有 down 没有 up。
    """

    action_detected = Signal(str, bool, float)   # (动作名, 是否按下, 按住时长秒)
    device_switched = Signal(str)                # (设备名)

    # 轮询间隔(ms)：100Hz，兼顾响应与 CPU
    POLL_INTERVAL_MS = 10
    # 设备热切换防抖：0.5s 内不重复切换
    DEVICE_SWITCH_COOLDOWN = 0.5
    # 扳机(轴)判定阈值：按下/松开用不同阈值形成回差，避免抖动重复触发
    AXIS_PRESS_THRESHOLD = 0.6
    AXIS_RELEASE_THRESHOLD = 0.3

    # 鼠标左右中键的 Win32 虚拟键码
    MOUSE_VK_CODES = {"left": 0x01, "right": 0x02, "middle": 0x04}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = True
        self.joystick = None
        self.last_device_switch_time = 0.0

        # 硬件 ID -> 动作名 的查找表
        self.button_id_to_action = {}
        self.hat_val_to_action = {}
        self.axis_id_to_action = {}
        self.axis_states = {}

        self.key_to_action = {}
        self.mouse_to_action = {}
        self.mouse_states = {"left": False, "right": False, "middle": False}

        self._keyboard_hook = None

        # 动作名 -> 按下时刻（time.monotonic），松手时取出算时长
        self._press_start = {}
        # 十字键当前按着的是哪个动作（hat 回中时要补一个 up 事件）
        self._hat_action = None

        self._build_lookup_table()

    # ============================================================ 映射表构建

    def _build_lookup_table(self):
        """把 config 里的按键图片名翻译成 hardware id -> action 的查找表。"""
        log.info("--- 正在构建双端输入映射表 ---")

        ctrl_buttons = config.get("controller.buttons", {}) or {}
        ctrl_axes = config.get("controller.axes", {}) or {}
        # 兼容历史拼写：config.json 里这个键叫 hat_，早期代码读的是 hats
        ctrl_hats = config.get("controller.hats") or config.get("controller.hat_") or {}

        # 十字键兜底表：万一 config 里没有 hat 段，按图片名反推
        dpad_fallback = {
            "dpad_up": "0,1",
            "dpad_down": "0,-1",
            "dpad_left": "-1,0",
            "dpad_right": "1,0",
        }

        for action, filename in (config.get("keymaps.xbox", {}) or {}).items():
            if not filename:
                continue

            # 从 "xbox_button_color_b.png" 这类文件名里提取核心键名 -> "b"
            core_key = (filename
                        .replace("xbox_button_color_", "")
                        .replace("xbox_button_", "")
                        .replace("xbox_", "")
                        .split(".")[0]
                        .lower())

            if core_key in ctrl_buttons:
                self.button_id_to_action[int(ctrl_buttons[core_key])] = action
            elif core_key in ctrl_axes:
                # LT/RT 在 pygame 里是轴而非按键
                self.axis_id_to_action[ctrl_axes[core_key]] = action
            elif core_key in ctrl_hats:
                self.hat_val_to_action[ctrl_hats[core_key]] = action
            else:
                matched = False
                for dpad_key, hat_val in dpad_fallback.items():
                    if dpad_key in filename:
                        self.hat_val_to_action[hat_val] = action
                        matched = True
                        break
                if not matched:
                    log.warning(f"手柄映射无法识别: '{filename}'")

        for action, filename in (config.get("keymaps.keyboard", {}) or {}).items():
            if not filename:
                continue

            if filename.startswith("key_") or filename.startswith("keyboard_"):
                # "keyboard_f" -> "f"   "key_space" -> "space"
                real_key = filename.replace("key_", "").replace("keyboard_", "").split("_")[0]
                self.key_to_action[real_key.lower()] = action

            elif filename.startswith("mouse_"):
                for btn in ("left", "right", "middle"):
                    if btn in filename:
                        self.mouse_to_action[btn] = action
                        break

        log.info(f"监听就绪: 手柄({len(self.button_id_to_action)}键/{len(self.axis_id_to_action)}轴) "
                 f"| 键盘({len(self.key_to_action)}键) | 鼠标({len(self.mouse_to_action)}键)")

    def reload_mapping(self):
        """设置界面保存后调用，热重载按键映射。"""
        log.info("[Listener] 正在重载按键映射...")
        self.button_id_to_action.clear()
        self.hat_val_to_action.clear()
        self.axis_id_to_action.clear()
        self.key_to_action.clear()
        self.mouse_to_action.clear()
        self._build_lookup_table()

    # ========================================================== 时长测量与上报

    def _emit_down(self, action):
        """
        上报一次"按下"，并开始计时。

        Windows 的键盘钩子对按住不放的键会反复送来 keydown（自动重复），
        如果每个都上报，长按就会被下游当成连续点击。所以这里做幂等：
        已经处于按下状态的动作，重复的 down 直接丢掉。

        :return: True 表示这是本次按压的第一次按下
        """
        if action in self._press_start:
            return False
        self._press_start[action] = time.monotonic()
        self.action_detected.emit(action, True, -1.0)
        return True

    def _emit_up(self, action):
        """上报一次"松开"，同时把按住时长一起带出去。"""
        start = self._press_start.pop(action, None)
        duration = -1.0
        if start is not None:
            duration = max(0.0, time.monotonic() - start)
        self.action_detected.emit(action, False, duration)

    def reset(self):
        """清空所有按压记录（停止监听前调用，避免残留状态跨会话）。"""
        self._press_start.clear()
        self._hat_action = None

    # ================================================================ 设备切换

    def _switch_device_mode(self, device_name):
        """
        键鼠 <-> 手柄 自动热切换。

        注意：这里会写 config.json，所以加了冷却时间，避免频繁写盘。
        """
        current = config.get("settings.current_device")
        if current == device_name:
            return

        now = time.time()
        if now - self.last_device_switch_time < self.DEVICE_SWITCH_COOLDOWN:
            return

        log.info(f"检测到输入源切换: {current} -> {device_name}")
        config.update_setting("settings.current_device", device_name)
        self.device_switched.emit(device_name)
        self.last_device_switch_time = now

    # ================================================================== 键盘

    def _on_keyboard_event(self, event):
        """keyboard 库的全局钩子回调（运行在 keyboard 自己的线程）。"""
        if not self.running:
            return

        action = self.key_to_action.get(event.name.lower())
        if not action:
            return

        if event.event_type == "down":
            self._switch_device_mode("keyboard")
            self._emit_down(action)
        elif event.event_type == "up":
            self._emit_up(action)

    # ================================================================== 鼠标

    def _sync_mouse_state(self):
        """启动时对齐一次真实状态，防止"启动瞬间正按着键"被当成一次按下。"""
        for btn_name, vk_code in self.MOUSE_VK_CODES.items():
            state = ctypes.windll.user32.GetAsyncKeyState(vk_code)
            self.mouse_states[btn_name] = bool(state & 0x8000)

    def _poll_mouse(self):
        """
        轮询鼠标按键，边沿触发（只在状态翻转时发信号）。

        Windows 下 GetAsyncKeyState 无法注册回调，只能轮询；
        100Hz 的采样率对"按键->引脚"的判定完全够用。
        """
        for btn_name, vk_code in self.MOUSE_VK_CODES.items():
            action = self.mouse_to_action.get(btn_name)
            state = ctypes.windll.user32.GetAsyncKeyState(vk_code)
            is_pressed = (state & 0x8000) != 0
            was_pressed = self.mouse_states[btn_name]

            if is_pressed and not was_pressed:
                self.mouse_states[btn_name] = True
                if action:
                    self._switch_device_mode("keyboard")
                    self._emit_down(action)
            elif not is_pressed and was_pressed:
                self.mouse_states[btn_name] = False
                if action:
                    self._emit_up(action)

    # ================================================================== 手柄

    def _ensure_joystick(self):
        """懒连接手柄：热插拔后也能自动认到。"""
        if self.joystick is not None or pygame.joystick.get_count() <= 0:
            return
        try:
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
            log.info(f"[Listener] 已连接手柄: {self.joystick.get_name()}")
        except Exception as e:
            self.joystick = None
            log.warning(f"手柄初始化失败: {e}")

    def _poll_joystick(self):
        """处理 pygame 事件队列里的按键 / 轴 / 十字键变化。"""
        if self.joystick is None:
            return

        for event in pygame.event.get():
            if event.type == pygame.JOYBUTTONDOWN:
                action = self.button_id_to_action.get(event.button)
                if action:
                    self._switch_device_mode("xbox")
                    self._emit_down(action)

            elif event.type == pygame.JOYBUTTONUP:
                action = self.button_id_to_action.get(event.button)
                if action:
                    self._emit_up(action)

            elif event.type == pygame.JOYAXISMOTION:
                action = self.axis_id_to_action.get(event.axis)
                if not action:
                    continue
                val = event.value
                was_pressed = self.axis_states.get(event.axis, False)

                if val > self.AXIS_PRESS_THRESHOLD:
                    self._switch_device_mode("xbox")
                    if not was_pressed:
                        self.axis_states[event.axis] = True
                        self._emit_down(action)
                elif val < self.AXIS_RELEASE_THRESHOLD and was_pressed:
                    self.axis_states[event.axis] = False
                    self._emit_up(action)

            elif event.type == pygame.JOYHATMOTION:
                # hat 回到 (0,0) 就是松手，必须补一个 up，
                # 否则按下记录永远不会清掉，下一次按同一个方向会被当成重复按下。
                if self._hat_action:
                    self._emit_up(self._hat_action)
                    self._hat_action = None

                if event.value == (0, 0):
                    continue

                hat_val = f"{event.value[0]},{event.value[1]}"
                action = self.hat_val_to_action.get(hat_val)
                if action:
                    self._switch_device_mode("xbox")
                    self._hat_action = action
                    self._emit_down(action)

    # ================================================================== 主循环

    def run(self):
        pygame.init()
        pygame.joystick.init()

        self._keyboard_hook = keyboard.hook(self._on_keyboard_event)
        self._sync_mouse_state()
        log.info("[Listener] 全局监听已启动...")

        try:
            while self.running:
                self._poll_mouse()
                self._ensure_joystick()
                self._poll_joystick()
                self.msleep(self.POLL_INTERVAL_MS)
        finally:
            # 线程退出时统一回收资源，避免 stop() 与 run() 在不同线程争用
            try:
                if self._keyboard_hook is not None:
                    keyboard.unhook(self._keyboard_hook)
                    self._keyboard_hook = None
            except Exception:
                pass
            try:
                pygame.quit()
            except Exception:
                pass
            self.reset()
            log.info("[Listener] 全局监听已停止")

    def stop(self):
        """
        请求停止监听。

        实际资源释放放在 run() 的 finally 里，这里只负责放下运行标志；
        调用方随后用 wait() 等线程安全退出。
        """
        self.running = False
