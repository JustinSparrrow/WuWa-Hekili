import os
from utils.config_manager import config


class AssetManager:
    def __init__(self, asset_path):
        self.path = asset_path
        self.ui_path = os.path.join(os.path.dirname(self.path), "ui")
        self.weapon_map = {}
        self.load_mapping()
        self.folder_map = config.get("assets.folder_mapping", {})

    def load_mapping(self):
        map_file = os.path.join(self.path, "Character_Occupation.txt")
        if not os.path.exists(map_file): return
        try:
            with open(map_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"): continue
                    for d in ["=", ":", "："]:
                        if d in line:
                            parts = line.split(d, 1)
                            self.weapon_map[parts[0].strip()] = parts[1].strip()
                            break
            print(f"✅ 已加载 {len(self.weapon_map)} 个角色武器映射。")
        except Exception as e:
            print(f"❌ 加载映射失败: {e}")

    def _find_image_in_dir(self, directory, variant=None, default_keyword=None):
        if not os.path.exists(directory): return None
        try:
            files = sorted([f for f in os.listdir(directory) if f.lower().endswith('.png')])
        except:
            return None
        if not files: return None

        if variant:
            for f in files:
                if variant.lower() in f.lower(): return os.path.join(directory, f)

        if default_keyword:
            for f in files:
                if default_keyword.lower() in f.lower(): return os.path.join(directory, f)

        return os.path.join(directory, files[0])

    def get_icon_path(self, char_name, action_type, variant=None, force_general=False, custom_icon=None):
        """
        🚀 强化版图标查找：支持跨文件夹自动降级
        """
        # 1. 初始尝试：按照 config 映射的文件夹找
        folder_name = self.folder_map.get(action_type, action_type)

        if custom_icon:
            # 尝试在专属文件夹找
            p1 = os.path.join(self.path, char_name, folder_name, custom_icon)
            if os.path.exists(p1): return p1
            # 尝试在普攻/技能等常见文件夹找
            for sub in ["normal_attack", "resonance_skill"]:
                p2 = os.path.join(self.path, char_name, sub, custom_icon)
                if os.path.exists(p2): return p2

        keyword = config.get(f"assets.default_filename.{action_type}", action_type)

        if not force_general:
            char_dir = os.path.join(self.path, char_name, folder_name)
            found = self._find_image_in_dir(char_dir, variant, keyword)
            if found: return found

            # --- 💡 核心改动：跨文件夹降级逻辑 ---

            # 情况 A: 如果是重击 (heavy) 没找到，去普攻文件夹 (normal_attack) 找
            if "heavy" in action_type or (variant and "heavy" in variant.lower()):
                alt_dir = os.path.join(self.path, char_name, "normal_attack")
                found = self._find_image_in_dir(alt_dir, variant, "normal")
                if found: return found

        # 2. 通用 AAA_general 查找
        general_dir = None
        if action_type == "basic" or action_type == "heavy":
            weapon = self.weapon_map.get(char_name)
            if weapon:
                # 尝试通用库里的普攻目录
                general_dir = os.path.join(self.path, "AAA_general", "normal_attack", weapon)
        else:
            general_dir = os.path.join(self.path, "AAA_general", folder_name)

        if general_dir:
            found = self._find_image_in_dir(general_dir, variant, keyword)
            if found: return found

        # 3. 最终死马当活马医：去角色主目录下随便搜搜
        if not force_general:
            fallback = self._find_image_in_dir(os.path.join(self.path, char_name, folder_name), variant=None)
            # 如果 fallback 找到了图，并且你希望显示，就 return fallback
            # 但如果你希望强行显示黑框，可以在这里加个判断：
            if fallback and action_type not in ["execution", "dodge"]:
                return fallback

        print(f"❌ 彻底找不到图标: {char_name}-{action_type}-{variant} (ForceGen: {force_general})")
        return None

    def get_button_path(self, action_type, target_index=None):
        # 保持之前的逻辑不变...
        device = config.get("settings.current_device", "xbox")
        lookup_key = action_type
        if action_type == "intro" and target_index is not None:
            lookup_key = f"intro_{target_index}"
        btn_filename = config.get(f"keymaps.{device}.{lookup_key}")
        if not btn_filename:
            btn_filename = config.get(f"keymaps.{device}.{action_type}")
        if not btn_filename: return None
        path = os.path.join(self.ui_path, device, f"{btn_filename}.png")
        return path if os.path.exists(path) else None