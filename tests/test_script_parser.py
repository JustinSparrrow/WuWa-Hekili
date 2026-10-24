"""
解析器与剧本体检的回归测试。

覆盖三件事：
1. **旧语法零回归** —— 现有剧本一个字都不用改
2. **新语法可用** —— 注释 / 重复 / 并行 / 不可打断 / 自定义时长
3. **错误能被发现** —— 未知字符、越界引用、坏字段都要报出来且能定位

跑法：python tests/test_script_parser.py
"""

import json
import os
import sys
import tempfile
import unittest

# 测试可能从任意 cwd 运行：就地向上找项目根并加入 import 路径，复用统一根查找
_root = os.path.abspath(__file__)
while True:
    _root = os.path.dirname(_root)
    if os.path.exists(os.path.join(_root, "main.py")) or _root == os.path.dirname(_root):
        break
if _root not in sys.path:
    sys.path.insert(0, _root)
ROOT = _root

from core.script_parser import ScriptParser, LEVEL_ERROR, LEVEL_WARNING  # noqa: E402
from tools.checks.routine_lint import lint_routine  # noqa: E402

TEAM = {
    "爱弥斯": (1, "Aemeath", ["爱"]),
    "琳奈": (2, "Lynae", ["琳"]),
    "莫宁": (3, "Mornye", ["莫"]),
}
NAMES = {1: "爱弥斯", 2: "琳奈", 3: "莫宁"}


def strip_meta(actions):
    """去掉仅供 UI 定位的 _line/_col，方便断言。"""
    return [{k: v for k, v in a.items() if not k.startswith("_")} for a in actions]


class TestLegacyCompatibility(unittest.TestCase):
    """旧语法必须逐字段一致，否则编辑器预览会和现有剧本对不上。"""

    def setUp(self):
        self.p = ScriptParser(TEAM)

    def test_basic_sequence(self):
        self.assertEqual(self.p.parse("爱aaaa"), [
            {"type": "basic", "desc": "普攻"}] * 4,
            "起手的角色名等于当前角色，不应该生成 intro")

    def test_intro_generates_next_char(self):
        acts = self.p.parse("爱aaaa莫e")
        # TEAM 的 key 是中文名，所以 desc 也用中文；真实剧本传英文名就显示英文
        self.assertEqual(acts[-2], {"type": "intro", "next_char": 3, "desc": "切-莫宁"})
        self.assertEqual(acts[-1], {"type": "skill", "desc": "技能"})

    def test_variant_and_heavy_tag(self):
        acts = self.p.parse("爱a2z")
        self.assertEqual(acts[0]["variant"], "2")
        self.assertEqual(acts[1]["variant"], "heavy", "z 永远带 heavy 标签")
        self.assertEqual(acts[1]["type"], "heavy")

    def test_forte_tag(self):
        acts = self.p.parse("爱f")
        self.assertEqual(acts[0]["variant"], "forte")

    def test_first_segment_force_general(self):
        acts = self.p.parse("爱a1")
        self.assertTrue(acts[0]["force_general"], "a1 要标记为使用通用图")
        self.assertNotIn("variant", acts[0], "a1 不带变体号")

    def test_hold_suffix(self):
        acts = self.p.parse("爱e+")
        self.assertTrue(acts[0]["hold"])
        self.assertIn("长按", acts[0]["desc"])

    def test_no_duplicate_hold_on_heavy(self):
        """z 本身就是长按语义，不该额外标 hold。"""
        acts = self.p.parse("爱z")
        self.assertNotIn("hold", acts[0])

    def test_hold_before_number_also_works(self):
        """e+3 这种顺序旧正则不支持，新解析器应当接受（容错增强）。"""
        acts = self.p.parse("爱e+3")
        self.assertTrue(acts[0]["hold"])
        self.assertEqual(acts[0]["variant"], "3")

    def test_variation_prefix(self):
        """变奏切入另一个角色。注意写当前角色不会生成动作（旧版行为一致）。"""
        acts = self.p.parse("(变奏)莫")
        self.assertEqual(acts[0]["desc"], "变奏-莫宁")

    def test_variation_to_current_char_is_noop(self):
        self.assertEqual(self.p.parse("(变奏)爱"), [])

    def test_explicit_switch_prefix(self):
        acts = self.p.parse("切莫")
        self.assertEqual(acts[0]["desc"], "切-莫宁")

    def test_chinese_jump_dodge(self):
        acts = self.p.parse("爱跳跳闪")
        self.assertEqual([a["type"] for a in acts], ["jump", "jump", "dodge"])

    def test_s_letter_shows_chinese(self):
        """旧版把 s 显示成 'S'，这是遗漏，已修为 '闪避'。"""
        acts = self.p.parse("爱s")
        self.assertEqual(acts[0]["desc"], "闪避")


