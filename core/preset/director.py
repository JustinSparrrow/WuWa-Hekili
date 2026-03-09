import time
from utils.config_manager import config
from utils.logger import log


class Director:
    def __init__(self, team_config, opener_script, loop_script, start_char_index, asset_mgr):
        self.team = team_config
        self.opener = opener_script
        self.loop = loop_script
        self.asset_mgr = asset_mgr
        self.is_in_opener = True
        self.step_index = 0
        self.current_char_idx = start_char_index

        self.is_holding = False
        self.button_press_start_time = 0
        self.heavy_threshold = config.get("settings.heavy_hold_time", 0.5)

        if not self.opener:
            self.is_in_opener = False

    def get_current_script(self):
        return self.opener if self.is_in_opener else self.loop

    def get_visual_data(self, preview_count=3):
        # 此处保持不变，略去了中间的代码以防你看花眼
        # 请保留你原本的 get_visual_data 逻辑
        result = []
        sim_in_opener = self.is_in_opener
        sim_step_idx = self.step_index
        virtual_char_idx = self.current_char_idx

        for i in range(preview_count):
            current_script = self.opener if sim_in_opener else self.loop
            if not current_script: break
            action = current_script[sim_step_idx]

            action_type = action.get("type")
            variant = action.get("variant")
            desc = action.get("desc", "")
            f_gen = action.get("force_general", False)
            c_icon = action.get("custom_icon")

            display_char_idx = virtual_char_idx
            target_idx_arg = None
            if action_type == "intro":
                next_char = action.get("next_char")
                if next_char:
                    virtual_char_idx = next_char
                    display_char_idx = next_char
                    target_idx_arg = next_char

            char_name = self.team.get(display_char_idx, "Unknown")
            icon_path = self.asset_mgr.get_icon_path(char_name, action_type, variant, f_gen, c_icon)
            btn_path = self.asset_mgr.get_button_path(action_type, target_index=target_idx_arg)

            result.append({
                "desc": desc, "icon_path": icon_path, "btn_path": btn_path,
                "variant": variant, "char_name": char_name, "is_current": (i == 0)
            })

            sim_step_idx += 1
            if sim_in_opener and sim_step_idx >= len(self.opener):
                sim_in_opener = False
                sim_step_idx = 0
            elif not sim_in_opener and sim_step_idx >= len(self.loop):
                sim_step_idx = 0
        return result

    # ==========================================
    # 🔍 核心诊断区：输入判定
    # ==========================================
    def input_received(self, input_action, is_down):
        current_script = self.get_current_script()
        if not current_script or self.step_index >= len(current_script):
            return False

        expected_action = current_script[self.step_index]
        expected_type = expected_action.get("type")
        variant = expected_action.get("variant", "")

        action_state_str = "【按下⬇️】" if is_down else "【松开⬆️】"
        log.debug(f"👉 导演收到信号: {action_state_str} {input_action} | 期待: {expected_type}({variant})")

        # --- 1. 处理按下 (DOWN) ---
        if is_down:
            is_match = False
            if expected_type == "intro":
                target = expected_action.get("next_char")
                if input_action == f"intro_{target}": is_match = True
            elif input_action == expected_type:
                is_match = True
            # === 💡 核心修复：兼容重击的按键判定 ===
            # 如果剧本要求 heavy，且玩家按下了 basic 键，判定为匹配！
            elif expected_type == "heavy" and input_action == "basic":
                is_match = True

            if is_match:
                # 兼容两种剧本写法：type是heavy，或者variant里带heavy
                is_heavy = (expected_type == "heavy") or (variant and "heavy" in variant.lower())

                if is_heavy:
                    if not self.is_holding:
                        self.button_press_start_time = time.time()
                        self.is_holding = True
                        log.info(f"⏳ 匹配成功！重击开始蓄力 (期待时长: {self.heavy_threshold}s)...")
                    else:
                        log.debug("🛡️ 已经在蓄力中，忽略重复的按下信号(防抖)。")
                    return False  # 蓄力中，不翻页
                else:
                    log.info(f"✅ 普通动作匹配成功！执行翻页。")
                    self.advance()
                    return True
            else:
                log.debug("❌ 动作不匹配，忽略。")
            return False

        # --- 2. 处理松开 (UP) ---
        else:
            if self.is_holding:
                hold_duration = time.time() - self.button_press_start_time
                log.debug(f"🛑 收到松开信号！已按住时间: {hold_duration:.3f}s")

                if hold_duration >= self.heavy_threshold:
                    self.is_holding = False
                    log.info(f"🔥 松开时蓄力已达标 ({hold_duration:.2f}s)！执行翻页。")
                    self.advance()
                    return True
                elif hold_duration > 0.1:
                    self.is_holding = False
                    log.info(f"⚠️ 蓄力失败！时间太短 ({hold_duration:.2f}s < {self.heavy_threshold}s)")
                else:
                    log.debug(f"🛡️ 瞬间松开 ({hold_duration:.3f}s)，判定为硬件抖动断触，保持蓄力状态！")
            return False

    # ==========================================
    # 🔍 核心诊断区：自动计时跳跃
    # ==========================================
    def check_auto_advance(self):
        if self.is_holding:
            elapsed = time.time() - self.button_press_start_time
            # 如果刚好卡在临界点，打印一下
            if elapsed >= self.heavy_threshold:
                self.is_holding = False
                log.info(f"💥 自动检测: 蓄力达标 ({elapsed:.2f}s)！强行翻页！")
                self.advance()
                return True
        return False

    def advance(self):
        current_action = self.get_current_script()[self.step_index]
        if current_action.get("type") == "intro":
            next_char = current_action.get("next_char")
            if next_char:
                self.current_char_idx = next_char
                log.info(f"🔄 角色切换 -> {self.team[next_char]}")

        self.step_index += 1
        if self.is_in_opener and self.step_index >= len(self.opener):
            log.info("✨ 启动轴跑完，切入循环轴！")
            self.is_in_opener = False
            self.step_index = 0
        elif not self.is_in_opener and self.step_index >= len(self.loop):
            log.info("🔁 循环轴跑完，重新开始！")
            self.step_index = 0

    def reset(self):
        self.step_index = 0
        self.is_in_opener = True if self.opener else False
        self.is_holding = False
        self.button_press_start_time = 0