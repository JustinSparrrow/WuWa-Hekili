"""
剧本体检工具：在**加载之前**把问题找出来，并用人的话说明白。

为什么需要它
------------
程序里所有的错误以前都是静默的：

  - 剧本缺字段 -> `data["team_config"]` 直接抛 KeyError，弹一个英文异常框
  - `next_char` 写了队伍里没有的槽位 -> 界面显示 "Unknown"，图标落到通用图
  - `custom_icon` 指向不存在的文件 -> 静默换一张别的图
  - 素材缺失 -> 降级到"目录里排第一张"，可能是完全不相干的动作

做轴的人改错一个字段，看到的现象往往是"图不对"或"程序卡住"，
但没有任何信息指向**哪一行**。这个工具就是补上这一环。

用法
----
    python tools/routine_lint.py configs/routines/爱琳莫轮椅轴.json
    python tools/routine_lint.py --all              # 检查全部剧本
    python tools/routine_lint.py <file> --strict    # 素材降级也算错误
    python tools/routine_lint.py --assets-only      # 只做素材覆盖率体检

退出码：0 = 无 error；1 = 有 error。可以直接接到 git hook 或打包脚本里。
"""

import argparse
import json
import os
import sys

# 独立运行：就地向上找到项目根（含 main.py）并加入 import 路径，再复用统一根查找。
# 这段 bootstrap 是独立脚本 import utils 前的必要步骤，无法消除；逻辑与
# utils.paths.project_root() 同源（while 向上找标志文件，不写死层级）。
_root = os.path.abspath(__file__)
while True:
    _root = os.path.dirname(_root)
    if os.path.exists(os.path.join(_root, "main.py")) or _root == os.path.dirname(_root):
        break
if _root not in sys.path:
    sys.path.insert(0, _root)

from utils.asset_manager import AssetManager  # noqa: E402
from utils.paths import project_root     # noqa: E402

ROOT = str(project_root())

# 剧本里允许出现的动作类型，和 Director.ACTION_TYPES / widgets 的兜底一致
ALLOWED_TYPES = {
    "basic", "heavy", "skill", "ult", "echo",
    "jump", "dodge", "execution", "intro",
}

REQUIRED_TOP_KEYS = ("team_config", "opener_script", "loop_script")
MAX_REASONABLE_MS = 8000     # 单步超过 8 秒基本可以判定是手误

# 素材来源 -> 提示级别。前三个是"正常"，后面是需要人看一眼的
SOURCE_LEVEL = {
    "custom": None,
    "exclusive:variant": None,
    "exclusive:keyword": None,
    "exclusive:first": "warning",     # 专属目录但图不对
    "heavy_fallback": "info",         # 借普攻，常见但要知道
    "general": "warning",             # 掉通用库，说明专属素材缺
    "loose:first": "warning",         # 随便一张，最可疑
    "missing": "error",
}


class Issue:
    """一条检查结论。where 是"第 N 步（启动轴）"这种人话位置。"""

    __slots__ = ("level", "where", "message")

    def __init__(self, level, where, message):
        self.level = level
        self.where = where
        self.message = message

    def render(self):
        tag = {"error": "错误", "warning": "警告", "info": "提示"}[self.level]
        loc = f" {self.where}" if self.where else ""
        return f"  [{tag}]{loc}：{self.message}"


class LintReport:
    def __init__(self, path):
        self.path = path
        self.issues = []
        self.source_stats = {}     # 来源代号 -> 次数
        self.suspicious = []       # (位置, 说明) 的素材可疑项
        self.parallel_steps = []   # 标了 parallel 的步（有意的配置，只汇总）
        self.step_count = 0
        self.team_desc = ""

    def add(self, level, where, message):
        self.issues.append(Issue(level, where, message))

    @property
    def errors(self):
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self):
        return [i for i in self.issues if i.level == "warning"]

    def ok(self):
        return not self.errors


# ====================================================================== 检查

def _iter_scripts(data):
    """产出 (轴名, 显示名, 动作数组)，跳过缺失的轴。"""
    if isinstance(data.get("opener_script"), list):
        yield "opener", "启动轴", data["opener_script"]
    if isinstance(data.get("loop_script"), list):
        yield "loop", "循环轴", data["loop_script"]


