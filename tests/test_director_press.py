"""
连招导演的行为测试：手势判定 + 时间轴 + 输入缓冲 + 并行插入。

三组关注点
---------
1. 手势：重击（长按）和普攻（轻按）必须能被时长区分开。
   v1.0 的 bug 是"期望重击时，轻点一下攻击键也算数"。
2. 时间轴：动作没播完之前的输入要么进缓冲、要么丢弃，
   不能在"游戏里还没发生"的时候就把提示推到下一步。
3. 并行：蓄力（长按）过程中允许提前完成后面允许并行的步（如声骸）。

测试全程用假时钟驱动，不真的 sleep；AssetManager 用空壳替代，
所以不依赖 assets 目录，跑得很快。
"""

import glob
import json
import os
import sys
import unittest

# 测试可能从任意 cwd 运行：就地向上找项目根并加入 import 路径，复用统一根查找
_root = os.path.abspath(__file__)
while True:
    _root = os.path.dirname(_root)
    if os.path.exists(os.path.join(_root, "main.py")) or _root == os.path.dirname(_root):
        break
if _root not in sys.path:
    sys.path.insert(0, _root)

from core.director import (MODE_ANY, MODE_HOLD, MODE_TAP, Director,
                                  classify_press, is_long_press, is_tap,
                                  press_matches)


class FakeClock:
    """可控时钟：只在自己 advance() 时前进，测试不用真的等。"""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeAssetManager:
    """Director 只需要图标路径，测试里全部返回 None。"""

    def get_icon_path(self, *args, **kwargs):
        return None

    def get_button_path(self, *args, **kwargs):
        return None


# 一套覆盖各类手势的剧本
SCRIPT = [
    {"type": "basic", "desc": "普攻"},
    {"type": "heavy", "desc": "重击", "variant": "heavy"},
    {"type": "skill", "desc": "长按技能", "hold": True},
    {"type": "dodge", "desc": "闪避"},
]


class TestPureFunctions(unittest.TestCase):
    """纯函数层：is_long_press / is_tap / press_matches。"""

    def test_threshold_boundary(self):
        print("\nRunning: test_threshold_boundary")
        self.assertTrue(is_long_press(0.5, 0.5), "正好等于阈值算长按")
        self.assertFalse(is_long_press(0.499, 0.5))
        self.assertTrue(is_tap(0.499, 0.5))
        self.assertFalse(is_tap(0.5, 0.5))
        self.assertEqual(classify_press(0.1, 0.5), MODE_TAP)
        self.assertEqual(classify_press(0.9, 0.5), MODE_HOLD)

    def test_press_matches_modes(self):
        print("Running: test_press_matches_modes")
        # 长按模式：只认够久的
        self.assertFalse(press_matches(0.1, MODE_HOLD, 0.5))
        self.assertTrue(press_matches(0.6, MODE_HOLD, 0.5))
        # 轻按模式 + 严格：两头都要卡
        self.assertTrue(press_matches(0.1, MODE_TAP, 0.5, strict_tap=True))
        self.assertFalse(press_matches(0.9, MODE_TAP, 0.5, strict_tap=True))
        # 轻按模式 + 宽松：只看键名
        self.assertTrue(press_matches(0.9, MODE_TAP, 0.5, strict_tap=False))
        # any：不看时长
        self.assertTrue(press_matches(3.0, MODE_ANY, 0.5))


