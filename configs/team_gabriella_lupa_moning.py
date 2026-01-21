# 角色映射：1=嘉(Gabriella), 2=莫(Moning), 3=露(Lupa)
TEAM_CONFIG = {1: "Gabriella", 2: "Moning", 3: "Lupa"}
INITIAL_CHAR_INDEX = 1

# 提取公共动作：三翅二踢
WINGS_KICK = [
    {"type": "basic", "desc": "A1"}, {"type": "basic", "desc": "A2"},
    {"type": "basic", "desc": "A3"}, {"type": "basic", "desc": "A4"},
    {"type": "dodge", "desc": "闪避"},
    {"type": "basic", "desc": "A1"}, {"type": "basic", "desc": "A2"},
    {"type": "basic", "desc": "A3"},
    {"type": "dodge", "desc": "闪避"},
    {"type": "basic", "desc": "A1"}, {"type": "basic", "desc": "A2"},
]

# 1. 启动轴 (Opener)
OPENER_SCRIPT = [
    # 嘉z
    {"type": "basic","force_general": True, "variant": "heavy", "desc": "嘉z 重击"},
    # 莫a1ra1 (a1 强制通用)
    {"type": "intro", "next_char": 2, "desc": "变奏-莫"},
    {"type": "basic", "force_general": True, "desc": "a1 普攻"},
    {"type": "ult", "desc": "R 大招"},
    {"type": "basic", "force_general": True, "desc": "a1 普攻"},
    # 露r enhanced_skill
    {"type": "intro", "next_char": 3, "desc": "变奏-露"},
    {"type": "ult", "desc": "R 大招"},
    {"type": "skill", "variant": "enhanced", "desc": "强化E"},
    # 莫a1a1
    {"type": "intro", "next_char": 2, "desc": "切莫"},
    {"type": "basic", "force_general": True, "desc": "a1"},
    {"type": "basic", "force_general": True, "desc": "a1"},
    # 露a1a1
    {"type": "intro", "next_char": 3, "desc": "切露"},
    {"type": "basic", "force_general": True, "desc": "a1"},
    {"type": "basic", "force_general": True, "desc": "a1"},
    # 嘉a1a1
    {"type": "intro", "next_char": 1, "desc": "切嘉"},
    {"type": "basic", "force_general": True, "desc": "a1"},
    {"type": "basic", "force_general": True, "desc": "a1"},
    # 露a1 莫a1 露a1
    {"type": "intro", "next_char": 3, "desc": "切露"}, {"type": "basic", "force_general": True, "desc": "a1"},
    {"type": "intro", "next_char": 2, "desc": "切莫"}, {"type": "basic", "force_general": True, "desc": "a1"},
    {"type": "intro", "next_char": 3, "desc": "切露"}, {"type": "basic", "force_general": True, "desc": "a1"},
    # 嘉z 露forte_skill
    {"type": "intro", "next_char": 1, "desc": "切嘉"}, {"type": "basic", "force_general": True,"variant": "heavy", "desc": "重击"},
    {"type": "intro", "next_char": 3, "desc": "切露"}, {"type": "skill", "variant": "forte", "desc": "核心E"},
    # 莫a1a1za2a2a2e2q
    {"type": "intro", "next_char": 2, "desc": "切莫"},
    {"type": "basic", "force_general": True, "desc": "a1"},
    {"type": "basic", "force_general": True, "desc": "a1"},
    {"type": "basic", "variant": "forte_heavy_1", "desc": "回路重击-1"},
    {"type": "basic", "variant": "2", "desc": "a2"},
    {"type": "basic", "variant": "2", "desc": "a2"},
    {"type": "basic", "variant": "2", "desc": "a2"},
    {"type": "skill", "variant": "enhanced_skill", "desc": "e2"},
    {"type": "echo", "desc": "Q 声骸"},
    # (变奏嘉贝) 嘉切露帕normal e1 e2
    {"type": "intro", "next_char": 1, "desc": "变奏-嘉"},
    {"type": "intro", "next_char": 3, "desc": "速切-露"},
    {"type": "skill", "variant": "1", "desc": "e1"},
    {"type": "skill", "variant": "2", "desc": "e2"},
    # (变奏嘉贝) 嘉qer
    {"type": "intro", "next_char": 1, "desc": "变奏-嘉"},
    {"type": "echo", "desc": "Q"},
    {"type": "skill", "variant": "forte_skill", "desc": "e2"},
    {"type": "ult", "desc": "R"},
    # 三翅二踢 z
    *WINGS_KICK,
    {"type": "basic", "variant": "heavy", "desc": "z 重击"},
    # (变奏露帕)
    {"type": "intro", "next_char": 3, "desc": "变奏-露"}
]