def _check_team(data, report, asset_mgr=None):
    """
    队伍配置：槽位编号、英文名、代称是否自洽。

    角色英文名必须和 `assets/characters/` 下的目录同名，否则所有图标都会退化。
    这个错误以前的表现是"图标全变成通用图"，完全看不出是名字写错了。
    """
    team = data.get("team_config")
    if not isinstance(team, dict) or not team:
        report.add("error", "", "team_config 必须是非空对象，如 {\"1\": \"Aemeath\"}")
        return {}

    normalized = {}
    for key, name in team.items():
        if not str(key).isdigit():
            report.add("error", "", f"team_config 的键 {key!r} 不是数字槽位号（应为 \"1\"/\"2\"/\"3\"）")
            continue
        if not isinstance(name, str) or not name.strip():
            report.add("error", "", f"team_config 槽位 {key} 的角色名为空")
            continue
        name = name.strip()
        normalized[int(key)] = name

        # 角色名必须对应素材目录
        if asset_mgr is not None:
            char_dir = os.path.join(asset_mgr.path, name)
            if not os.path.isdir(char_dir):
                report.add("error", "", f"槽位 {key} 的角色 {name!r} 在 "
                                        f"assets/characters/ 下没有对应目录，"
                                        f"该角色的所有图标都会退化为通用图或文字")
            elif not any(os.path.isdir(os.path.join(char_dir, s)) and
                         any(f.lower().endswith(".png") for f in os.listdir(os.path.join(char_dir, s)))
                         for s in os.listdir(char_dir) if os.path.isdir(os.path.join(char_dir, s))):
                report.add("warning", "", f"槽位 {key} 的角色 {name!r} 目录是空的，"
                                          f"没有任何图标，界面会退化为文字")

    slots = sorted(normalized)
    if slots != list(range(1, len(slots) + 1)):
        report.add("warning", "", f"槽位号不连续：{slots}。建议按 1..N 编号，否则切人方向键会错位")

    aliases = data.get("team_aliases") or {}
    for key in list(aliases.keys()):
        if not str(key).isdigit() or int(key) not in normalized:
            report.add("warning", "", f"team_aliases 里的 {key!r} 没有对应槽位")
    return normalized


def _check_action(action, where, team, current_char, report, asset_mgr, strict,
                  ignore_custom=False):
    """
    检查单个动作。返回它归属的角色 id（intro 会推进 current_char）。

    :return: (处理后的 current_char, 显示用角色 id)
    """
    if not isinstance(action, dict):
        report.add("error", where, "动作不是对象（应为 {...}）")
        return current_char, current_char

    atype = action.get("type")
    if not atype:
        report.add("error", where, "缺少 type 字段")
        return current_char, current_char
    if atype not in ALLOWED_TYPES:
        report.add("error", where,
                   f"不认识的 type={atype!r}，可用：{'/'.join(sorted(ALLOWED_TYPES))}")
        return current_char, current_char

    display_char = current_char
    if atype == "intro":
        nxt = action.get("next_char")
        if nxt is None:
            report.add("error", where, "intro 缺少 next_char（切到第几个槽位）")
        elif not isinstance(nxt, int) or nxt not in team:
            report.add("error", where,
                       f"next_char={nxt!r} 不在队伍里（只有 {sorted(team)}），"
                       f"运行时该步会显示 Unknown 并退化为通用图标")
        else:
            current_char = nxt
            display_char = nxt
    else:
        if current_char is None:
            report.add("error", where, "起始角色未知，无法确定这一步属于谁")
        elif current_char not in team:
            report.add("error", where,
                       f"当前角色槽位 {current_char} 不在队伍里（只有 {sorted(team)}）")

    # custom_icon 是否真的存在
    custom_icon = action.get("custom_icon")
    if custom_icon:
        char_name = team.get(display_char)
        if not char_name:
            report.add("warning", where, f"custom_icon 已设置，但该步角色未知，无法定位文件")
        elif asset_mgr is not None:
            hit = _custom_icon_exists(asset_mgr, char_name, atype, custom_icon)
            if not hit:
                report.add("error", where,
                           f"custom_icon={custom_icon!r} 在 {char_name} 的任何素材目录下都不存在，"
                           f"运行时会被静默换成别的图")

    # 变体号与 custom_icon 编号是否打架
    variant = action.get("variant") or ""
    custom_icon = action.get("custom_icon")
    if custom_icon and variant:
        vnum = next((p for p in variant.split("_") if p.isdigit()), None)
        cnum = _first_digit(custom_icon)
        if vnum and cnum and vnum != cnum:
            # 只在"目录里确实有更匹配的那张"时才警告，否则就是无奈之举
            better = _sibling_icon(asset_mgr, team.get(display_char), atype, custom_icon, vnum)
            if better:
                report.add("warning", where,
                           f"variant={variant!r}（第 {vnum} 段）却指定了 {custom_icon!r}，"
                           f"而同目录下有更匹配的 {better!r}，确认不是选错图")
            else:
                report.add("info", where,
                           f"variant 编号({vnum}) 与图标编号({cnum}) 不一致，"
                           f"但目录里没有第 {vnum} 张，只能这样用")

    # 并行标记只汇总，不逐条报（这是有意配置，不是错误）
    if action.get("parallel"):
        report.parallel_steps.append(where)

    # 时长
    dur = action.get("duration_ms")
    if dur is not None:
        if not isinstance(dur, (int, float)) or dur <= 0:
            report.add("error", where, f"duration_ms={dur!r} 必须为正数")
        elif dur > MAX_REASONABLE_MS:
            report.add("warning", where,
                       f"duration_ms={dur} 超过 {MAX_REASONABLE_MS}ms，确认不是把秒数当毫秒填了")

    # 素材审计
    if asset_mgr is not None and display_char in team:
        _audit_icon(action, where, team[display_char], display_char, report,
                    asset_mgr, strict, ignore_custom)

    return current_char, display_char


