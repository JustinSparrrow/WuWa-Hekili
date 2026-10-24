import json
import os
import sys


class ConfigManager:
    """
    全局配置管理器（单例）。

    config.json 用点号路径访问，例如：
        config.get("settings.current_device")
        config.update_setting("settings.current_device", "xbox")

    v1.1 优化点
    ----------
    - 写入前先比对值：值没变就不落盘。拖窗口、切设备这类高频操作
      以前每次都要把整个 JSON 序列化一遍，现在同值写入直接返回。
    - 新增 `update_settings()` 批量写入，多个键只写一次盘。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # 打包后配置放在 exe 同级；开发环境在项目根目录（统一根查找，见 utils.paths）
        from utils.paths import project_root
        base_path = str(project_root())

        self.config_path = os.path.join(base_path, "config.json")
        self.data = {}

        self.load()
        self._initialized = True

    # ================================================================ 读写

    def load(self):
        """从磁盘重新载入配置。"""
        if not os.path.exists(self.config_path):
            print("配置文件不存在，生成默认配置...")
            self.create_default()

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        except Exception as e:
            print(f"配置文件损坏: {e}")

    def save(self):
        """把内存中的配置写回磁盘（整个文件覆写，调用方自行控制频率）。"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置失败: {e}")

    # ================================================================ 访问

    def get(self, key, default=None):
        """按点号路径读取，不存在时返回 default。"""
        keys = key.split('.')
        value = self.data
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def _apply(self, key, value):
        """
        在内存里写入一个值。

        :return: True 表示值确实发生了变化（需要落盘），False 表示没变
        """
        keys = key.split('.')
        d = self.data
        for k in keys[:-1]:
            d = d.setdefault(k, {})

        if d.get(keys[-1]) == value:
            return False
        d[keys[-1]] = value
        return True

    def update_setting(self, key, value, save=True):
        """
        写入单个配置项。

        :param save: 是否需要立即落盘。批量场景下传 False，最后调用 save()
        :return: 值是否发生变化
        """
        changed = self._apply(key, value)
        if changed and save:
            self.save()
        return changed

    def update_settings(self, mapping):
        """
        批量写入多个配置项，只落盘一次。

        :param mapping: {"settings.window_x": 100, "settings.window_y": 200}
        """
        # 注意用列表推导先把所有项都应用完，any() 短路会漏掉后面的键
        changed = any([self._apply(k, v) for k, v in mapping.items()])
        if changed:
            self.save()

    # ================================================================ 默认值

    def create_default(self):
        """生成默认 config.json（文件损坏或首次运行时使用）。"""
        default_config = {
            "settings": {
                "current_device": "xbox",
                "theme": "dark",
                "window_opacity": 0.9,
                "heavy_hold_time": 0.5,
                "strict_tap_check": True,
                "window_x": 100,
                "window_y": 100
            },
            # ---- 时间轴 / 输入缓冲（v1.2）----
            # enabled          : 总开关。关掉退化成"按一下就推进一格"的老行为
            # input_buffer_ms  : 预输入寿命。玩家提前按键，超过这个时间还没轮到，
            #                    就认为"按太早、游戏已丢弃"，不推进
            # enable_parallel  : 允许"当前动作还没结束时提前按后面的步"（如蓄力中放声骸）
            # auto_parallel    : 全局允许并行的动作组合，默认空。
            #                    鸣潮里"蓄力中放声骸"是角色特性，靠剧本写 "parallel": true 声明；
            #                    只有确认某组合全局通用时才往这里加，如 [["heavy","echo"]]
            # durations_ms     : 每类动作的占位时长。这不是游戏数据，是手感参数：
            #                    提示总是慢半拍 -> 调小；总是抢在前面 -> 调大
            # character_durations : 角色级覆盖，只写差异。例如
            #                    {"Lynae": {"heavy": 780}, "Mornye": {"skill": 470}}
            #                    层级：剧本单步 duration_ms > 这里 > durations_ms
            "timing": {
                "enabled": True,
                "input_buffer_ms": 250,
                "enable_parallel": True,
                "auto_parallel": [],
                "durations_ms": {
                    "basic": 380,
                    "heavy": 700,
                    "skill": 520,
                    "ult": 1100,
                    "echo": 520,
                    "execution": 600,
                    "dodge": 320,
                    "jump": 280,
                    "intro": 500
                },
                "character_durations": {}
            },
            "controller": {
                "buttons": {
                    "a": 0,
                    "b": 1,
                    "x": 2,
                    "y": 3,
                    "lb": 4,
                    "rb": 5,
                    "view": 6,
                    "menu": 7,
                    "ls": 8,
                    "rs": 9
                },
                "axes": {
                    "lt": 4,
                    "rt": 5
                },
                "hat_": {
                    "dpad_up": "0,1",
                    "dpad_down": "0,-1",
                    "dpad_left": "-1,0",
                    "dpad_right": "1,0"
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
                    # skill / execution 都落在 resonance_skill 目录，文件名是 skill*.png。
                    # 以前这里写 "normal"，导致关键字永远匹配不上，只能退到
                    # 「取目录里第一张」——图片碰巧是对的，但属于运气而不是规则。
                    "skill": "skill",
                    "ult": "liberation",
                    "jump": "jump",
                    "dodge": "dodge",
                    "execution": "skill",
                    "intro": "avatar",
                    "echo": "echo"
                }
            },
            "keymaps": {
                "xbox": {
                    "start_trigger": "xbox_lb",
                    "rollback": "xbox_button_view",
                    "basic": "xbox_button_b",
                    "skill": "xbox_button_y",
                    "ult": "xbox_rb",
                    "jump": "xbox_button_a",
                    "dodge": "xbox_rt",
                    "echo": "xbox_lt",
                    "execution": "xbox_button_x",
                    "lock": "xbox_rs",
                    "intro_1": "xbox_dpad_up",
                    "intro_2": "xbox_dpad_right",
                    "intro_3": "xbox_dpad_down"
                },
                "keyboard": {
                    "start_trigger": "keyboard_x",
                    "rollback": "keyboard_v",
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
                json.dump(default_config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"写入默认配置失败: {e}")

        self.data = default_config


# 全局导出：其它模块直接 `from utils.config_manager import config`
config = ConfigManager()
