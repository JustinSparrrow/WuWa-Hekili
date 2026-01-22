import time
from utils.config_manager import config


class Director:
    def __init__(self, team_config, opener_script, loop_script, start_char_index, asset_mgr):
        self.team = team_config
        self.opener = opener_script
        self.loop = loop_script
        self.asset_mgr = asset_mgr
        self.is_in_opener = True
        self.step_index = 0
        self.current_char_idx = start_char_index

        # 长按逻辑变量
        self.is_holding = False
        self.button_press_start_time = 0
        self.heavy_threshold = config.get("settings.heavy_hold_time", 0.5)

        if not self.opener:
            self.is_in_opener = False

    def get_current_script(self):
        return self.opener if self.is_in_opener else self.loop

    def get_visual_data(self, preview_count=3):
        result = []
        sim_in_opener = self.is_in_opener
        sim_step_idx = self.step_index
        virtual_char_idx = self.current_char_idx

        for i in range(preview_count):
            current_script = self.opener if sim_in_opener else self.loop
            if not current_script: break

            action = current_script[sim_step_idx]

            # --- 💡 关键修改点 1：获取标签 ---
            action_type = action.get("type")
            variant = action.get("variant")
            desc = action.get("desc", "")
            f_gen = action.get("force_general", False)  # 提取强制通用标签

            # ... 处理切人逻辑 (保持不变) ...
            display_char_idx = virtual_char_idx
            target_idx_arg = None
            if action_type == "intro":
                next_char = action.get("next_char")
                if next_char:
                    virtual_char_idx = next_char
                    display_char_idx = next_char
                    target_idx_arg = next_char

            char_name = self.team.get(display_char_idx, "Unknown")

            # --- 💡 关键修改点 2：传给 AssetManager ---
            icon_path = self.asset_mgr.get_icon_path(
                char_name,
                action_type,
                variant=variant,
                force_general=f_gen  # 必须把这个值传过去！
            )

            btn_path = self.asset_mgr.get_button_path(action_type, target_index=target_idx_arg)

            result.append({
                "desc": desc,
                "icon_path": icon_path,
                "btn_path": btn_path,
                "variant": variant,
                "char_name": char_name,
                "is_current": (i == 0)
            })

            # ... 指针推进逻辑 (保持不变) ...
            sim_step_idx += 1
            if sim_in_opener and sim_step_idx >= len(self.opener):
                sim_in_opener = False
                sim_step_idx = 0
            elif not sim_in_opener and sim_step_idx >= len(self.loop):
                sim_step_idx = 0
        return result

    def input_received(self, input_action, is_down):
        current_script = self.get_current_script()
        expected_action = current_script[self.step_index]
        expected_type = expected_action.get("type")
        variant = expected_action.get("variant")

        if is_down:
            # 判定是否按对了键
            is_match = False
            if expected_type == "intro":
                target = expected_action.get("next_char")
                if input_action == f"intro_{target}": is_match = True
            elif input_action == expected_type:
                is_match = True

            if is_match:
                is_heavy = variant and "heavy" in variant.lower()
                if is_heavy:
                    # 💡 只要按下了正确的重击键，就开始计时
                    self.button_press_start_time = time.time()
                    self.is_holding = True
                    return False
                else:
                    self.advance()
                    return True
        else:
            # 💡 如果松开了按键，立即停止计时（防止误触发）
            self.is_holding = False

        return False

    def check_auto_advance(self):
        """
        【新增方法】由主循环每隔 50ms 调用一次
        返回 True 表示因为时间到了而自动推进了步骤
        """
        if self.is_holding:
            elapsed = time.time() - self.button_press_start_time
            if elapsed >= self.heavy_threshold:
                # 💡 时间到了！立刻推进，并关闭计时器防止重复触发
                self.is_holding = False
                # print(f"🔥 重击时长达标 ({elapsed:.2f}s)，自动跳转！")
                self.advance()
                return True
        return False

    def advance(self):
        """执行推进逻辑 (保持不变)"""
        current_script = self.get_current_script()
        current_action = current_script[self.step_index]

        if current_action.get("type") == "intro":
            next_char = current_action.get("next_char")
            if next_char:
                self.current_char_idx = next_char
                print(f"🔄 切人 -> {self.team[next_char]}")

        self.step_index += 1

        if self.is_in_opener and self.step_index >= len(self.opener):
            print("✨ 启动轴结束，进入循环轴！")
            self.is_in_opener = False
            self.step_index = 0
        elif not self.is_in_opener and self.step_index >= len(self.loop):
            self.step_index = 0

    def reset(self):
        self.step_index = 0
        self.is_in_opener = True if self.opener else False
        self.is_holding = False
        self.button_press_start_time = 0