def _sibling_icon(asset_mgr, char_name, action_type, custom_icon, vnum):
    """
    在 custom_icon 所在目录里找"编号更匹配"的同族文件。

    例：custom_icon=normal_3.png、vnum=2，若同目录有 normal_2.png 就返回它。
    找不到返回 None（说明第 vnum 张本来就不存在，用户没得选）。
    """
    if not char_name or not custom_icon:
        return None
    base = custom_icon.rsplit("_", 1)[0] if "_" in custom_icon else custom_icon.rsplit(".", 1)[0]
    candidate = f"{base}_{vnum}.png"

    folder = asset_mgr.folder_map.get(action_type, action_type)
    dirs = [folder, "normal_attack", "resonance_skill", "resonance_liberation", "echo"]
    for sub in dict.fromkeys(dirs):
        directory = os.path.join(asset_mgr.path, char_name, sub)
        if os.path.exists(os.path.join(directory, custom_icon)) and \
                os.path.exists(os.path.join(directory, candidate)):
            return candidate
    return None


def _custom_icon_exists(asset_mgr, char_name, action_type, filename):
    """在角色的各个子目录里找一个文件名。"""
    folder = asset_mgr.folder_map.get(action_type, action_type)
    candidates = [folder, "normal_attack", "resonance_skill", "resonance_liberation", "echo"]
    for sub in dict.fromkeys(candidates):
        if os.path.exists(os.path.join(asset_mgr.path, char_name, sub, filename)):
            return True
    return False


def _first_digit(text):
    for ch in text or "":
        if ch.isdigit():
            return ch
    return None


def _audit_icon(action, where, char_name, char_id, report, asset_mgr, strict,
                ignore_custom=False):
    """
    查这一步最终会显示哪张图，来自哪一级降级。

    :param ignore_custom: 忽略剧本里的 custom_icon，模拟"如果没手选图会怎样"。
                          每步都手选了图时，降级路径根本不会触发，也就查不出
                          "这个角色其实缺素材"——这个开关就是为这种剧本准备的。
    """
    atype = action.get("type")
    custom = None if ignore_custom else action.get("custom_icon")
    info = asset_mgr.explain_icon_path(
        char_name, atype, action.get("variant"),
        action.get("force_general", False), custom)

    source = info["source"]
    report.source_stats[source] = report.source_stats.get(source, 0) + 1

    level = SOURCE_LEVEL.get(source, "info")
    if level is None:
        return
    if strict and level == "info":
        # 严格模式：连"借普攻"也算需要处理
        level = "warning"
    if level == "info":
        return  # 借图太常见，不逐条刷屏，只计入统计

    report.add(level, where, info["detail"])
    report.suspicious.append((where, info["detail"]))