class TestDirectorPress(unittest.TestCase):
    """核心：重击与普攻必须能被时长区分开。"""

    def _make_director(self, script=None, strict=True, hold_threshold=0.5, timing=False):
        script = script or [dict(a) for a in SCRIPT]
        self.clock = FakeClock()

        director = Director(
            team_config={1: "Aemaeth"},
            opener_script=script,
            loop_script=script,
            start_char_index=1,
            asset_mgr=FakeAssetManager(),
            hold_threshold=hold_threshold,
            strict_tap=strict,
            clock=self.clock,
        )
        # 默认关掉时间轴：这组测试只关心"手势裁决"，
        # 闸门会把连续输入挡住，反而干扰断言。时间轴另有一组专门测试。
        director.timing_enabled = timing
        return director

    def _press(self, director, key):
        return director.input_received(key, True)

    def _release(self, director, key, seconds):
        self.clock.advance(seconds)
        return director.input_received(key, False)

    # ---------------------------------------------------- 重击 / 普攻

    def test_heavy_rejects_short_tap(self):
        """老 bug：期望重击，轻点攻击键不应该推进。"""
        print("Running: test_heavy_rejects_short_tap")
        d = self._make_director()
        d.step_index = 1  # 指向 heavy

        self._press(d, "basic")
        advanced = self._release(d, "basic", 0.08)

        self.assertFalse(advanced, "轻按不能算重击")
        self.assertEqual(d.step_index, 1, "指针不应该动")
        self.assertEqual(d.last_press_reject, MODE_HOLD)

    def test_heavy_accepts_long_press(self):
        print("Running: test_heavy_accepts_long_press")
        d = self._make_director()
        d.step_index = 1

        self._press(d, "basic")
        advanced = self._release(d, "basic", 0.65)

        self.assertTrue(advanced, "长按应该算重击")
        self.assertEqual(d.step_index, 2)

    def test_basic_accepts_short_tap(self):
        print("Running: test_basic_accepts_short_tap")
        d = self._make_director()

        self._press(d, "basic")
        advanced = self._release(d, "basic", 0.08)

        self.assertTrue(advanced, "轻点应该算普攻")
        self.assertEqual(d.step_index, 1)

    def test_basic_rejects_long_press_in_strict_mode(self):
        print("Running: test_basic_rejects_long_press_in_strict_mode")
        d = self._make_director(strict=True)

        self._press(d, "basic")
        advanced = self._release(d, "basic", 0.8)

        self.assertFalse(advanced, "严格模式下按住太久就不是普攻了")
        self.assertEqual(d.last_press_reject, MODE_TAP)

    def test_basic_allows_long_press_when_not_strict(self):
        print("Running: test_basic_allows_long_press_when_not_strict")
        d = self._make_director(strict=False)

        self._press(d, "basic")
        advanced = self._release(d, "basic", 0.8)

        self.assertTrue(advanced, "非严格模式下不卡轻按上限")

    # ---------------------------------------------------- 特殊技能长按

    def test_skill_hold_flag(self):
        print("Running: test_skill_hold_flag")
        d = self._make_director()
        d.step_index = 2  # skill, hold=True

        self._press(d, "skill")
        self.assertFalse(self._release(d, "skill", 0.1), "hold=True 的技能轻按不算")

        self._press(d, "skill")
        self.assertTrue(self._release(d, "skill", 0.6), "按够 0.5s 才算")

    def test_custom_hold_time(self):
        print("Running: test_custom_hold_time")
        script = [{"type": "skill", "desc": "长按充能", "hold_time": 1.2}]
        d = self._make_director(script=script)

        self._press(d, "skill")
        self.assertFalse(self._release(d, "skill", 0.8), "没到自己声明的 1.2s")

        self._press(d, "skill")
        self.assertTrue(self._release(d, "skill", 1.3), "超过 1.2s 才算")

    def test_hold_seconds_shorthand(self):
        """hold 直接写数字 <=> hold=True + 该阈值。"""
        print("Running: test_hold_seconds_shorthand")
        script = [{"type": "echo", "desc": "声骸", "hold": 0.9}]
        d = self._make_director(script=script)

        mode, threshold = d.resolve_press_mode(script[0])
        self.assertEqual(mode, MODE_HOLD)
        self.assertAlmostEqual(threshold, 0.9)

        self._press(d, "echo")
        self.assertFalse(self._release(d, "echo", 0.7))
        self._press(d, "echo")
        self.assertTrue(self._release(d, "echo", 1.0))

    # ---------------------------------------------------- 瞬时动作

    def test_instant_action_advances_on_press(self):
        print("Running: test_instant_action_advances_on_press")
        script = [{"type": "dodge", "desc": "闪避"}, {"type": "basic", "desc": "普攻"}]
        d = self._make_director(script=script)

        self.assertTrue(self._press(d, "dodge"), "闪避按下就该推进")
        self.assertEqual(d.step_index, 1)

        self.assertFalse(self._release(d, "dodge", 0.5), "松手不能重复推进")
        self.assertEqual(d.step_index, 1)

    def test_no_double_advance_on_repeated_instant(self):
        """连续两步都是闪避时，松手不能把下一步也吃掉。"""
        print("Running: test_no_double_advance_on_repeated_instant")
        script = [{"type": "dodge", "desc": "闪避"}, {"type": "dodge", "desc": "闪避"}]
        d = self._make_director(script=script)

        self._press(d, "dodge")
        self.assertEqual(d.step_index, 1)
        self._release(d, "dodge", 0.3)
        self.assertEqual(d.step_index, 1, "松手不应该再推进一格")

    # ---------------------------------------------------- 状态安全

    def test_rollback_clears_press_state(self):
        print("Running: test_rollback_clears_press_state")
        d = self._make_director()
        d.step_index = 1

        # 先正常推进一步，攒出历史
        self._press(d, "basic")
        self._release(d, "basic", 0.6)
        self.assertEqual(d.step_index, 2)

        # 按住不放 -> 回退 -> 松手，不能误推进
        self._press(d, "basic")
        self.assertTrue(d.rollback())
        self.assertFalse(self._release(d, "basic", 0.05))
        self.assertEqual(d.step_index, 1)

    def test_wrong_key_is_silent(self):
        """按错键不闪红框（只有手势不对才提示），也不推进。"""
        print("Running: test_wrong_key_is_silent")
        d = self._make_director()

        d.input_received("ult", True)
        self.assertFalse(d.input_received("ult", False))
        self.assertIsNone(d.last_press_reject)
        self.assertEqual(d.step_index, 0)

    def test_resolve_press_mode(self):
        print("Running: test_resolve_press_mode")
        d = self._make_director()

        cases = [
            ({"type": "basic"}, MODE_TAP),
            ({"type": "heavy"}, MODE_HOLD),
            ({"type": "skill"}, MODE_ANY),
            ({"type": "skill", "hold": True}, MODE_HOLD),
            ({"type": "skill", "hold": False}, MODE_TAP),
            ({"type": "ult"}, MODE_ANY),
        ]
        for action, expected in cases:
            mode, _ = d.resolve_press_mode(action)
            self.assertEqual(mode, expected, f"{action} 应解析为 {expected}")

    def test_visual_data_carries_press_mode(self):
        """悬浮窗要靠 press_mode 显示"长按"角标。"""
        print("Running: test_visual_data_carries_press_mode")
        d = self._make_director()
        d.step_index = 1

        data = d.get_visual_data(preview_count=1)
        self.assertEqual(data[1]["press_mode"], MODE_HOLD, "当前格是重击，应该标长按")


