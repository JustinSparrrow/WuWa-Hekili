import os
import sys

from utils.config_manager import config
from utils.logger import log

# 用于区分「缓存里存了 None」和「缓存里还没有这个 key」的哨兵对象
_MISS = object()


class AssetManager:
    """
    资源解析器：负责把「角色 + 动作 + 变体」翻译成具体的图标文件路径。

    性能设计（v1.1 优化重点）
    ------------------------
    悬浮窗每推进一格，就要为 4 个槽位各取一次技能图标和一次按键图标。
    旧实现每次都走 os.listdir + os.path.exists，单次推进约产生 8~12 次磁盘
    系统调用；连续普攻时每秒可推进数次，磁盘 IO 成为明显卡顿来源。

    现在所有解析结果都会被缓存：
      - `_icon_cache`   : 技能大图路径
      - `_button_cache` : 右下角按键小图路径
    缓存 key 里包含了 config 中参与判定的值（文件夹名 / 默认关键字 / 按键文件名），
    所以用户改了按键映射或素材映射后，key 自然会失配，无需手动清缓存。
    目录内容（新增 png）在运行期间不会变化；确需刷新时调用 `clear_cache()`。
    """

    # 共用同一颗物理键的动作：keymaps 里只登记了左边那个，右边要借。
    # 目前只有「重击」借「普攻」——游戏里都是攻击键，靠按住时长区分。
    KEY_FAMILY = {"heavy": "basic"}

    def __init__(self, asset_path):
        """
        :param asset_path: 开发环境下传入的相对路径，如 "assets/characters"
        """
        if getattr(sys, 'frozen', False):
            # 打包环境：忽略传入参数，强制定位到 EXE 旁边的 _internal 目录
            exe_root = os.path.dirname(sys.executable)
            self.path = os.path.join(exe_root, "_internal", "assets", "characters")
        else:
            # 开发环境：转绝对路径，避免受工作目录影响
            self.path = os.path.abspath(asset_path)

        # assets/characters 的上一级是 assets，按键图标在 assets/input 下
        self.ui_path = os.path.join(os.path.dirname(self.path), "input")

        self.weapon_map = {}
        self.load_mapping()
        self.folder_map = config.get("assets.folder_mapping", {})

        # 解析结果缓存（见类文档）
        self._icon_cache = {}
        self._button_cache = {}

    # ------------------------------------------------------------------ 配置

    def load_mapping(self):
        """读取 Character_Occupation.txt，建立「角色英文名 -> 武器类型」映射。"""
        map_file = os.path.join(self.path, "Character_Occupation.txt")
        if not os.path.exists(map_file):
            return
        try:
            with open(map_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    # 兼容 "=" / ":" / "：" 三种分隔符
                    for d in ["=", ":", "："]:
                        if d in line:
                            parts = line.split(d, 1)
                            self.weapon_map[parts[0].strip()] = parts[1].strip()
                            break
            log.debug(f"已加载 {len(self.weapon_map)} 个角色武器映射")
        except Exception as e:
            log.error(f"加载角色武器映射失败: {e}")

    def clear_cache(self):
        """素材目录发生变化（如用素材工厂新增了图标）后调用，强制下次重新扫描。"""
        self._icon_cache.clear()
        self._button_cache.clear()

    # -------------------------------------------------------------- 基础查找

    def _find_image_in_dir(self, directory, variant=None, default_keyword=None):
        """
        在一个目录里挑一张最合适的 png。

        优先级：变体关键字命中 -> 默认关键字命中 -> 目录里排第一张。

        :return: (路径 或 None, 命中方式)
                 命中方式 ∈ {"variant", "keyword", "first"}，用于审计报告区分
                 "真的找到了这一步的图" 和 "只是目录里有张图就拿来用了"。
        """
        if not os.path.exists(directory):
            return None, "missing"
        try:
            files = sorted([f for f in os.listdir(directory) if f.lower().endswith('.png')])
        except OSError:
            return None, "missing"
        if not files:
            return None, "missing"

        if variant:
            for f in files:
                if variant.lower() in f.lower():
                    return os.path.join(directory, f), "variant"

        if default_keyword:
            for f in files:
                if default_keyword.lower() in f.lower():
                    return os.path.join(directory, f), "keyword"

        # 兜底拿第一张：这不是"找到"，只是"目录非空"，审计时要标出来
        return os.path.join(directory, files[0]), "first"

    # ---------------------------------------------------------------- 对外 API

    def get_icon_path(self, char_name, action_type, variant=None, force_general=False, custom_icon=None):
        """
        获取技能图标路径（带缓存）。

        强化版图标查找：支持跨文件夹自动降级
        查找顺序：角色专属文件夹 -> 跨文件夹兜底(重击找普攻) -> _general 通用库

        :return: 图标绝对路径；彻底找不到时为 None
        """
        return self.explain_icon_path(char_name, action_type, variant,
                                      force_general, custom_icon)["path"]

    def explain_icon_path(self, char_name, action_type, variant=None,
                          force_general=False, custom_icon=None):
        """
        与 get_icon_path 相同，但额外告诉你这张图是**怎么来的**。

        做轴的人最常遇到的问题不是"找不到图"，而是"图找错了但没人告诉我"。
        旧的查找逻辑在专属目录里挑不到合适变体时，会直接拿目录里排第一张，
        表面看是"有图"，实际可能是完全不相干的动作。

        :return: dict，含
                 path   : 绝对路径或 None
                 source : 命中来源
                          custom            剧本指定 custom_icon 且命中
                          exclusive:variant 专属目录 + 变体精确命中（最理想）
                          exclusive:keyword 专属目录 + 默认关键字命中
                          exclusive:first   专属目录 + 随便拿了第一张（可疑）
                          heavy_fallback    重击没有素材，借用普攻的图
                          general           掉到 _general 通用库
                          loose:first       角色目录下兜底随便一张
                          missing           完全没有
                 detail : 人话说明
        """
        folder_name = self.folder_map.get(action_type, action_type)
        keyword = config.get(f"assets.default_filename.{action_type}", action_type)

        # 缓存 key 包含所有会影响解析结果的输入，配置改动会自动 miss
        cache_key = (char_name, folder_name, variant, keyword, force_general, custom_icon)
        cached = self._icon_cache.get(cache_key, _MISS)
        if cached is _MISS:
            cached = self._resolve_icon(char_name, action_type, folder_name, variant, keyword,
                                        force_general, custom_icon)
            self._icon_cache[cache_key] = cached

        path, source = cached
        return {"path": path, "source": source,
                "detail": self._explain_source(char_name, action_type, variant, source, path)}

    @staticmethod
    def _explain_source(char_name, action_type, variant, source, path):
        """把来源代号翻译成一句人话，供审计工具直接展示。"""
        label = f"{char_name} 的 {action_type}"
        if variant:
            label += f"[{variant}]"
        base = os.path.basename(path) if path else ""

        if source == "custom":
            return f"{label}: 使用剧本指定的图标 {base}"
        if source == "exclusive:variant":
            return f"{label}: 专属目录精确命中 {base}"
        if source == "exclusive:keyword":
            return f"{label}: 专属目录按默认关键字命中 {base}"
        if source == "exclusive:first":
            return (f"{label}: 专属目录里没有匹配 {variant or '该动作'} 的图，"
                    f"取了第一张 {base} —— 可能是错的动作")
        if source == "heavy_fallback":
            return f"{label}: 没有重击素材，借用普攻图 {base}"
        if source == "general":
            return f"{label}: 掉到通用库 {base}（角色专属素材缺失）"
        if source == "loose:first":
            return f"{label}: 只在角色目录下兜底取了一张 {base}"
        return f"{label}: 没有找到任何可用图标，界面会退化为文字"

    def _resolve_icon(self, char_name, action_type, folder_name, variant, keyword,
                      force_general, custom_icon):
        """
        真正的磁盘查找逻辑，只在缓存未命中时执行。

        :return: (路径 或 None, 来源代号)，来源代号见 explain_icon_path 的说明
        """
        # 1. 剧本里写死了图标文件名：优先按用户指定找
        if custom_icon:
            # 尝试在专属文件夹找
            p1 = os.path.join(self.path, char_name, folder_name, custom_icon)
            if os.path.exists(p1):
                return p1, "custom"
            # 尝试在普攻/技能等常见文件夹找
            for sub in ["normal_attack", "resonance_skill"]:
                p2 = os.path.join(self.path, char_name, sub, custom_icon)
                if os.path.exists(p2):
                    return p2, "custom"
            # 指定了却没找到：以前是静默降级，用户会以为指定生效了
            log.warning(f"剧本指定的图标不存在: {char_name}/{custom_icon}，已改用自动查找")

        if not force_general:
            # 2. 角色专属文件夹
            char_dir = os.path.join(self.path, char_name, folder_name)
            found, kind = self._find_image_in_dir(char_dir, variant, keyword)
            if found:
                return found, f"exclusive:{kind}"

            # 3. 跨文件夹降级：重击(heavy)没素材时，借用普攻的图
            if "heavy" in action_type or (variant and "heavy" in variant.lower()):
                alt_dir = os.path.join(self.path, char_name, "normal_attack")
                found, kind = self._find_image_in_dir(alt_dir, variant, "normal")
                if found:
                    return found, "heavy_fallback"

        # 4. 通用库 _general：普攻/重击再按武器类型细分
        general_dir = None
        if action_type in ("basic", "heavy"):
            weapon = self.weapon_map.get(char_name)
            if weapon:
                general_dir = os.path.join(self.path, "_general", "normal_attack", weapon)
        else:
            general_dir = os.path.join(self.path, "_general", folder_name)

        if general_dir:
            found, kind = self._find_image_in_dir(general_dir, variant, keyword)
            if found:
                return found, "general"

        # 5. 最后兜底：角色主目录下随便找一张（处决/闪避除外，它们宁可显示黑框）
        if not force_general:
            fallback, _ = self._find_image_in_dir(os.path.join(self.path, char_name, folder_name),
                                                  variant=None)
            if fallback and action_type not in ("execution", "dodge"):
                return fallback, "loose:first"

        log.warning(f"图标缺失: {char_name}-{action_type}-{variant} "
                    f"(force_general={force_general})，界面将退化为文字")
        return None, "missing"

    def get_button_path(self, action_type, target_index=None):
        """
        获取右下角「按键提示」小图路径（带缓存）。

        :param target_index: 切人动作的目标槽位(1/2/3)，用于区分十字键/数字键方向
        """
        device = config.get("settings.current_device", "xbox")

        lookup_key = action_type
        if action_type == "intro" and target_index is not None:
            lookup_key = f"intro_{target_index}"

        # 先按精细 key 取，取不到再退回动作类型本身
        btn_filename = config.get(f"keymaps.{device}.{lookup_key}")
        if not btn_filename:
            btn_filename = config.get(f"keymaps.{device}.{action_type}")

        # 重击和普攻共用同一颗攻击键（鼠标左键 / 手柄 X），keymaps 里只登记了 basic，
        # 所以重击格以前右下角是空的 —— 提示「重击」却不告诉你按哪个键。
        if not btn_filename:
            family = self.KEY_FAMILY.get(action_type)
            if family:
                btn_filename = config.get(f"keymaps.{device}.{family}")

        if not btn_filename:
            return None

        # key 里带设备名和文件名，切设备 / 改映射后天然失效
        cache_key = (device, btn_filename)
        cached = self._button_cache.get(cache_key, _MISS)
        if cached is not _MISS:
            return cached

        path = os.path.join(self.ui_path, device, f"{btn_filename}.png")
        result = path if os.path.exists(path) else None
        self._button_cache[cache_key] = result
        return result