def lint_routine(path, asset_mgr=None, strict=False, ignore_custom=False):
    """检查一份剧本，返回 LintReport。"""
    report = LintReport(path)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        report.add("error", "", f"文件不存在：{path}")
        return report
    except json.JSONDecodeError as e:
        report.add("error", "", f"JSON 语法错误（第 {e.lineno} 行第 {e.colno} 列）：{e.msg}")
        return report

    if not isinstance(data, dict):
        report.add("error", "", "剧本顶层必须是对象")
        return report

    for key in REQUIRED_TOP_KEYS:
        if key not in data:
            report.add("error", "", f"缺少必需字段 {key}")
    if not any(k in data for k in ("opener_script", "loop_script")):
        report.add("error", "", "opener_script 和 loop_script 至少要有一个")
        return report

    team = _check_team(data, report, asset_mgr)
    if not team:
        return report

    start = data.get("initial_char_index")
    if start is None:
        report.add("warning", "", "缺少 initial_char_index，运行时按 1 号位处理")
        start = 1
    elif start not in team:
        report.add("error", "", f"initial_char_index={start} 不在队伍里（只有 {sorted(team)}）")

    report.team_desc = "  ".join(f"{k}={v}" for k, v in sorted(team.items()))

    for _key, label, script in _iter_scripts(data):
        if not isinstance(script, list):
            report.add("error", label, "不是数组")
            continue
        if not script:
            report.add("warning", label, "是空数组，加载后这一轴没有任何提示")
            continue

        report.step_count += len(script)
        current = start
        for i, action in enumerate(script):
            where = f"第 {i} 步（{label}）"
            current, _ = _check_action(action, where, team, current, report,
                                       asset_mgr, strict, ignore_custom)

    # 启动轴末尾接循环轴的切人连续性
    if isinstance(data.get("opener_script"), list) and isinstance(data.get("loop_script"), list):
        if data["opener_script"] and data["loop_script"]:
            first = data["loop_script"][0]
            if first.get("type") == "intro":
                report.add("info", "循环轴第 0 步",
                           "循环轴以切人开始，每轮循环都会多一次切人，确认这是有意的")

    return report


# ====================================================================== 素材覆盖

def audit_assets(asset_mgr):
    """
    全局素材体检：角色目录 vs 武器映射表。

    basic/heavy 掉到通用库时，需要按 `Character_Occupation.txt` 里的武器类型
    再找一层 `_general/normal_attack/<武器>/`。没登记的角色会直接跳过这一级，
    表现为"没有图"或"拿到别人的图"，而且没有任何提示。
    """
    lines = []
    base = asset_mgr.path
    if not os.path.isdir(base):
        return [Issue("error", "", f"素材根目录不存在：{base}")]

    char_dirs = sorted(
        d for d in os.listdir(base)
        if os.path.isdir(os.path.join(base, d)) and d != "_general"
    )

    mapped = {k.lower(): v for k, v in asset_mgr.weapon_map.items()}
    missing = [d for d in char_dirs if d.lower() not in mapped]

    lines.append(Issue("info", "", f"角色目录 {len(char_dirs)} 个，"
                                   f"Character_Occupation.txt 登记了 {len(asset_mgr.weapon_map)} 个"))
    if missing:
        lines.append(Issue(
            "warning", "",
            f"{len(missing)} 个角色没有武器类型登记，basic/heavy 掉通用库时找不到对应目录："
            f"{', '.join(missing[:8])}{' …' if len(missing) > 8 else ''}"))

    # 每个角色缺哪些常用子目录
    core_subs = ["normal_attack", "resonance_skill", "resonance_liberation", "character"]
    thin = []
    for d in char_dirs:
        absent = [s for s in core_subs if not os.path.isdir(os.path.join(base, d, s))]
        if len(absent) >= 3:
            thin.append(f"{d}(缺{len(absent)})")
    if thin:
        lines.append(Issue(
            "warning", "",
            f"{len(thin)} 个角色的核心素材目录基本是空的：{', '.join(thin[:10])}"
            f"{' …' if len(thin) > 10 else ''}"))

    # 通用库的武器目录有哪些
    general_root = os.path.join(base, "_general")
    if os.path.isdir(general_root):
        weapons = sorted(os.listdir(os.path.join(general_root, "normal_attack"))) \
            if os.path.isdir(os.path.join(general_root, "normal_attack")) else []
        if weapons:
            lines.append(Issue("info", "", f"通用库武器目录：{', '.join(weapons)}"))

    return lines