class TestTimelineAndBuffer(unittest.TestCase):
    """
    时间轴 / 预输入 / 连按 / 并行。

    这组测试对应 v1.2 要解决的三类真实错位：
        - 连按跑飞（点 5 下推进 5 格）
        - 预输入空转（按太早，游戏没出招，程序却推进了）
        - 双键并行（蓄力中放声骸）
    """

    # 闸门时长固定成好算的值，避免和 config 打架
    DURATIONS = {"basic": 400, "heavy": 700, "skill": 400, "echo": 400, "dodge": 320,
                 "ult": 1000, "jump": 280, "intro": 500, "execution": 600}

    def _make_director(self, script):
        clock = FakeClock()
        d = Director(
            team_config={1: "Aemaech"},
            opener_script=script,
            loop_script=script,
            start_char_index=1,
            asset_mgr=FakeAssetManager(),
            hold_threshold=0.5,
            strict_tap=False,
            clock=clock,
        )
        # 打开时间轴，并用固定时长，让断言可算
        d.timing_enabled = True
        d.parallel_enabled = True
        d.durations_ms = dict(self.DURATIONS)
        d.buffer_window = 0.3
        return d, clock

    def _tap(self, d, clock, key, hold=0.05):
        """按一下再松开，返回松手时的推进结果。"""
        d.input_received(key, True)
        clock.advance(hold)
        return d.input_received(key, False)

    # ---------------------------------------------------- 预输入

    def test_preinput_fires_when_gate_opens(self):
        """同一颗键连按：动作没播完时再按，先进缓冲，闸门一开立刻兑现。"""
        print("\nRunning: test_preinput_fires_when_gate_opens")
        script = [{"type": "basic", "desc": "普攻1"},
                  {"type": "basic", "desc": "普攻2"},
                  {"type": "skill", "desc": "技能"}]
        d, clock = self._make_director(script)

        self.assertTrue(self._tap(d, clock, "basic"), "第一下普攻应该推进")
        self.assertEqual(d.step_index, 1)
        gate = d._gate_until
        self.assertAlmostEqual(gate, 0.05 + 0.4, places=3,
                               msg="下一颗键还是攻击键，闸门应关到动作结束")

        # 玩家在动作快结束的时候又点了一下攻击键（预输入连段）
        clock.advance(0.3)
        d.input_received("basic", True)
        clock.advance(0.05)
        self.assertFalse(d.input_received("basic", False), "闸门没开，不应该推进")
        self.assertEqual(d.step_index, 1)
        self.assertEqual(len(d._buffer), 1, "预输入应该被暂存")

        # 闸门打开的那一瞬间，心跳把缓冲兑现
        self.assertTrue(d.tick(now=gate + 0.02), "闸门开了应该兑现预输入")
        self.assertEqual(d.step_index, 2)

    def test_stale_preinput_is_dropped(self):
        """按得太早（超出缓冲寿命）就当没按过——这就是"空转"的解药。"""
        print("Running: test_stale_preinput_is_dropped")
        script = [{"type": "basic", "desc": "普攻1"},
                  {"type": "basic", "desc": "普攻2"},
                  {"type": "skill", "desc": "技能"}]
        d, clock = self._make_director(script)

        self._tap(d, clock, "basic")

        d.input_received("basic", True)
        clock.advance(0.05)
        d.input_received("basic", False)

        # 拖到很久以后才检查：这条预输入早就过期了
        self.assertFalse(d.tick(now=2.0), "过期的预输入不能推进")
        self.assertEqual(d.step_index, 1, "指针必须留在原地等玩家重按")
        self.assertEqual(len(d._buffer), 0, "过期项应被清掉")

    # ---------------------------------------------------- 换键不受闸门限制

    def test_different_key_is_not_gated(self):
        """
        普攻没播完就按技能，技能会打断普攻直接出来 —— 程序也不该拦。
        这是 v1.3 修正的核心：闸门只压同一颗键。
        """
        print("Running: test_different_key_is_not_gated")
        script = [{"type": "basic", "desc": "普攻"},
                  {"type": "skill", "desc": "技能"},
                  {"type": "basic", "desc": "普攻2"}]
        d, clock = self._make_director(script)

        self.assertTrue(self._tap(d, clock, "basic"))
        self.assertEqual(d.step_index, 1)
        self.assertAlmostEqual(d._gate_until, clock.now, places=3,
                               msg="下一颗键不同，不该关闸")

        # 动作才过了 50ms 就按技能，也应立刻推进
        clock.advance(0.05)
        d.input_received("skill", True)
        clock.advance(0.05)
        self.assertTrue(d.input_received("skill", False), "换键应该立刻推进，不进缓冲")
        self.assertEqual(d.step_index, 2)
        self.assertEqual(len(d._buffer), 0, "换键不该留下缓冲项")

    def test_same_key_keeps_gate_closed(self):
        """a -> a 这种连段才关闸；a -> z 共用攻击键，同样算同键。"""
        print("Running: test_same_key_keeps_gate_closed")
        script = [{"type": "basic", "desc": "普攻"},
                  {"type": "heavy", "desc": "重击"},
                  {"type": "basic", "desc": "普攻2"}]
        d, clock = self._make_director(script)

        self._tap(d, clock, "basic")
        self.assertGreater(d._gate_until, clock.now,
                           "普攻接重击用的是同一颗攻击键，应该关闸")

    def test_uncancellable_blocks_other_keys(self):
        """显式声明不可打断的步（如长动画大招），换键也要等。"""
        print("Running: test_uncancellable_blocks_other_keys")
        script = [{"type": "ult", "desc": "解放", "uncancellable": True},
                  {"type": "skill", "desc": "技能"}]
        d, clock = self._make_director(script)

        d.input_received("ult", True)
        clock.advance(0.1)
        self.assertTrue(d.input_received("ult", False))
        self.assertGreater(d._gate_until, clock.now, "不可打断的动作应关闸")

        d.input_received("skill", True)
        clock.advance(0.05)
        self.assertFalse(d.input_received("skill", False), "闸门关着，先不推进")

    # ---------------------------------------------------- 连按

    def test_mashing_counts_as_one(self):
        """连按 5 下只有 1 次生效，不会把提示推到 5 步开外。"""
        print("Running: test_mashing_counts_as_one")
        script = [{"type": "basic", "desc": "普攻"}] * 4
        d, clock = self._make_director(script)

        self.assertTrue(self._tap(d, clock, "basic", hold=0.02))
        self.assertEqual(d.step_index, 1)

        # 在动画期间狂按（每次间隔 40ms，全部落在闸门关闭区间内）
        for _ in range(5):
            d.input_received("basic", True)
            clock.advance(0.02)
            d.input_received("basic", False)
            clock.advance(0.02)

        self.assertEqual(len(d._buffer), 1, "重复输入应该在缓冲里合并成一条")
        self.assertEqual(d.step_index, 1, "闸门没开之前一步都不能推进")

        # 走到闸门打开的时刻
        clock.advance(d._gate_until - clock.now + 0.01)
        self.assertTrue(d.tick(), "闸门开了应该兑现")
        self.assertEqual(d.step_index, 2, "只推进一格，不是五格")

        # 缓冲已清空，紧接着的 tick 不应该再推进
        self.assertFalse(d.tick())
        self.assertEqual(d.step_index, 2)

    # ---------------------------------------------------- 并行插入

    def test_parallel_echo_during_charge(self):
        """蓄力重击的过程中按声骸：声骸被提前完成，主指针等松手才动。"""
        print("Running: test_parallel_echo_during_charge")
        script = [
            {"type": "heavy", "desc": "蓄力重击", "variant": "heavy"},
            {"type": "echo", "desc": "声骸", "parallel": True},
            {"type": "skill", "desc": "技能"},
        ]
        d, clock = self._make_director(script)

        # 按住攻击键开始蓄力
        self.assertFalse(d.input_received("basic", True), "重击要等松手才算")
        self.assertEqual(d.step_index, 0)

        # 蓄力中放声骸
        clock.advance(0.3)
        d.input_received("echo", True)
        clock.advance(0.05)
        self.assertTrue(d.input_received("echo", False), "蓄力中应该允许插入声骸")

        self.assertEqual(d.step_index, 0, "主指针不能动，重击还在进行")
        self.assertEqual(d._ahead_done, {1}, "声骸应被标记为已提前完成")

        # 松手完成重击 -> 跳过已完成的声骸，直接指向技能
        clock.advance(0.5)
        self.assertTrue(d.input_received("basic", False))
        self.assertEqual(d.step_index, 2, "应跳过已完成的声骸那一步")

    def test_parallel_requires_holding(self):
        """没在长按状态下，后面的声骸不能凭空被提前完成。"""
        print("Running: test_parallel_requires_holding")
        script = [
            {"type": "basic", "desc": "普攻"},
            {"type": "echo", "desc": "声骸"},
        ]
        d, clock = self._make_director(script)

        d.input_received("echo", True)
        clock.advance(0.05)
        self.assertFalse(d.input_received("echo", False))
        self.assertEqual(d._ahead_done, set())

    def test_parallel_can_be_disabled(self):
        print("Running: test_parallel_can_be_disabled")
        script = [
            {"type": "heavy", "desc": "蓄力重击", "variant": "heavy"},
            {"type": "echo", "desc": "声骸", "parallel": True},
        ]
        d, clock = self._make_director(script)
        d.parallel_enabled = False

        d.input_received("basic", True)
        clock.advance(0.3)
        d.input_received("echo", True)
        clock.advance(0.05)
        self.assertFalse(d.input_received("echo", False), "关掉并行后不该吃这个键")

    def test_visual_data_skips_completed_parallel_step(self):
        """被提前完成的步不该继续出现在预览里，后面的步要递补上来。"""
        print("Running: test_visual_data_skips_completed_parallel_step")
        script = [
            {"type": "heavy", "desc": "蓄力重击", "variant": "heavy"},
            {"type": "echo", "desc": "声骸", "parallel": True},
            {"type": "skill", "desc": "技能"},
        ]
        d, clock = self._make_director(script)

        d.input_received("basic", True)
        clock.advance(0.3)
        d.input_received("echo", True)
        clock.advance(0.05)
        d.input_received("echo", False)

        data = d.get_visual_data(preview_count=2)
        self.assertEqual(data[1]["desc"], "蓄力重击", "当前格仍是重击")
        self.assertEqual(data[2]["desc"], "技能", "声骸已提前完成，预览应跳到技能")


