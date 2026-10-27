"""
连招导演（Director）—— 整个程序的状态机核心。

它要解决的问题
==============
《鸣潮》这类动作游戏里，"我按了键"和"角色打出动作"不是同一件事：

    玩家按下  ->  游戏在下一帧处理  ->  角色进入某段动作
              ->  动作播完（前摇+判定+后摇）前，新输入要么进缓冲、要么被丢弃
              ->  动作结束，缓冲里还有有效输入就自动接上

v1.1 之前的实现把"按键事件"直接当成"动作完成"，于是出现三类明显错位：

1. **连按跑飞**：普攻一段动画 0.4s，玩家 0.4s 内点了 5 下，游戏只打出 1~2 段，
   程序却推进了 5 格，提示立刻跑到十步开外。
2. **预输入空转**：玩家提前按了下一个键，程序马上推进；但游戏侧因为按得太早
   （超出它自己的缓冲窗口）把输入丢了，动作根本没出来。程序在自说自话。
3. **无法双键并行**：蓄力重击（按住）的同时放声骸（另一个键），两条时间线
   同时进行，线性链表结构表达不了。

v1.2/v1.3 的模型：**时间轴 + 输入缓冲 + 并行插入**
=============================================

    剧本指针  step_index          当前该做哪一步
    时间闸门  _gate_until         "同一颗键"的冷却到什么时候
    输入缓冲  _buffer             闸门关着时收到的、键名正确的输入先存着
    并行集合  _ahead_done         已经被"提前完成"的未来步（相对当前指针的偏移）

一次按键的完整旅程：

    松手 --> 键名对得上当前步？
              ├─ 手势（轻按/长按）也对
              │    ├─ 闸门已开  -> 直接推进
              │    └─ 闸门未开  -> 压进缓冲，等闸门开（这就是"预输入"）
              └─ 对不上当前步 -> 是不是蓄力中允许插入的动作？是就提前完成它

闸门什么时候关：**只有连续按同一颗键**
------------------------------------
这一点很关键，v1.3 之前搞错了。鸣潮里新动作的优先级很高——普攻还没打完
按技能，技能会直接打断普攻放出来；闪避更能取消一切。所以"要等动作播完"
这件事只对**同一颗键连点**成立（再点一下普攻不能凭空多打一段）。

因此 `_needs_gate()` 只在两种情况下关闸：

    刚完成那一步的物理键 == 下一步要按的物理键    （a -> a、a -> z 都算，共用攻击键）
    那一步显式声明 "uncancellable": true           （不可打断，比如长动画大招）

换键一律不等，程序立刻推进——这才和游戏里的观感一致。反过来，如果连点是
跨键的（a -> e），程序也不该拦，因为游戏本来就会打断。

缓冲项有寿命（`input_buffer_ms`，默认 250ms）。闸门开的那一刻，如果缓冲里
那一下已经超过寿命，说明玩家按得太早、游戏早就丢弃了 —— 那就**不推进**，
提示留在原格等玩家重按。这正是"程序空转"的解药。

连按为什么自动被治好了
--------------------
同一个动作的重复输入在缓冲里是**合并**的（只留一份、刷新时间戳）。
玩家狂按 5 下，缓冲里始终只有 1 项，闸门一开只会消耗 1 次 —— 推进 1 格。
玩家真正想连段时，会在闸门开后再按，那时是新的一次输入，正常消耗。

长短按判定（v1.1 引入，v1.2 移到输入层测量）
------------------------------------------
攻击键只有一个物理键：点一下是普攻、按住是重击。判定链是：

    InputListener 记录按下时刻，松手时把 duration 一起发上来  （测量）
    Director 按剧本要求裁决这个 duration 算不算数              （裁决）

剧本每一步要求什么手势，由 resolve_press_mode() 决定：

    type == "heavy"        -> 必须长按
    type == "basic"        -> 必须轻按
    action["hold"] = True  -> 必须长按（特殊技能长按走这里）
    action["hold"] = False -> 必须轻按
    action["hold"] = 0.8   -> 必须长按，且用 0.8s 作为该动作的阈值
    action["hold_time"]    -> 单独覆盖阈值
    其它类型               -> 不检查时长（老剧本兼容）

剧本中一步（action）的字段
------------------------
    type        : basic / heavy / skill / ult / echo / jump / dodge / execution / intro
    desc        : 显示用的中文描述
    variant     : 变体标记（如 "2" / "heavy" / "forte"），参与图标匹配与样式
    next_char   : 仅 intro 使用，切到几号位
    custom_icon : 指定具体 png 文件名
    force_general : 强制从通用素材库取图
    hold / hold_time : 手势要求（见上），一般不用手写，heavy/basic 已自动推导
    duration_ms : 这一步动作占用多久（覆盖 config 里的同类默认值）
    parallel    : 显式声明"可以在上一步还在进行时提前按下"
"""

import time
from collections import namedtuple

from utils.config_manager import config
from utils.logger import log


# ============================================================ 手势判定
# 这三个模式是"剧本要求"，不是"玩家实际做了什么"。
MODE_ANY = "any"    # 不关心长短按，只要求键名匹配（老剧本的兼容行为）
MODE_TAP = "tap"    # 必须轻按：时长 < 阈值
MODE_HOLD = "hold"  # 必须长按：时长 >= 阈值

DEFAULT_HOLD_SECONDS = 0.5


def is_long_press(duration, threshold=DEFAULT_HOLD_SECONDS):
    """这一下算不算长按。"""
    return duration >= threshold


def is_tap(duration, threshold=DEFAULT_HOLD_SECONDS):
    """这一下算不算轻按（长按的补集）。"""
    return duration < threshold


