import re
import json
import os
from utils.logger import log


class GenericScriptParser:
    def __init__(self, team_mapping):
        self.team_mapping = team_mapping

        # 角色名称简称映射
        self.char_lookup = {}
        for full_zh_name, data in self.team_mapping.items():
            cid, en_name, aliases = data
            self.char_lookup[full_zh_name] = (cid, en_name, full_zh_name)
            for alias in aliases:
                self.char_lookup[alias] = (cid, en_name, full_zh_name)

        # 基础动作映射
        self.action_mapping = {
            'a': "basic",
            'e': "skill",
            'r': "ult",
            'q': "echo",
            'z': "heavy",  # Z 对应普攻类型的重击
            'f': "execution",  # ✅ 保持你要求的独立类型
            's': "dodge",
            'j': "jump",
            '跳': "jump",
            '闪': "dodge",
        }

        self._build_regex()

    def _build_regex(self):
        char_keys = sorted(list(self.char_lookup.keys()), key=len, reverse=True)
        action_keys = "".join([re.escape(k) for k in self.action_mapping.keys()])

        parts = [
            r'\(.*?变奏.*?\)', r'（.*?变奏.*?）', r'切',
            "|".join([re.escape(k) for k in char_keys]),
            rf'[{action_keys}]\d*'
        ]
        self.pattern = re.compile("|".join(parts), re.IGNORECASE)

    def parse(self, text, start_char_id=1):
        tokens = self.pattern.findall(text)
        result = []
        current_char_id = start_char_id

        sorted_char_keys = sorted(list(self.char_lookup.keys()), key=len, reverse=True)

        for token in tokens:
            t = token.lower()
            if t == '切': continue

            # 1. 角色切换逻辑
            is_char_switch = False
            for char_key in sorted_char_keys:
                if char_key in t:
                    cid, en_name, full_zh_name = self.char_lookup[char_key]
                    if cid != current_char_id:
                        prefix = "变奏" if "变奏" in t else "切"
                        result.append({"type": "intro", "next_char": cid, "desc": f"{prefix}-{full_zh_name}"})
                        current_char_id = cid
                    is_char_switch = True
                    break
            if is_char_switch: continue

            # 2. 动作解析逻辑 [Action][Number]
            match = re.match(rf'^([^\d]+)(\d*)$', t)
            if not match: continue

            action_key, num = match.groups()
            action_type = self.action_mapping.get(action_key)
            if not action_type: continue

            display_names = {
                'a': "普攻", 'z': "重击", 'e': "技能", 'r': "解放",
                'q': "声骸", 'f': "处决", 'j': "跳跃", '跳': "跳跃", '闪': "闪避"
            }
            desc_name = display_names.get(action_key, action_key.upper())

            variant_parts = []

            # --- 💡 核心逻辑：确保 Z 永远带有 heavy 标签 ---
            if action_key == 'z':
                variant_parts.append("heavy")

            # --- 💡 核心逻辑：确保 F 永远带有 forte 标签 ---
            elif action_key == 'f':
                variant_parts.append("forte")

            if num:
                if action_key == 'a' and num == '1':
                    pass
                else:
                    variant_parts.append(num)

            action_dict = {
                "type": action_type,
                "desc": f"{desc_name}{num}"
            }

            if variant_parts:
                action_dict["variant"] = "_".join(variant_parts)

            if action_key == 'a' and num == '1':
                action_dict["force_general"] = True

            result.append(action_dict)

        return result