class TestPreviewAcrossBoundary(unittest.TestCase):
    """
    预览必须按**真实播放顺序**走，跨过「启动轴 -> 循环轴」的边界。

    这是修过的一个真 bug：启动轴快结束时，后面两格本应显示循环轴的内容，
    却因为对当前剧本取模而绕回了启动轴开头（一片普攻），按一下才瞬间变对。
    """

    OPENER = [
        {"type": "basic", "desc": "O0"},
        {"type": "basic", "desc": "O1"},
    ]
    LOOP = [
        {"type": "intro", "desc": "L0", "next_char": 2},
        {"type": "skill", "desc": "L1"},
        {"type": "ult", "desc": "L2"},
    ]

    def _make(self):
        clock = FakeClock()
        return Director(
            team_config={1: "A", 2: "B"},
            opener_script=[dict(a) for a in self.OPENER],
            loop_script=[dict(a) for a in self.LOOP],
            start_char_index=1,
            asset_mgr=FakeAssetManager(),
            clock=clock,
        )

    def test_last_opener_step_previews_loop(self):
        print("\nRunning: test_last_opener_step_previews_loop")
        d = self._make()
        d.step_index = len(self.OPENER) - 1   # 启动轴最后一步

        data = d.get_visual_data(preview_count=3)
        self.assertEqual(data[1]["desc"], "O1", "当前格应是启动轴最后一步")
        self.assertEqual(data[2]["desc"], "L0", "下一格应跨到循环轴第一步，而不是绕回启动轴开头")
        self.assertEqual(data[3]["desc"], "L1")

    def test_opener_crossing_reports_loop_character(self):
        """跨轴那一步是切人，预览应显示切过去的角色，衔接才自然。"""
        print("Running: test_opener_crossing_reports_loop_character")
        d = self._make()
        d.step_index = len(self.OPENER) - 1

        data = d.get_visual_data(preview_count=3)
        self.assertEqual(data[2]["char_name"], "B", "切人后应显示新角色")

    def test_loop_wraps_inside_loop(self):
        print("Running: test_loop_wraps_inside_loop")
        d = self._make()
        d.is_in_opener = False
        d.step_index = len(self.LOOP) - 1

        data = d.get_visual_data(preview_count=3)
        self.assertEqual(data[2]["desc"], "L0", "循环轴末尾应绕回循环轴开头")
        self.assertEqual(data[3]["desc"], "L1")


