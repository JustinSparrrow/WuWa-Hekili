import json
import os
import sys


class ConfigManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        self.config_path = os.path.join(base_path, "config.json")
        self.data = {}

        self.load()
        self._initialized = True

    def load(self):
        if not os.path.exists(self.config_path):
            print("⚠️ 配置文件不存在，生成默认配置...")
            self.create_default()

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            print("✅ 配置加载成功")
        except Exception as e:
            print(f"❌ 配置文件损坏: {e}")

    def get(self, key, default=None):
        keys = key.split('.')
        value = self.data
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def update_setting(self, key, value):
        keys = key.split('.')
        d = self.data
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value

        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            print(f"❌ 保存配置失败: {e}")

    def create_default(self):
        """生成完美的默认 config.json"""
        default_config = {
            "settings": {
                "current_device": "xbox",
                "theme": "default",
                "window_opacity": 0.9,
                "heavy_hold_time": 0.5,
                "window_x": 100,
                "window_y": 100
            },
            "controller": {
                "hardware_mapping": {
                    "0": "xbox_button_color_a",
                    "1": "xbox_button_color_b",
                    "2": "xbox_button_color_x",
                    "3": "xbox_button_color_y",
                    "4": "xbox_lb",
                    "5": "xbox_rb",
                    "6": "xbox_button_view",
                    "7": "xbox_button_menu",
                    "8": "xbox_ls",
                    "9": "xbox_rs"
                },
                "axis_mapping": {
                    "4": "xbox_lt",
                    "5": "xbox_rt"
                },
                "hat_mapping": {
                    "0,1": "xbox_dpad_up",
                    "0,-1": "xbox_dpad_down",
                    "-1,0": "xbox_dpad_left",
                    "1,0": "xbox_dpad_right"
                }
            },
            "assets": {
                "folder_mapping": {
                    "basic": "normal_attack",
                    "heavy": "heavy",
                    "skill": "resonance_skill",
                    "ult": "resonance_liberation",
                    "execution": "resonance_skill",
                    "jump": "jump",
                    "dodge": "dodge",
                    "echo": "echo",
                    "intro": "character"
                },
                "default_filename": {
                    "basic": "normal",
                    "heavy": "heavy",
                    "skill": "normal",
                    "ult": "liberation",
                    "jump": "jump",
                    "dodge": "dodge",
                    "execution": "normal",
                    "intro": "avatar",
                    "echo": "echo"
                }
            },
            "keymaps": {
                "xbox": {
                    "start_trigger": "xbox_button_color_x",
                    "basic": "xbox_button_color_b",
                    "skill": "xbox_button_color_y",
                    "ult": "xbox_rb",
                    "jump": "xbox_button_color_a",
                    "dodge": "xbox_rt",
                    "echo": "xbox_lt",
                    "execution": "xbox_button_color_y",
                    "lock": "xbox_rs",
                    "intro_1": "xbox_dpad_up",
                    "intro_2": "xbox_dpad_right",
                    "intro_3": "xbox_dpad_down"
                },
                "keyboard": {
                    "start_trigger": "keyboard_f",
                    "basic": "mouse_left",
                    "skill": "keyboard_e",
                    "ult": "keyboard_r",
                    "jump": "keyboard_space",
                    "dodge": "mouse_right",
                    "echo": "keyboard_q",
                    "execution": "keyboard_f",
                    "lock": "mouse_scroll",
                    "intro_1": "keyboard_1",
                    "intro_2": "keyboard_2",
                    "intro_3": "keyboard_3"
                }
            }
        }

        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2)
        except Exception as e:
            print(f"❌ 写入配置失败: {e}")

        self.data = default_config


# 全局导出
config = ConfigManager()