def classify_press(duration, threshold=DEFAULT_HOLD_SECONDS):
    """把时长翻译成手势名，返回 MODE_TAP 或 MODE_HOLD。"""
    return MODE_HOLD if is_long_press(duration, threshold) else MODE_TAP


def press_matches(duration, mode, threshold=DEFAULT_HOLD_SECONDS, strict_tap=True):
    """
    这一下按压是否满足期望模式。

    :param duration:   按住时长（秒）
    :param mode:       MODE_TAP / MODE_HOLD / MODE_ANY
    :param threshold:  长按阈值（秒）
    :param strict_tap: 期望轻按时是否也要卡上限。
                       关掉后退化成"只看键名"，用于习惯按住攻击键连打的玩家。
    :return: True 表示这一下可以算作该动作
    """
    if mode == MODE_HOLD:
        # 长按必须真的按够久，这是区分重击和普攻的核心
        return is_long_press(duration, threshold)
    if mode == MODE_TAP:
        return True if not strict_tap else is_tap(duration, threshold)
    return True


# ============================================================ 动作占位时长
# 单位毫秒：一次动作从"确认打出"到"能接下一个输入"的典型间隔。
#
# !!! 这张表是**手感参数**，不是游戏数据 !!!
# 数值不需要等于动画真实帧数，只要和你的手感对得上就行：
#   - 觉得提示总是慢半拍 -> 调小
#   - 觉得提示总是抢在前面 -> 调大
# 直接改 config.json 的 timing.durations_ms 即可，改这里只影响兜底值。
DEFAULT_DURATIONS_MS = {
    "basic": 290,       # 普攻一段
    "heavy": 700,       # 重击出手到能接下一个
    "skill": 520,       # 共鸣技能
    "ult": 1100,        # 共鸣解放（变身/大招动画长）
    "echo": 520,        # 声骸技能
    "execution": 600,   # 处决
    "dodge": 320,       # 闪避
    "jump": 280,        # 跳跃
    "intro": 500,       # 变奏出场（切人动画）
}


# ============================================================ 内部数据结构

# 缓冲里的一条输入
#   action     动作名
#   pressed_at 按下时刻（用它算寿命，因为游戏也是从按下开始缓冲）
#   duration   按住时长
#   offset     打算消耗哪一步：0 = 当前步，>0 = 提前完成未来的第 offset 步
_BufferedPress = namedtuple("_BufferedPress", "action pressed_at duration offset")

# 历史栈里的一条快照：回退要能把时间轴状态一起复原，否则回退后闸门时间错乱
_State = namedtuple(
    "_State",
    "step_index is_in_opener char_idx ahead_done gate_until step_started",
)