class TestParallelDetection(unittest.TestCase):
    """第二条时间轴只在剧本真的需要时才启用。"""

    def _make(self, opener):
        return Director(
            team_config={1: "A"},
            opener_script=opener,
            loop_script=opener,
            start_char_index=1,
            asset_mgr=FakeAssetManager(),
            clock=FakeClock(),
        )

    def test_plain_script_has_no_parallel(self):
        print("\nRunning: test_plain_script_has_no_parallel")
        d = self._make([{"type": "basic", "desc": "a"}, {"type": "skill", "desc": "e"}])
        self.assertFalse(d._has_parallel, "没有并行机会的剧本不该启用第二条时间轴")

    def test_plain_heavy_echo_does_not_enable(self):
        """蓄力中放声骸是角色特性，不能因为类型组合对上就全局放行。"""
        print("\nRunning: test_plain_heavy_echo_does_not_enable")
        d = self._make([{"type": "heavy", "desc": "z"}, {"type": "echo", "desc": "q"}])
        self.assertFalse(d._has_parallel, "没写 parallel 就不该启用第二条时间轴")
        self.assertFalse(d._pair_is_parallel({"type": "heavy"}, {"type": "echo"}))

    def test_config_auto_parallel_can_enable(self):
        print("Running: test_config_auto_parallel_can_enable")
        d = self._make([{"type": "heavy", "desc": "z"}, {"type": "echo", "desc": "q"}])
        # 模拟 config 里显式写了 auto_parallel
        d.auto_parallel_pairs = {("heavy", "echo")}
        self.assertTrue(d._pair_is_parallel({"type": "heavy"}, {"type": "echo"}))

    def test_explicit_flag_enables_parallel(self):
        print("Running: test_explicit_flag_enables_parallel")
        d = self._make([{"type": "skill", "desc": "e"},
                        {"type": "ult", "desc": "r", "parallel": True}])
        self.assertTrue(d._has_parallel, "显式 parallel 标记也要能启用")

    def test_parallel_hint_in_visual_data(self):
        """可并行的那一格要带上提示，悬浮窗才会标成"可同时"。"""
        print("Running: test_parallel_hint_in_visual_data")
        d = self._make([{"type": "heavy", "desc": "z"},
                        {"type": "echo", "desc": "q", "parallel": True},
                        {"type": "skill", "desc": "e"}])

        data = d.get_visual_data(preview_count=3)
        self.assertTrue(data[1]["is_current"])
        self.assertTrue(data[2]["parallel_hint"], "重击之后的声骸应标可并行")
        self.assertFalse(data[3]["parallel_hint"], "更后面的步不该带提示")