# ====================================================================== 输出

def print_report(report, verbose_source=True):
    name = os.path.basename(report.path)
    print("=" * 72)
    print(f"剧本：{name}")
    if report.team_desc:
        print(f"队伍：{report.team_desc}")
    print(f"共检查 {report.step_count} 步")
    print("=" * 72)

    if not report.issues:
        print("  ✅ 没有发现问题")
    else:
        order = {"error": 0, "warning": 1, "info": 2}
        for issue in sorted(report.issues, key=lambda i: order[i.level]):
            print(issue.render())

    if verbose_source and report.source_stats:
        print("-" * 72)
        print("素材来源统计")
        for source, count in sorted(report.source_stats.items(),
                                    key=lambda kv: -kv[1]):
            print(f"  {source:20s} {count:4d} 步")
        # 全是 custom 时，降级路径根本没被触发，说明这份剧本查不出"缺素材"
        custom_n = report.source_stats.get("custom", 0)
        if custom_n and custom_n == sum(report.source_stats.values()):
            print("  ↑ 每步都手选了图标，走不到自动降级。"
                  "想查这个角色缺哪些素材，加 --ignore-custom 再跑一次")

    if report.parallel_steps:
        print("-" * 72)
        print(f"可并行标记 {len(report.parallel_steps)} 处："
              f"{'、'.join(report.parallel_steps[:6])}"
              f"{' …' if len(report.parallel_steps) > 6 else ''}")

    print("-" * 72)
    print(f"结果：{len(report.errors)} 个错误，{len(report.warnings)} 个警告")
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description="剧本体检：加载前找出问题")
    parser.add_argument("routine", nargs="?", help="剧本 JSON 路径")
    parser.add_argument("--all", action="store_true", help="检查 configs/routines 下全部剧本")
    parser.add_argument("--strict", action="store_true", help="素材降级（借图）也算警告")
    parser.add_argument("--ignore-custom", action="store_true",
                        help="忽略剧本里的 custom_icon，检查自动降级路径（用来看角色缺什么素材）")
    parser.add_argument("--assets-only", action="store_true", help="只做素材覆盖率体检")
    args = parser.parse_args()

    assets_path = os.path.join(ROOT, "assets", "characters")
    asset_mgr = None
    if os.path.isdir(assets_path):
        asset_mgr = AssetManager(assets_path)
    else:
        print(f"[警告] 素材目录不存在，跳过素材审计：{assets_path}")

    if args.assets_only:
        print("=" * 72)
        print("素材覆盖体检")
        print("=" * 72)
        for issue in audit_assets(asset_mgr):
            print(issue.render())
        return 0

    if args.all:
        routine_dir = os.path.join(ROOT, "configs", "routines")
        files = sorted(os.path.join(routine_dir, f)
                       for f in os.listdir(routine_dir) if f.endswith(".json"))
    elif args.routine:
        files = [args.routine if os.path.isabs(args.routine)
                 else os.path.abspath(args.routine)]
    else:
        parser.print_help()
        return 2

    bad = 0
    total_errors = 0
    for path in files:
        report = lint_routine(path, asset_mgr, strict=args.strict,
                              ignore_custom=args.ignore_custom)
        print_report(report)
        print()
        total_errors += len(report.errors)
        if not report.ok():
            bad += 1

    if args.all and asset_mgr is not None:
        print("=" * 72)
        print("素材覆盖体检")
        print("=" * 72)
        for issue in audit_assets(asset_mgr):
            print(issue.render())
        print()

    if len(files) > 1:
        print(f"合计：{len(files)} 份剧本，{bad} 份有错误，共 {total_errors} 个错误")

    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