class TestNewSyntax(unittest.TestCase):
    def setUp(self):
        self.p = ScriptParser(TEAM)

    def test_line_comment(self):
        acts = self.p.parse("爱aa // 起手两下\n莫e")
        self.assertEqual(len(acts), 4)  # 2 普攻 + 切人 + 技能
        self.assertEqual(acts[-1]["type"], "skill")

    def test_block_comment(self):
        acts = self.p.parse("爱a /* 中间说明 */ aa")
        self.assertEqual(len(acts), 3)

    def test_repeat_expand(self):
        acts = self.p.parse("爱a*4")
        self.assertEqual(len(acts), 4)
        self.assertTrue(all(a["type"] == "basic" for a in acts))

    def test_repeat_with_modifier(self):
        acts = self.p.parse("爱e3+*2")
        self.assertEqual(len(acts), 2)
        self.assertEqual(acts[0]["variant"], "3")
        self.assertTrue(acts[0]["hold"])

    def test_parallel_marker(self):
        acts = self.p.parse("琳z&q")
        heavy = next(a for a in acts if a["type"] == "heavy")
        echo = next(a for a in acts if a["type"] == "echo")
        self.assertNotIn("parallel", heavy, "& 应作用于后一个动作")
        self.assertTrue(echo["parallel"])

    def test_uncancellable(self):
        acts = self.p.parse("爱r!")
        self.assertTrue(acts[0]["uncancellable"])

    def test_duration(self):
        acts = self.p.parse("爱a{620}")
        self.assertEqual(acts[0]["duration_ms"], 620)

    def test_combined_modifiers(self):
        acts = self.p.parse("爱a3+!{700}")
        a = acts[0]
        self.assertEqual(a["variant"], "3")
        self.assertTrue(a["hold"])
        self.assertTrue(a["uncancellable"])
        self.assertEqual(a["duration_ms"], 700)


class TestDiagnostics(unittest.TestCase):
    """容错的核心：错误必须能被看见、能定位。"""

    def setUp(self):
        self.p = ScriptParser(TEAM)

    def test_unknown_char_reports_position(self):
        acts, diags = self.p.parse_with_diagnostics("爱aaax莫")
        errors = [d for d in diags if d.level == LEVEL_ERROR]
        self.assertEqual(len(errors), 1, "x 应该报一条错误")
        self.assertEqual(errors[0].code, "E001")
        self.assertEqual((errors[0].line, errors[0].col), (1, 5),
                         "位置应指向第 5 个字符 x")
        self.assertEqual(len(acts), 4, "报错不能中断解析，后面的内容照常处理")

    def test_error_does_not_stop_later_tokens(self):
        _, diags = self.p.parse_with_diagnostics("爱a#a$z")
        codes = [d.code for d in diags if d.level == LEVEL_ERROR]
        self.assertGreaterEqual(len(codes), 2, "两个坏字符都应各自报一条")

    def test_unclosed_block_comment(self):
        _, diags = self.p.parse_with_diagnostics("爱aa /* 忘了关")
        self.assertTrue(any(d.code == "E003" for d in diags))

    def test_bad_bracket_content(self):
        _, diags = self.p.parse_with_diagnostics("爱(变秦)aaa")
        self.assertTrue(any(d.code == "E004" for d in diags),
                        "把「变奏」打错成「变秦」必须报错")

    def test_leading_char_is_silent(self):
        """起手写当前角色是正常习惯，不该报警。"""
        _, diags = self.p.parse_with_diagnostics("爱aaaa")
        self.assertFalse([d for d in diags if d.level == LEVEL_WARNING])

    def test_mid_switch_to_same_char_warns(self):
        """打到一半又写当前角色，可能是笔误，要提示。"""
        _, diags = self.p.parse_with_diagnostics("爱aaaa爱aa")
        self.assertTrue(any(d.code == "W001" for d in diags))

    def test_snippet_contains_caret(self):
        _, diags = self.p.parse_with_diagnostics("爱aaax")
        err = next(d for d in diags if d.code == "E001")
        self.assertIn("^", err.snippet, "报错应带尖号指示位置")


class TestRoundTrip(unittest.TestCase):
    """解析 -> 还原字符串 -> 再解析，结果必须一致。"""

    def setUp(self):
        self.p = ScriptParser(TEAM)

    def _roundtrip(self, text):
        acts1, _ = self.p.parse_with_diagnostics(text)
        rendered = self.p.render(acts1, NAMES)
        acts2, _ = self.p.parse_with_diagnostics(rendered)
        self.assertEqual(strip_meta(acts1), strip_meta(acts2),
                         f"往返不一致\n原文: {text}\n还原: {rendered}")
        return rendered

    def test_roundtrip_simple(self):
        self._roundtrip("爱aaaa莫e")

    def test_roundtrip_all_modifiers(self):
        rendered = self._roundtrip("爱a3+!{700}*2莫e")
        self.assertIn("+", rendered)
        self.assertIn("!", rendered)
        self.assertIn("{700}", rendered)

    def test_roundtrip_parallel(self):
        rendered = self._roundtrip("琳z&q")
        self.assertIn("&", rendered)