class TestParallelSlot(unittest.TestCase):
    """并行轨小窗的数据源：什么时候该显示、显示哪一步。"""

    def _make(self, echo_parallel=True):
        echo = {"type": "echo", "desc": "声骸·蓄力中"}
        if echo_parallel:
            echo["parallel"] = True
        return Director(
            team_config={1: "A"},
            opener_script=[
                {"type": "heavy", "desc": "蓄力重击", "variant": "heavy"},
                echo,
                {"type": "skill", "desc": "技能"},
            ],
            loop_script=[{"type": "basic", "desc": "兜底"}],
            start_char_index=1,
            asset_mgr=FakeAssetManager(),
            clock=FakeClock(),
        )

    def test_shows_parallel_target(self):
        print("\nRunning: test_shows_parallel_target")
        slot = self._make().get_parallel_slot()
        self.assertIsNotNone(slot, "蓄力步后面有可并行的声骸，应该给出支线数据")
        self.assertEqual(slot["desc"], "声骸·蓄力中")
        self.assertTrue(slot["parallel_hint"])

    def test_hidden_when_current_not_hold(self):
        print("Running: test_hidden_when_current_not_hold")
        d = self._make()
        d.step_index = 2   # 技能，不是长按类，谈不上"同时按"
        self.assertIsNone(d.get_parallel_slot())

    def test_hidden_after_target_done(self):
        print("Running: test_hidden_after_target_done")
        d = self._make()
        d._ahead_done = {1}   # 声骸已经按掉了
        self.assertIsNone(d.get_parallel_slot(), "支线做完了就该收起小窗")

    def test_hidden_when_script_has_no_parallel(self):
        print("Running: test_hidden_when_script_has_no_parallel")
        d = self._make(echo_parallel=False)
        self.assertIsNone(d.get_parallel_slot())
        self.assertFalse(d._has_parallel)


