import os
from utils.config_manager import config


class AssetManager:
    def __init__(self, asset_path):
        """
        初始化资源管理器
        :param asset_path: 指向 assets/assets 的绝对路径
        """
        self.path = asset_path
        # UI 图标通常在 assets/ui (asset_path 的同级目录)
        self.ui_path = os.path.join(os.path.dirname(asset_path), "ui")

        self.weapon_map = {}
        self.load_mapping()

        # 从 config 获取文件夹映射 (例如 basic -> normal_attack)
        self.folder_map = config.get("assets.folder_mapping", {})

    def load_mapping(self):
        """加载角色职业/武器映射文件"""
        map_file = os.path.join(self.path, "Character_Occupation.txt")

        if not os.path.exists(map_file):
            print(f"⚠️ 警告: 找不到映射文件 {map_file}")
            return

        try:
            with open(map_file, "r", encoding="utf-8") as f:
                for line in f:
                    if "=" in line and not line.strip().startswith("#"):
                        char, weapon = line.strip().split("=", 1)
                        self.weapon_map[char.strip()] = weapon.strip()
            print(f"✅ 已加载 {len(self.weapon_map)} 个角色武器映射。")
        except Exception as e:
            print(f"❌ 加载映射文件失败: {e}")

    def _find_image_in_dir(self, directory, variant=None, default_keyword=None):
        """
        [内部核心] 在文件夹中智能寻找最匹配的图片
        """
        if not os.path.exists(directory):
            return None

        # 1. 获取所有 PNG 并【排序】(确保 _1 在 _2 前面)
        try:
            files = sorted([f for f in os.listdir(directory) if f.lower().endswith('.png')])
        except Exception:
            return None

        if not files:
            return None

        # 2. 策略 A: 优先匹配 Variant (例如剧本里写的 "heavy", "enhanced", "2")
        if variant:
            for f in files:
                if variant.lower() in f.lower():
                    return os.path.join(directory, f)
            # 没找到 variant 时，不直接返回None，允许继续向下寻找默认图(降级)

        # 3. 策略 B: 匹配 config 里的默认关键词 (例如 "normal", "liberation")
        if default_keyword:
            for f in files:
                if default_keyword.lower() in f.lower():
                    return os.path.join(directory, f)

        # 4. 策略 C: 保底返回第一张图
        return os.path.join(directory, files[0])

    def get_icon_path(self, char_name, action_type, variant=None, force_general=False):
        """
        获取技能/动作图标路径
        :param char_name: 角色名
        :param action_type: 动作简写 (basic, skill, ult...)
        :param variant: 变体关键词 (heavy, enhanced, forte...)
        :param force_general: 是否强制跳过专属目录去通用目录找
        """
        # 转换文件夹名 (例如 skill -> resonance_skill)
        folder_name = self.folder_map.get(action_type, action_type)
        # 获取默认文件名关键词 (例如 skill -> normal)
        keyword = config.get(f"assets.default_filename.{action_type}", action_type)

        # --- 阶段 1: 角色专属查找 (仅在不强制通用时执行) ---
        if not force_general:
            if variant and "heavy" in variant.lower():
                special_heavy_dir = os.path.join(self.path, char_name, "heavy")
                found = self._find_image_in_dir(special_heavy_dir, variant, "heavy")
                if found: return found

            char_dir = os.path.join(self.path, char_name, folder_name)
            found = self._find_image_in_dir(char_dir, variant, keyword)
            if found:
                return found

        # --- 阶段 2: 通用 AAA_general 查找 ---
        general_dir = None
        if action_type == "basic":
            # 普攻根据武器类型找: AAA_general/normal_attack/sword/
            weapon = self.weapon_map.get(char_name)
            if weapon:
                general_dir = os.path.join(self.path, "AAA_general", folder_name, weapon)
        else:
            # 其他动作直接在通用目录找: AAA_general/jump/
            general_dir = os.path.join(self.path, "AAA_general", folder_name)

        if general_dir:
            found = self._find_image_in_dir(general_dir, variant, keyword)
            if found:
                return found

        # --- 阶段 3: 终极保底 ---
        # 如果连通用都没找到（可能拼写错误），返回专属目录下随便一张图
        if not force_general:
            fallback = self._find_image_in_dir(os.path.join(self.path, char_name, folder_name))
            if fallback: return fallback

        print(f"❌ 彻底找不到图标: {char_name}-{action_type}-{variant} (ForceGen: {force_general})")
        return None

    def get_button_path(self, action_type, target_index=None):
        """
        获取手柄/键盘按键图标
        :param action_type: 动作类型
        :param target_index: 切人目标位置 (1, 2, 3)
        """
        device = config.get("settings.current_device", "xbox")

        # 处理 Intro 逻辑，转换为 intro_1, intro_2 等
        lookup_key = action_type
        if action_type == "intro" and target_index is not None:
            lookup_key = f"intro_{target_index}"

        # 从 config 获取按键图片文件名
        btn_filename = config.get(f"keymaps.{device}.{lookup_key}")

        if not btn_filename:
            # 回退尝试找通用 intro
            btn_filename = config.get(f"keymaps.{device}.{action_type}")
            if not btn_filename:
                return None

        # 路径: assets/ui/xbox/xbox_button_x.png
        path = os.path.join(self.ui_path, device, f"{btn_filename}.png")

        if os.path.exists(path):
            return path
        return None


# ================= 测试代码 =================
if __name__ == "__main__":
    # 模拟路径 (根据实际情况调整)
    base_path = r"..\assets\assets"
    manager = AssetManager(base_path)

    print("\n--- AssetManager 功能测试 ---")

    # 1. 测试强制通用 (a1)
    p1 = manager.get_icon_path("Gabriella", "basic", force_general=True)
    print(f"测试1 (强制通用普攻): {p1}")

    # 2. 测试专属强化 (Moning 强化E)
    p2 = manager.get_icon_path("Moning", "skill", variant="enhanced")
    print(f"测试2 (角色强化技能): {p2}")

    # 3. 测试手柄切人按键 (intro_2)
    p3 = manager.get_button_path("intro", target_index=2)
    print(f"测试3 (Xbox切2号位按键): {p3}")