class TestRealRoutine(unittest.TestCase):
    """用仓库里真实的剧本做回归，防止改解析器把现有轴改坏。"""

    def setUp(self):
        path = os.path.join(ROOT, "configs", "routines", "爱琳莫轮椅轴.json")
        if not os.path.exists(path):
            self.skipTest("没有可用的真实剧本")
        self.data = json.load(open(path, encoding="utf-8"))
        team = {}
        aliases = self.data.get("team_aliases") or {}
        for k, v in self.data["team_config"].items():
            al = [x.strip() for x in (aliases.get(k) or "").replace("，", ",").split(",") if x.strip()]
            team[v] = (int(k), v, al)
        self.p = ScriptParser(team)

    def test_step_count_matches_saved_json(self):
        for key in ("opener", "loop"):
            text = self.data.get("original_" + key)
            if not text:
                continue
            acts = self.p.parse(text, self.data.get("initial_char_index", 1))
            saved = self.data[key + "_script"]
            self.assertEqual(len(acts), len(saved),
                             f"{key} 轴步数变化，解析器可能有回归")

    def test_roundtrip_whole_routine(self):
        for key in ("opener", "loop"):
            text = self.data.get("original_" + key)
            if not text:
                continue
            a1, _ = self.p.parse_with_diagnostics(text, self.data.get("initial_char_index", 1))
            rendered = self.p.render(a1, NAMES)
            a2, _ = self.p.parse_with_diagnostics(rendered, self.data.get("initial_char_index", 1))
            self.assertEqual(strip_meta(a1), strip_meta(a2), f"{key} 往返不一致")


class TestRoutineLint(unittest.TestCase):
    """体检器要能抓住"以前只会表现为图不对"的那些问题。"""

    @classmethod
    def setUpClass(cls):
        # 素材审计需要真实的素材目录；没有就退化成纯 JSON 检查
        cls.asset_mgr = None
        assets = os.path.join(ROOT, "assets", "characters")
        if os.path.isdir(assets):
            from utils.asset_manager import AssetManager
            cls.asset_mgr = AssetManager(assets)
            cls.asset_mgr.clear_cache()

    def _write(self, payload):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        self.addCleanup(os.unlink, path)
        return path

    def _lint(self, payload):
        return lint_routine(self._write(payload), self.asset_mgr)

    def _base(self, **over):
        data = {
            "team_config": {"1": "Aemeath", "2": "Lynae", "3": "Mornye"},
            "opener_script": [{"type": "basic", "desc": "普攻"}],
            "loop_script": [{"type": "basic", "desc": "普攻"}],
            "initial_char_index": 1,
        }
        data.update(over)
        return data

    def test_clean_routine_passes(self):
        report = self._lint(self._base())
        self.assertTrue(report.ok(), f"干净剧本不该报错: {[i.render() for i in report.errors]}")

    def test_missing_required_key(self):
        data = self._base()
        del data["opener_script"]
        data.pop("loop_script", None)
        report = self._lint(data)
        self.assertFalse(report.ok())

    def test_next_char_out_of_range(self):
        """这是以前最坑的一种：不崩溃，但界面显示 Unknown。"""
        report = self._lint(self._base(
            opener_script=[{"type": "intro", "next_char": 4, "desc": "切-不存在"}]))
        self.assertFalse(report.ok())
        self.assertTrue(any("next_char" in i.message for i in report.errors))

    def test_unknown_action_type(self):
        report = self._lint(self._base(
            opener_script=[{"type": "superskill", "desc": "瞎写"}]))
        self.assertFalse(report.ok())

    def test_bad_duration(self):
        report = self._lint(self._base(
            opener_script=[{"type": "basic", "desc": "普攻", "duration_ms": 0}]))
        self.assertFalse(report.ok())

    @unittest.skipIf(not os.path.isdir(os.path.join(ROOT, "assets", "characters")),
                     "没有素材目录，跳过图标存在性检查")
    def test_custom_icon_missing(self):
        report = self._lint(self._base(
            opener_script=[{"type": "basic", "desc": "普攻", "custom_icon": "不存在.png"}]))
        self.assertFalse(report.ok())
        self.assertTrue(any("custom_icon" in i.message for i in report.errors))

    def test_team_key_not_numeric(self):
        report = self._lint(self._base(team_config={"一": "Aemeath"}))
        self.assertFalse(report.ok())

    def test_initial_char_not_in_team(self):
        report = self._lint(self._base(initial_char_index=9))
        self.assertFalse(report.ok())

    def test_report_has_location(self):
        """报错必须说清是第几步，否则等于没说。"""
        report = self._lint(self._base(
            opener_script=[{"type": "basic", "desc": "a"},
                           {"type": "nope", "desc": "b"}]))
        err = report.errors[0]
        self.assertIn("第 1 步", err.where)


if __name__ == "__main__":
    unittest.main(verbosity=2)