class TestCharacterDurations(unittest.TestCase):
    """角色级时长覆盖：只填差异，不写代码。"""

    def test_override_priority(self):
        print("\nRunning: test_override_priority")
        d = Director(
            team_config={1: "A"},
            opener_script=[{"type": "basic", "desc": "a"}],
            loop_script=[{"type": "basic", "desc": "a"}],
            start_char_index=1,
            asset_mgr=FakeAssetManager(),
            clock=FakeClock(),
        )
        d.timing_enabled = True
        d.durations_ms = {"heavy": 700}
        d.character_durations = {"Lynae": {"heavy": 900}}

        # 角色覆盖
        self.assertAlmostEqual(d._duration_of({"type": "heavy"}, "Lynae"), 0.9)
        # 没覆盖的角色走全局
        self.assertAlmostEqual(d._duration_of({"type": "heavy"}, "Aemeath"), 0.7)
        # 剧本单步优先于角色覆盖
        self.assertAlmostEqual(
            d._duration_of({"type": "heavy", "duration_ms": 1200}, "Lynae"), 1.2)
        # 关掉时间轴一律 0
        d.timing_enabled = False
        self.assertAlmostEqual(d._duration_of({"type": "heavy"}, "Lynae"), 0.0)


class TestFullRoutinePlayback(unittest.TestCase):
    """
    整份真实剧本能否在**严格模式**下顺利走完。

    这条测试是防止"改判定把剧本改卡住"的护栏：
    严格模式下只要某一步的时长规则和剧本类型对不上，就会推不动，
    而这种事只有把整份剧本走一遍才会暴露。

    这里关掉时间轴（timing_enabled=False），只验证手势规则本身。
    """

    ROOT = _root

    def _play_routine(self, path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        clock = FakeClock()
        director = Director(
            team_config={int(k): v for k, v in data["team_config"].items()},
            opener_script=data["opener_script"],
            loop_script=data["loop_script"],
            start_char_index=data.get("initial_char_index", 1),
            asset_mgr=FakeAssetManager(),
            hold_threshold=0.5,
            strict_tap=True,
            clock=clock,
        )
        director.timing_enabled = False

        # 走完启动轴 + 循环轴的前 20 步，足够覆盖一次完整循环
        steps = len(data["opener_script"]) + min(20, len(data["loop_script"]))

        for i in range(steps):
            script = director.get_current_script()
            action = script[director.step_index]

            key = (f"intro_{action['next_char']}" if action["type"] == "intro"
                   else action["type"])
            mode, threshold = director.resolve_press_mode(action)

            # 按剧本要求的手势演一遍：长按的就演够时长，轻按的就演短
            if mode == MODE_HOLD:
                duration = threshold + 0.15
            elif mode == MODE_TAP:
                duration = min(0.08, threshold * 0.4)
            else:
                duration = 0.1

            pressed = director.input_received(key, True)
            clock.advance(duration)
            released = director.input_received(key, False)

            if action["type"] in Director.INSTANT_TYPES:
                self.assertTrue(pressed, f"第 {i} 步 {action} 按下没推进")
            else:
                self.assertTrue(released, f"第 {i} 步 {action} 松手没推进（手势={mode}）")

    def test_all_routines_play_through(self):
        print("\nRunning: test_all_routines_play_through")
        routine_dir = os.path.join(self.ROOT, "configs", "routines")
        paths = sorted(glob.glob(os.path.join(routine_dir, "*.json")))
        self.assertTrue(paths, "configs/routines 下没有剧本")

        for path in paths:
            with self.subTest(routine=os.path.basename(path)):
                self._play_routine(path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
