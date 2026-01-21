# configs/team_test.py

# 1. 队伍配置 (对应 assets 文件夹里的名字)
# 键必须是 int (1, 2, 3)
TEAM_CONFIG = {
    1: "Gabriella",  # 主角
    2: "Lupa",  # 秧秧
    3: "Moning"  # 炽霞
}

# 2. 初始站场角色 (比如刚进战斗是主角)
INITIAL_CHAR_INDEX = 1

# 3. 连招剧本
ROTATION_SCRIPT = [
    # === 主角 ===
    {"type": "skill", "desc": "E技能"},
    {"type": "basic", "desc": "普攻1"},
    {"type": "basic", "desc": "普攻2"},

    # === 切秧秧 ===
    # next_char: 2 表示切到 2号位
    {"type": "intro", "next_char": 2, "desc": "切秧秧"},

    # === 秧秧 ===
    {"type": "skill", "desc": "E 聚怪"},
    {"type": "ult", "desc": "R 大招"},

    # === 切炽霞 ===
    {"type": "intro", "next_char": 3, "desc": "切炽霞"},

    # === 炽霞 ===
    {"type": "skill", "desc": "E 突突突"},
    {"type": "skill", "variant": "2", "desc": "E 滑铲"},  # 假设有二段E
]