# 2. 循环轴 (Loop)
LOOP_SCRIPT = [
    # 露r enhanced_skill
    {"type": "ult", "desc": "R 大招"},
    {"type": "skill", "variant": "enhanced", "desc": "强化E"},
    # 莫ra1
    {"type": "intro", "next_char": 2, "desc": "切莫"},
    {"type": "ult", "desc": "R"}, {"type": "basic", "force_general": True, "desc": "a1"},
    # 露a1a1 嘉a1a1
    {"type": "intro", "next_char": 3, "desc": "切露"}, {"type": "basic", "force_general": True, "desc": "a1"}, {"type": "basic", "force_general": True, "desc": "a1"},
    {"type": "intro", "next_char": 1, "desc": "切嘉"}, {"type": "basic", "force_general": True, "desc": "a1"}, {"type": "basic", "force_general": True, "desc": "a1"},
    # 露a1 莫a1 嘉a1 露a1
    {"type": "intro", "next_char": 3, "desc": "切露"}, {"type": "basic", "force_general": True, "desc": "a1"},
    {"type": "intro", "next_char": 2, "desc": "切莫"}, {"type": "basic", "force_general": True, "desc": "a1"},
    {"type": "intro", "next_char": 1, "desc": "切嘉"}, {"type": "basic", "force_general": True, "desc": "a1"},
    {"type": "intro", "next_char": 3, "desc": "切露"}, {"type": "basic", "force_general": True, "desc": "a1"},
    # 嘉z 露forte skill
    {"type": "intro", "next_char": 1, "desc": "切嘉"}, {"type": "basic", "force_general": True, "variant": "heavy", "desc": "z"},
    {"type": "intro", "next_char": 3, "desc": "切露"}, {"type": "skill", "variant": "forte", "desc": "核心E"},
    # 莫a1a1a1za2a2a2e2q
    {"type": "intro", "next_char": 2, "desc": "切莫"},
    {"type": "basic", "force_general": True, "desc": "a1"},
    {"type": "basic", "force_general": True, "desc": "a1"},
    {"type": "basic", "force_general": True, "desc": "a1"},
    {"type": "basic", "variant": "heavy", "desc": "z"},
    {"type": "basic", "variant": "2", "desc": "a2"},
    {"type": "basic", "variant": "2", "desc": "a2"},
    {"type": "basic", "variant": "2", "desc": "a2"},
    {"type": "skill", "variant": "enhanced_skill", "desc": "e2"},
    {"type": "echo", "desc": "Q"},
    # (变奏嘉贝) 嘉切露帕e (变奏嘉贝) 嘉qer
    {"type": "intro", "next_char": 1, "desc": "变奏-嘉"},
    {"type": "intro", "next_char": 3, "desc": "速切-露"},
    {"type": "skill", "variant": "1", "desc": "e1"},
    {"type": "skill", "variant": "2", "desc": "e2"},
    {"type": "intro", "next_char": 1, "desc": "变奏-嘉"},
    {"type": "echo", "desc": "Q"}, {"type": "skill", "variant": "forte_skill", "desc": "e2"}, {"type": "ult", "desc": "R"},
    # 三翅二踢 z2 (变奏露帕)
    *WINGS_KICK,
    {"type": "basic", "variant": "heavy", "desc": "z2 重击"},
    {"type": "intro", "next_char": 3, "desc": "变奏-露"}
]