class Director:
    """
    连招导演：持有剧本、播放指针、时间轴与输入缓冲。

    职责
    ----
    1. 持有剧本（启动轴 opener / 循环轴 loop）和播放指针 step_index。
    2. 收到玩家的"动作名 + 按下/松手 + 按住时长"，判定是否推进。
    3. 维护当前在场角色槽位 current_char_idx（切人动作会改动它）。
    4. 通过 history_stack 支持回退（最多 20 步），回退是状态级的、不是纯视觉的。
    5. 维护时间轴（闸门）与输入缓冲，让"提示"和"游戏里真实发生的动作"对齐。
    """

    MAX_HISTORY = 20                 # 回退栈深度
    MAX_BUFFER = 6                   # 输入缓冲最多存几条（正常人不会超过 3）
    PARALLEL_LOOKAHEAD = 3           # 并行插入最多往后看几步

    # 无需等待松手的动作：按下就推进
    INSTANT_TYPES = ("intro", "dodge", "jump")

    # 共用同一个物理键的动作族：族内可以互相触发，最终由"按压时长"裁决。
    # config.json 的 keymaps 里 basic 绑的是鼠标左键 / 手柄 B 键，没有单独的
    # heavy 键位，所以在 heavy 期望下收到的 input_action 通常是 "basic"。
    SHARED_KEY_FAMILY = {
        "basic": ("basic", "heavy"),
        "heavy": ("basic", "heavy"),
    }

    # 允许"上一步还在进行时提前按"的动作组合：(上一步类型, 下一步类型)。
    #
    # v1.3 改为**默认空**：鸣潮里"蓄力中能放声骸"是角色特性，不是通用机制
    # （比如只有琳奈能这么接，莫宁/爱弥斯同位置就不行）。
    # 所以并行一律靠剧本那一步显式写 "parallel": true 来声明；
    # 如果以后确认某类组合全局通用，再往 config 的 timing.auto_parallel 里加。
    DEFAULT_AUTO_PARALLEL = []

    def __init__(self, team_config, opener_script, loop_script, start_char_index, asset_mgr,
                 hold_threshold=None, strict_tap=None, clock=None):
        """
        :param team_config:      {1: "Aemeath", 2: "Lynae", 3: "Mornye"}
        :param opener_script:    启动轴动作数组
        :param loop_script:      循环轴动作数组
        :param start_char_index: 起手时在场的角色槽位
        :param asset_mgr:        AssetManager，用于把动作翻译成图标路径
        :param hold_threshold:   长按阈值(秒)，不传则读 config 的 settings.heavy_hold_time
        :param strict_tap:       轻按是否也卡时长上限，不传则读 settings.strict_tap_check
        :param clock:            计时函数，默认 time.monotonic。单测可注入假时钟。
        """
        self.team = team_config
        self.opener = opener_script
        self.loop = loop_script
        self.asset_mgr = asset_mgr

        self.is_in_opener = True if self.opener else False
        self.step_index = 0
        self.current_char_idx = start_char_index

        # ---- 计时 ----
        self._clock = clock or time.monotonic

        # ---- 手势判定 ----
        self.hold_threshold = self._read_hold_threshold(hold_threshold)
        self.strict_tap_check = self._read_strict_tap(strict_tap)

        # ---- 时间轴 / 缓冲（v1.2）----
        self.timing_enabled = bool(config.get("timing.enabled", True))
        self.parallel_enabled = bool(config.get("timing.enable_parallel", True))
        self.durations_ms = self._read_durations()
        self.character_durations = self._read_character_durations()
        self.buffer_window = self._read_buffer_window()

        # 第二条时间轴（并行轨）按需启用：
        # 加载剧本时先扫一遍，没有任何"可并行"的地方就完全跳过这套逻辑，
        # 省下每次按键都要往后看三步的开销，也避免无谓的状态/窗口。
        self.auto_parallel_pairs = self._read_auto_parallel()
        self._has_parallel = self._detect_parallel(opener_script, loop_script)
        if self._has_parallel and self.parallel_enabled:
            log.info("剧本含可并行动作，启用第二条时间轴（并行轨）")
        elif self._has_parallel:
            log.info("剧本含可并行动作，但 config 里关闭了并行，按单轨运行")
        else:
            log.info("剧本无并行动作，跳过第二条时间轴")

        self._gate_until = 0.0        # 当前步最早可被接受的时刻
        self._step_started_at = 0.0   # 当前步的生效时刻（用于学时长、算进度）
        self._buffer = []             # list[_BufferedPress]
        self._ahead_done = set()      # 已提前完成的未来步偏移集合

        # 按下记录：动作名 -> (推进序号, 按下时刻)
        # 推进序号用来判断"这次松手所对应的按下，是否已经过期作废"
        self._seq = 0
        self._down_seq = {}
        self._down_at = {}

        # 最近一次"键名对上了、但按得太短/太久"的原因（tap/hold/None）。
        # main 用它决定要不要让悬浮窗闪一下红框，让玩家知道"按了但不算"。
        self.last_press_reject = None

        # 时长学习样本：动作种类 -> 观测到的自然间隔列表。
        # 只在 timing.enabled=false 时有意义（闸门开着，间隔就是玩家自然节奏）。
        self.timing_samples = {}

        # 历史状态栈
        self.history_stack = []

    # ================================================================ 配置读取

    @classmethod
    def _read_hold_threshold(cls, override=None):
        """长按阈值：构造参数 > config > 兜底值。"""
        if override is not None:
            try:
                value = float(override)
                if value > 0:
                    return value
            except (TypeError, ValueError):
                pass

        raw = config.get("settings.heavy_hold_time", DEFAULT_HOLD_SECONDS)
        try:
            value = float(raw)
            return value if value > 0 else DEFAULT_HOLD_SECONDS
        except (TypeError, ValueError):
            return DEFAULT_HOLD_SECONDS

    @classmethod
    def _read_strict_tap(cls, override=None):
        """轻按是否卡上限：构造参数 > config > 默认开启。"""
        if override is not None:
            return bool(override)
        return bool(config.get("settings.strict_tap_check", True))

    @staticmethod
    def _read_durations():
        """动作占位时长表：config 里写的覆盖代码里的兜底值。"""
        table = dict(DEFAULT_DURATIONS_MS)
        custom = config.get("timing.durations_ms", {}) or {}
        if isinstance(custom, dict):
            for key, value in custom.items():
                try:
                    table[str(key)] = max(0.0, float(value))
                except (TypeError, ValueError):
                    continue
        return table

    @staticmethod
    def _read_character_durations():
        """
        角色级时长覆盖表：{角色英文名: {动作类型: 毫秒}}。

        这是"按角色差异化"的**数据入口**，不是代码入口。
        绝大多数角色之间的差别只是数值不同（前后摇长短），填表即可，
        不需要为每个角色写一个类。
        """
        raw = config.get("timing.character_durations", {}) or {}
        table = {}
        if isinstance(raw, dict):
            for char_name, per_type in raw.items():
                if not isinstance(per_type, dict):
                    continue
                fixed = {}
                for action_type, value in per_type.items():
                    try:
                        fixed[str(action_type)] = max(0.0, float(value))
                    except (TypeError, ValueError):
                        continue
                if fixed:
                    table[str(char_name)] = fixed
        return table

    @classmethod
    def _read_auto_parallel(cls):
        """
        读取"全局允许并行的动作组合"。

        默认是空的：鸣潮里"蓄力中放声骸"是**角色特性**而非通用机制，
        统一放行会让不该并行的角色也被提前消耗掉一步。
        想让某类组合全局生效，在 config 里写：
            "timing": { "auto_parallel": [["heavy", "echo"]] }
        """
        raw = config.get("timing.auto_parallel", None)
        if raw is None:
            raw = cls.DEFAULT_AUTO_PARALLEL

        pairs = set()
        if isinstance(raw, (list, tuple)):
            for item in raw:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    pairs.add((str(item[0]), str(item[1])))
        return pairs

    def _detect_parallel(self, opener, loop):
        """
        扫一遍剧本，判断有没有需要"第二条时间轴"的步。

        判定条件（两者满足其一）：
            - 某一步显式声明 "parallel": true
            - 相邻两步的类型组合出现在 config 的 auto_parallel 里

        注意要检查"启动轴最后一步 -> 循环轴第一步"这个跨界处，
        否则跨轴的并行会被漏掉。
        """
        for script in (opener, loop):
            if not script:
                continue
            for i in range(len(script) - 1):
                if self._pair_is_parallel(script[i], script[i + 1]):
                    return True

        if opener and loop and self._pair_is_parallel(opener[-1], loop[0]):
            return True

        return False

    def _pair_is_parallel(self, prev_action, next_action):
        """
        相邻两步是否构成一次可并行插入。

        显式声明优先：写 true 就并行，写 false 就强制不并行（覆盖全局配置）。
        """
        declared = next_action.get("parallel")
        if isinstance(declared, bool):
            return declared
        return (prev_action.get("type"), next_action.get("type")) in self.auto_parallel_pairs

    @staticmethod
    def _read_buffer_window():
        """
        输入缓冲寿命（秒）。超过这个年纪的预输入视为"按太早、游戏已丢弃"。

        250ms 是实机调过的手感值：300ms 时经常出现"按早了也算"，提示会跑快半拍。
        """
        try:
            ms = float(config.get("timing.input_buffer_ms", 250))
        except (TypeError, ValueError):
            ms = 250.0
        return max(0.0, ms) / 1000.0

    # ================================================================ 剧本访问

    def get_current_script(self):
        """当前生效的剧本文本（启动轴或循环轴）。"""
        return self.opener if self.is_in_opener else self.loop

    def get_overlay_meta(self):
        """
        悬浮窗右上角要显示的"我在轴的哪儿"。

        没跟剧本推进绑死，纯粹是给界面的元信息，
        所以单独开一个方法，而不是塞进每个槽位字典里。
        """
        script = self.get_current_script() or []
        total = len(script)
        index = self.step_index if total else 0
        return {
            "phase": "opener" if self.is_in_opener else "loop",
            "index": max(0, min(index, max(0, total - 1))),
            "total": total,
        }

    # ================================================================ 手势解析

    def resolve_press_mode(self, action):
        """
        解析某一步要求的手势，返回 (模式, 阈值)。

        解析优先级：显式 hold > 显式 hold_time > 动作类型默认规则。
        """
        # ---- 阈值：动作自带的 hold_time 优先，其次全局配置 ----
        threshold = self.hold_threshold
        has_custom_time = False
        raw_threshold = action.get("hold_time")
        if raw_threshold is not None:
            try:
                value = float(raw_threshold)
                if value > 0:
                    threshold = value
                    has_custom_time = True
            except (TypeError, ValueError):
                pass

        # ---- 模式：显式 hold 字段优先 ----
        declared = action.get("hold")
        # 注意 bool 是 int 的子类，必须先判 bool，否则 True 会被当成数字
        if isinstance(declared, bool):
            return (MODE_HOLD if declared else MODE_TAP), threshold
        if isinstance(declared, (int, float)):
            value = float(declared)
            return MODE_HOLD, (value if value > 0 else threshold)

        # 只写了 hold_time 却没写 hold：显然是想自定义长按阈值
        if has_custom_time:
            return MODE_HOLD, threshold

        # ---- 没写就用类型默认规则 ----
        action_type = action.get("type")
        if action_type == "heavy":
            return MODE_HOLD, threshold
        if action_type == "basic":
            return MODE_TAP, threshold
        return MODE_ANY, threshold

    def _duration_of(self, action, char_name=None):
        """
        这一步动作要占用多久（秒）。0 表示不占用、可立即接下一个。

        优先级：剧本里这一步的 duration_ms > 角色级覆盖 > 全局同类默认值。
        timing.enabled=false 时一律返回 0，退化成 v1.1 的事件驱动行为。
        """
        if not self.timing_enabled:
            return 0.0

        raw = action.get("duration_ms")
        if raw is not None:
            try:
                value = float(raw)
                if value >= 0:
                    return value / 1000.0
            except (TypeError, ValueError):
                pass

        action_type = action.get("type")

        if char_name:
            per_char = self.character_durations.get(char_name)
            if per_char and action_type in per_char:
                return per_char[action_type] / 1000.0

        return self.durations_ms.get(action_type, 0.0) / 1000.0

    def _peek_action(self, offset):
        """
        按**真实播放顺序**取指针之后第 offset 步的动作（offset=0 即当前步）。

        为什么要这个函数
        --------------
        剧本被拆成"启动轴 + 循环轴"两段，播放时是首尾相接的。
        但如果按「对当前剧本取模」来预览，启动轴快结束时往后看两步就会
        绕回启动轴开头 —— 于是最后几步明明该显示循环轴的内容，却显示成
        开头的普攻，按一步之后才"瞬间变对"。这个 bug 就是这么来的。

        这里按播放顺序跨过启动轴→循环轴的边界，绕完循环轴一圈后回到循环轴开头。

        :return: (action, 所属剧本)；已经没得取了返回 (None, None)
        """
        if offset < 0:
            return None, None

        if self.is_in_opener and self.opener:
            remain = max(0, len(self.opener) - self.step_index)
            if offset < remain:
                return self.opener[self.step_index + offset], self.opener

            # 越过启动轴末尾，接着从循环轴开头数
            offset -= remain
            if not self.loop:
                return None, None
            return self.loop[offset % len(self.loop)], self.loop

        if not self.loop:
            return None, None
        return self.loop[(self.step_index + offset) % len(self.loop)], self.loop

    def _key_matches(self, expected_action, input_action):
        """
        动作名的匹配（不涉及时长）。

        切人要匹配到具体槽位（intro_2）；basic/heavy 在同一族里互相认可，
        最终是长按还是轻按交给 press_matches() 裁决。
        """
        expected_type = expected_action.get("type")

        if expected_type == "intro":
            return input_action == f"intro_{expected_action.get('next_char')}"

        if input_action == expected_type:
            return True

        return input_action in self.SHARED_KEY_FAMILY.get(expected_type, ())

    @classmethod
    def _physical_key(cls, action):
        """
        这一步落在哪颗**物理键**上。

        为什么要这个：鸣潮里新动作的优先级很高——普攻没打完按技能，技能会直接
        打断普攻放出来；闪避更是能取消一切。所以"动作没播完就要等"这件事，
        只对**同一颗键连按**成立（再点一下普攻不能凭空多打一段）。
        换键不需要等，程序也就不该拦。

        basic / heavy 共用攻击键，归成同一类；切人按的是不同方向键，按槽位区分。
        """
        action_type = action.get("type")
        if action_type in ("basic", "heavy"):
            return "attack"
        if action_type == "intro":
            return f"intro_{action.get('next_char')}"
        return action_type

    def _needs_gate(self, finished_action):
        """
        刚完成的这一步，要不要让下一个输入"等一会儿"。

        只有两种情况需要：
            1. 下一步按的是同一颗键（连点普攻 / 连段）
            2. 这一步显式声明了 uncancellable（不可打断，比如长动画的大招）
        """
        if finished_action.get("uncancellable"):
            return True

        next_action, _script = self._peek_action(0)
        if next_action is None:
            return False
        return self._physical_key(finished_action) == self._physical_key(next_action)

    # ================================================================ 界面数据

    def get_visual_data(self, preview_count=3):
        """
        生成悬浮窗需要的槽位数据。

        :param preview_count: 向后预览的步数，返回长度为 preview_count + 1 的列表
        :return: [历史, 当前, 预告1, 预告2, ...]，每项是一个 dict
        """
        result = []
        current_script = self.get_current_script()
        if not current_script:
            return []

        total_steps = len(current_script)

        # ---------- 历史槽：显示上一步做过什么 ----------
        if not self.history_stack:
            result.append({"icon_path": None, "btn_path": None, "desc": "START",
                           "is_history": True, "is_current": False})
        else:
            snapshot = self.history_stack[-1]
            h_idx, h_opener, h_char = snapshot.step_index, snapshot.is_in_opener, snapshot.char_idx
            prev_script = self.opener if h_opener else self.loop

            # 防御：理论上不会越界，但历史剧本切换瞬间可能读到脏数据
            if not prev_script or h_idx >= len(prev_script):
                result.append({"icon_path": None, "btn_path": None, "desc": "",
                               "is_history": True, "is_current": False})
            else:
                prev_action = prev_script[h_idx]

                # 历史动作若是切人，应该显示"切过去的那个角色"的头像，
                # 而不是切换前的角色（h_char 是推进前的槽位）。
                if prev_action.get("type") == "intro" and prev_action.get("next_char"):
                    display_char_idx = prev_action["next_char"]
                else:
                    display_char_idx = h_char

                display_name = self.team.get(display_char_idx, "Unknown")
                icon_path = self.asset_mgr.get_icon_path(display_name, prev_action["type"],
                                                         prev_action.get("variant"))
                result.append({
                    "desc": prev_action.get("desc", ""),
                    "icon_path": icon_path,
                    "btn_path": None,
                    "type": prev_action.get("type", ""),
                    "variant": prev_action.get("variant"),
                    "char_name": display_name,
                    "is_current": False,
                    "is_history": True
                })

        # ---------- 当前 / 未来槽 ----------
        # 用 _peek_action 按真实播放顺序取，才能正确跨过启动轴→循环轴的边界。
        # 预测未来角色变化：切人动作会改变后续步骤的"归属角色"。
        # 已被并行提前完成的步要跳过，但虚拟角色仍然要跟着推进，否则会算错。
        virtual_char_idx = self.current_char_idx
        offset = 0
        produced = 0
        guard = 0
        guard_limit = total_steps + preview_count + self.PARALLEL_LOOKAHEAD + 8

        # 当前步允许并行时，给"下一个"槽位打一个可同时按的标记
        current_action, _ = self._peek_action(0)
        current_is_hold = False
        if current_action is not None:
            current_mode, _t = self.resolve_press_mode(current_action)
            current_is_hold = (current_mode == MODE_HOLD)

        while produced < preview_count and guard < guard_limit:
            guard += 1
            action, _script = self._peek_action(offset)
            if action is None:
                break

            display_char_idx = virtual_char_idx

            if action["type"] == "intro":
                next_c = action.get("next_char")
                if next_c:
                    # 切人后，屏幕上该显示新角色的头像
                    display_char_idx = next_c
                    virtual_char_idx = next_c

            # 已被并行提前完成的步不再出现在预览里，让后面的步递补上来
            if offset not in self._ahead_done:
                # 这一步能不能趁当前动作还没结束就先按下去
                parallel_hint = False
                if (produced == 1 and current_is_hold and self._has_parallel
                        and self.parallel_enabled and self._can_parallel(current_action, action)):
                    parallel_hint = True

                result.append(self._build_slot(
                    action, display_char_idx,
                    is_current=(produced == 0), parallel_hint=parallel_hint))
                produced += 1

            offset += 1

        return result

    def _build_slot(self, action, char_idx, is_current=False, parallel_hint=False):
        """
        把一步动作翻译成悬浮窗要的槽位字典。

        抽成一个函数，是因为主队列、并行轨小窗要的东西完全一样，
        分开写迟早会漏字段。
        """
        char_name = self.team.get(char_idx, "Unknown")
        target_idx = action.get("next_char") if action["type"] == "intro" else None

        icon_path = self.asset_mgr.get_icon_path(
            char_name, action["type"], action.get("variant"),
            action.get("force_general", False), action.get("custom_icon"))
        btn_path = self.asset_mgr.get_button_path(action["type"], target_index=target_idx)

        press_mode, press_threshold = self.resolve_press_mode(action)

        return {
            "desc": action.get("desc", ""),
            "icon_path": icon_path,
            "btn_path": btn_path,
            # 头像单独查一次：悬浮窗左上角要长驻显示"现在是谁的轴"，
            # 而当前步可能是技能图，不能拿它当头像用
            "char_avatar": self.asset_mgr.get_icon_path(char_name, "intro"),
            "type": action["type"],
            "variant": action.get("variant"),
            "char_name": char_name,
            "press_mode": press_mode,
            "hold_threshold": press_threshold,
            "parallel_hint": parallel_hint,
            "is_current": is_current,
            "is_history": False,
        }

    def get_parallel_slot(self):
        """
        当前有没有"另一条时间线可以立刻按"的动作；有就返回它的槽位数据。

        并行轨小窗靠它决定显示什么、要不要显示：
            - 当前步不是长按类（没在蓄力）-> 没有支线
            - 后面几步里没有声明 parallel 的动作    -> 没有支线
            - 支线已经被提前完成（在 _ahead_done 里）-> 不显示

        注意这里**不要求玩家已经按住**：蓄力之前就该让玩家知道
        "这一步还有一支可以同时按"，否则只会在按下之后突然冒出来。
        """
        if not self._has_parallel or not self.parallel_enabled:
            return None
        if not self.get_current_script():
            return None

        current_action, _script = self._peek_action(0)
        if current_action is None:
            return None

        mode, _threshold = self.resolve_press_mode(current_action)
        if mode != MODE_HOLD:
            return None

        for offset in range(1, self.PARALLEL_LOOKAHEAD + 1):
            if offset in self._ahead_done:
                continue
            candidate, _script = self._peek_action(offset)
            if candidate is None:
                break
            if not self._can_parallel(current_action, candidate):
                continue
            return self._build_slot(candidate, self.current_char_idx, parallel_hint=True)

        return None

    def get_gate_state(self, now=None):
        """
        当前这一步"还要占位多久"，给悬浮窗画进度条用。

        :return: (剩余秒数, 总秒数)；不占位时返回 (0.0, 0.0)
        """
        total = self._gate_until - self._step_started_at
        if total <= 0:
            return 0.0, 0.0

        if now is None:
            now = self._clock()
        remain = self._gate_until - now
        if remain <= 0:
            return 0.0, total
        return min(remain, total), total

    # ================================================================ 输入处理

    def input_received(self, input_action, is_down, duration=None, now=None):
        """
        处理一次按键事件。

        :param input_action: 动作名，如 "basic" / "intro_2" / "rollback"
        :param is_down:      True 按下，False 松开
        :param duration:     按住时长（秒）。由 InputListener 测量后带上来；
                             传 None 或负数时本类用自己的时间戳兜底估算。
        :param now:          当前时刻，默认取 clock()。单测注入假时钟用。
        :return: True 表示状态推进了（或并行步被完成），界面需要刷新
        """
        if now is None:
            now = self._clock()

        # 每次事件都重置拒绝原因，调用方只需在返回 False 后读一次
        self.last_press_reject = None

        current_script = self.get_current_script()
        if not current_script or self.step_index >= len(current_script):
            return False

        if is_down:
            return self._handle_press(input_action, current_script, now)

        return self._handle_release(input_action, current_script, duration, now)

    # ------------------------------------------------------------ 按下

    def _handle_press(self, input_action, current_script, now):
        """
        按下：记录时刻，并在"瞬时动作"上立刻推进。

        非瞬时动作按下时不裁决——因为此时还不知道玩家会按多久。
        """
        current = current_script[self.step_index]
        expected_type = current.get("type")

        # 记下"按下时程序推进到哪了"，松手时若已变化就丢弃这次按压，
        # 避免"按住 A 键期间 B 键触发了推进，松手又把 A 算一遍"。
        self._down_seq[input_action] = self._seq
        self._down_at[input_action] = now

        if expected_type not in self.INSTANT_TYPES:
            return False

        if not self._key_matches(current, input_action):
            return False

        # 瞬时动作没有长短按语义：按下即推进
        if now >= self._gate_until:
            log.debug(f"瞬发动作匹配: {input_action}")
            self._commit_current(now)
            return True

        # 闸门还没开：把这次按下当作预输入存起来，稍后由 tick() 消费。
        # 存完要清掉按下记录，否则松手时会被当成一次新的输入重复处理。
        self._down_seq.pop(input_action, None)
        self._down_at.pop(input_action, None)
        self._buffer_append(input_action, now, 0.0, 0)
        return False

    # ------------------------------------------------------------ 松手

    def _handle_release(self, input_action, current_script, duration, now):
        """
        松手：做出最终裁决。

        这里是"重击 vs 普攻"真正被区分开的地方，也是"预输入"真正生效的地方。
        """
        down_seq = self._down_seq.pop(input_action, None)
        down_at = self._down_at.pop(input_action, None)

        # 没记录到按下（例如程序启动前就按着这个键），忽略
        if down_seq is None or down_at is None:
            return False

        # 按下到松手之间指针变过 => 这次按压已经作废（多半是按下时已推进）
        if down_seq != self._seq:
            log.debug(f"松手忽略（期间已推进）: {input_action}")
            return False

        # InputListener 没带时长（比如启动瞬间的残留按键）就自己估一个
        if duration is None or duration < 0:
            duration = max(0.0, now - down_at)

        current = current_script[self.step_index]

        # ---------- 情况 1：按的就是当前这一步 ----------
        if self._key_matches(current, input_action):
            mode, threshold = self.resolve_press_mode(current)

            if not press_matches(duration, mode, threshold, self.strict_tap_check):
                # 键按对了但手势不对：不推进，只记录原因让界面提示一下
                self.last_press_reject = mode
                log.debug(
                    f"手势不符: 期望 {current.get('type')}({mode}, 阈值 {threshold:.2f}s)，"
                    f"实际按住 {duration:.3f}s"
                )
                return False

            if now >= self._gate_until:
                log.debug(f"动作完成: {input_action} 按住 {duration:.3f}s（{mode}）")
                self._commit_current(now)
                return True

            # 闸门还关着 = 玩家按早了。存起来，闸门开的瞬间看它还"活着"就推进。
            self._buffer_append(input_action, now - duration, duration, 0)
            log.debug(f"预输入: {input_action} 提前 {self._gate_until - now:.3f}s")
            return False

        # ---------- 情况 2：当前步还在进行，但按的是允许并行的未来步 ----------
        target_offset = self._find_parallel_target(input_action, duration, now)
        if target_offset:
            self._ahead_done.add(target_offset)
            log.info(f"并行插入: {input_action} 提前完成了第 {target_offset} 步")
            return True

        # ---------- 情况 3：按错了，静默忽略 ----------
        return False

    # ============================================================== 输入缓冲

    def _buffer_append(self, action, pressed_at, duration, offset):
        """
        把一条输入压进缓冲。

        同一个动作 + 同一个目标步只保留一份，并用最新一次按下的时间戳刷新它。
        这就是"连按 5 下只算 1 下"的实现：玩家狂按不会堆出 5 条待办。
        """
        for i, item in enumerate(self._buffer):
            if item.action == action and item.offset == offset:
                self._buffer[i] = _BufferedPress(action, pressed_at, duration, offset)
                return

        self._buffer.append(_BufferedPress(action, pressed_at, duration, offset))
        if len(self._buffer) > self.MAX_BUFFER:
            self._buffer.pop(0)

    def _drop_expired(self, now):
        """丢掉已经"按太早、游戏侧必然丢弃"的预输入。"""
        if not self._buffer:
            return
        window = self.buffer_window
        self._buffer = [i for i in self._buffer if now - i.pressed_at <= window]

    def tick(self, now=None):
        """
        时间轴心跳：闸门一开就把缓冲里合法的预输入兑现掉。

        由主窗口的 QTimer 以 ~30Hz 调用，开销可以忽略（缓冲通常为空，
        空就直接 return，连时间都不用取）。

        :return: True 表示这一步被推进了，界面需要刷新
        """
        if not self._buffer:
            return False

        if now is None:
            now = self._clock()

        self._drop_expired(now)

        # 闸门还关着（动作没做完），继续等
        if now < self._gate_until or not self._buffer:
            return False

        current_script = self.get_current_script()
        if not current_script:
            return False

        current = current_script[self.step_index]
        mode, threshold = self.resolve_press_mode(current)

        for index, item in enumerate(self._buffer):
            if item.offset != 0:
                continue
            if not self._key_matches(current, item.action):
                continue
            if not press_matches(item.duration, mode, threshold, self.strict_tap_check):
                continue

            self._buffer.pop(index)
            log.debug(f"预输入兑现: {item.action}（迟滞 {now - item.pressed_at:.3f}s）")
            self._commit_current(now)
            return True

        return False

    # ============================================================== 并行判定

    def _is_holding_current(self, current):
        """
        玩家是不是正按住"当前这一步对应的键"。

        重击蓄力就是这个状态：按下还没松，动作在进行中，
        此时允许插入别的动作（比如声骸）。
        """
        for action in self._down_at:
            if self._key_matches(current, action):
                return True
        return False

    def _can_parallel(self, current, candidate):
        """某一步能不能在当前步进行中被提前按下。"""
        # 切人会改变在场角色，和别的时间线纠缠太深，一律不允许并行
        if candidate.get("type") == "intro":
            return False
        return self._pair_is_parallel(current, candidate)

    def _find_parallel_target(self, input_action, duration, now):
        """
        在当前步还在进行时，看这次按键能不能提前完成后面某一步。

        :return: 目标步相对当前指针的偏移（>0）；不行返回 0
        """
        # 剧本里根本没有可并行的地方，直接短路，不做任何向后预览
        if not self._has_parallel or not self.parallel_enabled:
            return 0

        current_script = self.get_current_script()
        if not current_script:
            return 0

        current = current_script[self.step_index]

        # 只有当"当前步是长按类动作、且玩家还按着"时才开放插入窗口。
        # 这就是"蓄力中可以放声骸"的判定条件。
        mode, _ = self.resolve_press_mode(current)
        if mode != MODE_HOLD or not self._is_holding_current(current):
            return 0

        for offset in range(1, self.PARALLEL_LOOKAHEAD + 1):
            if offset in self._ahead_done:
                continue

            candidate, _script = self._peek_action(offset)
            if candidate is None:
                break

            if not self._can_parallel(current, candidate):
                continue
            if not self._key_matches(candidate, input_action):
                continue

            cand_mode, cand_threshold = self.resolve_press_mode(candidate)
            if not press_matches(duration, cand_mode, cand_threshold, self.strict_tap_check):
                continue

            return offset

        return 0

    # ================================================================ 状态推进

    def _advance_pointer(self):
        """指针前进一格，启动轴走完后无缝切入循环轴。"""
        self.step_index += 1

        if self.is_in_opener:
            if not self.opener or self.step_index >= len(self.opener):
                log.info("启动轴完成，进入循环轴")
                self.is_in_opener = False
                self.step_index = 0
        else:
            if self.loop and self.step_index >= len(self.loop):
                self.step_index = 0

    def _shift_ahead(self):
        """
        指针前进后，并行偏移集合整体左移一格。

        注意必须保留 1->0：偏移 0 表示"这一步已经被提前完成，轮到时直接跳过"，
        交给调用方的 while 循环处理。过滤掉它会导致提前完成的步被重复执行。
        """
        self._ahead_done = {offset - 1 for offset in self._ahead_done if offset >= 1}

    def _push_history(self):
        """把"还没变之前"的状态压栈，供回退使用。"""
        self.history_stack.append(_State(
            step_index=self.step_index,
            is_in_opener=self.is_in_opener,
            char_idx=self.current_char_idx,
            ahead_done=frozenset(self._ahead_done),
            gate_until=self._gate_until,
            step_started=self._step_started_at,
        ))
        if len(self.history_stack) > self.MAX_HISTORY:
            self.history_stack.pop(0)

    def _record_timing_sample(self, action, elapsed):
        """
        记一条"这一步实际用了多久"的样本。

        只有 timing.enabled=false（闸门关掉）时样本才有意义：
        那时的间隔就是玩家真实的操作节奏，可以作为配置时长的参考。
        """
        if self.timing_enabled or elapsed <= 0 or elapsed > 5.0:
            return
        key = f"{action.get('type')}:{action.get('variant') or ''}"
        samples = self.timing_samples.setdefault(key, [])
        samples.append(elapsed)
        if len(samples) > 200:
            samples.pop(0)

    def _commit_current(self, now=None):
        """
        确认当前这一步已经打出，并推进指针。

        这是"一步动作完成"的唯一入口：正常推进、缓冲兑现、
        并行提前完成之后的指针前移，都走这里。
        """
        if now is None:
            now = self._clock()

        current_script = self.get_current_script()
        if not current_script or self.step_index >= len(current_script):
            return

        action = current_script[self.step_index]
        # 这一步由谁打？切人动作算"切过去的那个角色"的动画更合理。
        actor_idx = action.get("next_char") if action.get("type") == "intro" else self.current_char_idx
        actor = self.team.get(actor_idx) if actor_idx else None
        occupy = self._duration_of(action, actor)

        # 1. 记账（存的是"还没变之前"的状态）
        self._push_history()

        # 2. 学一条时长样本（只在闸门关闭时才有参考价值）
        if self._step_started_at > 0:
            self._record_timing_sample(action, now - self._step_started_at)

        # 3. 应用本步的副作用：切人动作要更新在场角色
        if action.get("type") == "intro":
            next_char = action.get("next_char")
            if next_char:
                self.current_char_idx = next_char

        # 4. 指针前进，并跳过已经被并行提前完成、又轮到位置的步
        self._advance_pointer()
        self._shift_ahead()

        guard = 0
        while 0 in self._ahead_done and guard < self.PARALLEL_LOOKAHEAD + 2:
            guard += 1
            self._ahead_done.discard(0)
            self._advance_pointer()
            self._shift_ahead()

        # 5. 时间轴：只有"连续按同一颗键"才需要占位等待
        #
        #    鸣潮的新动作优先级很高：普攻没播完按技能会直接出技能，闪避能取消一切。
        #    所以换键一律不等，闸门只用来压住同一颗键的连点
        #    （否则狂点普攻会把提示推到好几步开外）。
        self._seq += 1
        self._step_started_at = now
        self._gate_until = (now + occupy) if self._needs_gate(action) else now

        # 6. 针对"当前步"的预输入已经兑现，其余作废（键位对不上了）
        if self._buffer:
            self._buffer = [i for i in self._buffer if i.offset != 0]

    def advance(self, now=None):
        """外部直接推进一格（压测工具、调试用）。"""
        self._commit_current(now)

    def rollback(self):
        """
        回退一步（整段状态复原）。

        :return: True 表示回退成功；False 表示已经退到最开头
        """
        if not self.history_stack:
            log.warning("已经回退到头了，无法再回退")
            return False

        # 按压状态必须一起清掉，否则玩家"按住攻击键→回退→松手"会误推进
        self._down_seq.clear()
        self._down_at.clear()
        self._buffer.clear()
        self.last_press_reject = None

        snapshot = self.history_stack.pop()

        self.step_index = snapshot.step_index
        self.is_in_opener = snapshot.is_in_opener
        self.current_char_idx = snapshot.char_idx
        self._ahead_done = set(snapshot.ahead_done)
        self._gate_until = snapshot.gate_until
        self._step_started_at = snapshot.step_started

        # 回退后旧缓冲里的输入已经对不上新位置，直接丢弃
        self._seq += 1

        log.info(f"回退成功：回到角色 {self.team.get(self.current_char_idx)}，步骤 {self.step_index}")
        return True

    def reset(self):
        """回到剧本开头（下次按启动键时调用）。"""
        self.step_index = 0
        self.is_in_opener = True if self.opener else False
        self._down_seq.clear()
        self._down_at.clear()
        self._buffer.clear()
        self._ahead_done.clear()
        self._gate_until = 0.0
        self._step_started_at = 0.0
        self._seq += 1
        self.last_press_reject = None
        self.history_stack.clear()

    # ============================================================ 时长观测汇总

    def timing_summary(self):
        """
        把收集到的时长样本汇总成"建议配置值"，用于调 timing.durations_ms。

        :return: {动作种类: 建议毫秒数}
        """
        summary = {}
        for key, samples in self.timing_samples.items():
            if not samples:
                continue
            ordered = sorted(samples)
            # 取 30% 分位：玩家的自然节奏里偏快的那部分，更接近"动作一结束就按"
            pick = ordered[min(len(ordered) - 1, int(len(ordered) * 0.3))]
            summary[key] = round(pick * 1000)
        return summary
