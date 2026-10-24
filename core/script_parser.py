"""
黑话剧本解析器（分层版）：字符串 -> Token -> AST -> 剧本 JSON

为什么重写
----------
旧实现是「一条大正则 + findall + 逐个查表」。它有三个结构性缺陷：

1. **丢错误**。`re.findall` 只返回匹配到的片段，任何不认识的字符直接消失。
   用户写了 `axax`，解析出两个普攻，`x` 没了，且没有任何提示。
2. **无位置**。`findall` 不返回 span，所以报错只能说"解析失败"，
   没法告诉用户"第 1 行第 12 个字符有个 x 认不出来"。
3. **不可逆**。没有中间表示，JSON 里的 `parallel` / `uncancellable` /
   `duration_ms` 无法回写成字符串，导致编辑器保存时会把这些字段吞掉。

现在的分层：

    原始文本
      ↓ Lexer     逐字符扫描，产出带 (行, 列) 的 Token；不认识就报 E001 并继续
    Token 流
      ↓ Parser    识别修饰符（数字 / + / ! / {ms} / *N / &），产出 Step 列表
    AST
      ↓ Resolver  查角色表、补默认值、生成最终 dict；产出诊断（warning）
    剧本 JSON

这样四件事同时成立：**报错能定位**、**能校验**、**能扩展语法**、**能反向序列化**。

语法
----
兼容旧语法（现有剧本一个字都不用改）：

    a e r q z f s j     普攻 / 技能 / 解放 / 声骸 / 重击 / 处决 / 闪避 / 跳跃
    跳 闪               中文字等同 j / s
    角色名或代称         切人
    (变奏)角色名         变奏切入
    切角色名             显式切人
    a2                  变体（二段普攻）
    e+                  长按

新增语法（全部可选，不影响旧文本）：

    // 注释到行尾        写轴时做标注
    /* 块注释 */
    a*3                 重复三次（等价 aaa）
    z&q                 q 与前面的 z 并行（q 打上 parallel: true）
    r!                  不可打断（uncancellable: true）
    a{620}              这一步占位 620ms（duration_ms）

作者备注
--------
修饰符顺序不限，`e3+` 和 `e+3` 都认；同一修饰符写两次会出 W002 警告。
`&` 不是修饰符而是独立记号：它把**后面那个**动作标记为可并行，
因为语义是"后一步能趁前一步的蓄力先按下去"。
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ====================================================================== 诊断

LEVEL_ERROR = "error"
LEVEL_WARNING = "warning"
LEVEL_INFO = "info"


@dataclass
class Diagnostic:
    """一条解析诊断。带行列，能直接指给用户看。"""

    level: str
    code: str          # E001 / W003 之类，方便搜索与文档索引
    message: str
    line: int = 1
    col: int = 1
    snippet: str = ""  # 已渲染好的"原文 + ^^^"两行

    @property
    def is_error(self):
        return self.level == LEVEL_ERROR

    def render(self, source_name=""):
        head = f"[{self.level.upper()}] {self.code}"
        if source_name:
            head += f" {source_name}"
        head += f" 第 {self.line} 行 第 {self.col} 列：{self.message}"
        if self.snippet:
            return f"{head}\n{self.snippet}"
        return head


def _make_snippet(text, line, col, length=1):
    """把出错位置渲染成"原文 + 尖号"两行，方便一眼看到错在哪。"""
    lines = text.splitlines()
    if not (1 <= line <= len(lines)):
        return ""
    src = lines[line - 1]
    # 制表符按一列算，避免对齐错乱
    caret = " " * (col - 1) + "^" * max(1, length)
    return f"    {src}\n    {caret}"


# ====================================================================== Token

# Token 种类
T_ACTION = "action"     # a / e / r ...
T_CHAR = "char"         # 角色名或代称
T_PREFIX = "prefix"     # 切 / (变奏)
T_AMP = "amp"           # & 并行记号
T_COMMENT = "comment"
T_UNKNOWN = "unknown"


@dataclass
class Token:
    kind: str
    value: str
    line: int
    col: int
    length: int
    raw: str
    # 修饰符（只有 T_ACTION 才有）
    number: str = ""
    hold: bool = False
    uncancellable: bool = False
    duration_ms: Optional[int] = None
    repeat: int = 1

    @property
    def span_end(self):
        return self.col + self.length


@dataclass
class Step:
    """
    AST 的一个节点。同时持有"要序列化成的 dict"和"来源位置"。

    `raw` 保存原文片段，`render()` 靠它反向拼字符串——这是修复
    "编辑器重新解析会丢字段"的基础。
    """

    action: dict
    line: int
    col: int
    raw: str
    modifiers: Tuple[str, ...] = ()   # 已应用的修饰符，回写时按它还原

    @property
    def type(self):
        return self.action.get("type")


# ====================================================================== 词法

class Lexer:
    """
    把文本切成 Token。**不认识就报错并继续**，绝不静默跳过。

    角色名采用"按长度降序前缀匹配"，避免「爱」吃掉「爱琳」这种短名抢先的问题。
    """

    def __init__(self, action_keys, char_lookup):
        """
        :param action_keys: 动作字母表，如 {'a','e','r',...}
        :param char_lookup: 角色名/代称 -> (cid, en_name, full_zh)
        """
        self.action_keys = set(action_keys)
        self.char_lookup = char_lookup
        # 长名优先，防止短别名截断长名
        self._char_keys = sorted(char_lookup.keys(), key=len, reverse=True)
        # 只允许跟在动作后面的修饰符字符，用于校验
        self._modifier_re = re.compile(r'(?:\d+|\+|!|\{\s*\d+\s*\}|\[.*?\]|\*\d+)')

    def tokenize(self, text):
        tokens = []
        diags = []
        i = 0
        n = len(text)
        line, col = 1, 1

        def advance(step):
            """推进游标，同时维护行列。"""
            nonlocal i, line, col
            for _ in range(step):
                if i < n and text[i] == "\n":
                    line += 1
                    col = 1
                else:
                    col += 1
                i += 1

        while i < n:
            ch = text[i]

            # ---- 空白 ----
            if ch in " \t\r\n":
                advance(1)
                continue

            # ---- 行注释 //... ----
            if text.startswith("//", i):
                end = text.find("\n", i)
                end = n if end < 0 else end
                raw = text[i:end]
                tokens.append(Token(T_COMMENT, raw, line, col, len(raw), raw))
                advance(len(raw))
                continue

            # ---- 块注释 /*...*/ ----
            if text.startswith("/*", i):
                end = text.find("*/", i + 2)
                if end < 0:
                    diags.append(Diagnostic(
                        LEVEL_ERROR, "E003", "块注释没有闭合（缺少 */）", line, col,
                        _make_snippet(text, line, col, 2)))
                    raw = text[i:]
                    tokens.append(Token(T_COMMENT, raw, line, col, len(raw), raw))
                    advance(len(raw))
                    continue
                raw = text[i:end + 2]
                tokens.append(Token(T_COMMENT, raw, line, col, len(raw), raw))
                advance(len(raw))
                continue

            # ---- (变奏) 前缀 ----
            if ch in "(（":
                close = ")" if ch == "(" else "）"
                end = text.find(close, i + 1)
                inner = text[i + 1:end] if end > 0 else ""
                if end > 0 and "变奏" in inner:
                    raw = text[i:end + 1]
                    tokens.append(Token(T_PREFIX, "变奏", line, col, len(raw), raw))
                    advance(len(raw))
                    continue
                diags.append(Diagnostic(
                    LEVEL_ERROR, "E004", f"括号内容无法识别（只支持「(变奏)」）：{inner}",
                    line, col, _make_snippet(text, line, col, len(inner) + 2)))
                advance(len(inner) + 2 if end > 0 else 1)
                continue

            # ---- 切 ----
            if ch == "切":
                tokens.append(Token(T_PREFIX, "切", line, col, 1, ch))
                advance(1)
                continue

            # ---- 角色名（长名优先前缀匹配）----
            matched_char = None
            for key in self._char_keys:
                if text.startswith(key, i):
                    matched_char = key
                    break
            if matched_char:
                tokens.append(Token(T_CHAR, matched_char, line, col, len(matched_char), matched_char))
                advance(len(matched_char))
                continue

            # ---- 并行记号 ----
            if ch == "&":
                tokens.append(Token(T_AMP, ch, line, col, 1, ch))
                advance(1)
                continue

            # ---- 动作 + 修饰符 ----
            if ch in self.action_keys:
                start_line, start_col = line, col
                start_i = i
                advance(1)
                # 紧跟的修饰符（中间不允许有空格，空格意味着这是下一个 token）
                while i < n:
                    m = self._modifier_re.match(text, i)
                    if not m:
                        break
                    advance(len(m.group(0)))

                raw = text[start_i:i]
                tok = Token(T_ACTION, ch, start_line, start_col, len(raw), raw)
                self._parse_modifiers(tok, raw[1:], text, start_line, start_col, diags)
                tokens.append(tok)
                continue

            # ---- 不认识：报错 + 跳过 1 个字符 ----
            diags.append(Diagnostic(
                LEVEL_ERROR, "E001",
                f"无法识别的字符 {ch!r}。可用动作：a普攻 e技能 r解放 q声骸 "
                f"z重击 f处决 s闪避 j跳跃；也可写角色名切人",
                line, col, _make_snippet(text, line, col, 1)))
            advance(1)

        return tokens, diags

    def _parse_modifiers(self, tok, mods, text, line, col, diags):
        """把 `3+{620}*2` 这类后缀解析成结构化字段。"""
        seen = set()
        pos = 0
        while pos < len(mods):
            ch = mods[pos]
            snippet = _make_snippet(text, line, col + 1 + pos, 1)

            if ch.isdigit():
                num = ""
                while pos < len(mods) and mods[pos].isdigit():
                    num += mods[pos]
                    pos += 1
                if "number" in seen:
                    diags.append(Diagnostic(LEVEL_WARNING, "W002",
                                            "变体号写了两次，以最后一个为准", line, col, snippet))
                tok.number = num
                seen.add("number")

            elif ch == "+":
                if "hold" in seen:
                    diags.append(Diagnostic(LEVEL_WARNING, "W002",
                                            "长按记号 + 重复出现", line, col, snippet))
                tok.hold = True
                seen.add("hold")
                pos += 1

            elif ch == "!":
                if "uncancel" in seen:
                    diags.append(Diagnostic(LEVEL_WARNING, "W002",
                                            "不可打断记号 ! 重复出现", line, col, snippet))
                tok.uncancellable = True
                seen.add("uncancel")
                pos += 1

            elif ch == "{":
                end = mods.find("}", pos)
                body = mods[pos + 1:end] if end > 0 else ""
                if not body.strip().isdigit():
                    diags.append(Diagnostic(
                        LEVEL_ERROR, "E005",
                        f"时长写法应为 {{毫秒}}，如 a{{620}}；当前是 {{{body}}}",
                        line, col, snippet))
                    pos = len(mods)
                    break
                tok.duration_ms = int(body.strip())
                seen.add("duration")
                pos = end + 1

            elif ch == "*":
                end = mods.find("}", pos)  # 占位，正常走数字分支
                num = ""
                pos += 1
                while pos < len(mods) and mods[pos].isdigit():
                    num += mods[pos]
                    pos += 1
                if not num:
                    diags.append(Diagnostic(
                        LEVEL_ERROR, "E006", "重复写法应为 *次数，如 a*3", line, col, snippet))
                    continue
                if int(num) > 50:
                    diags.append(Diagnostic(
                        LEVEL_WARNING, "W004", f"重复次数 {num} 过大，确认不是笔误？",
                        line, col, snippet))
                tok.repeat = max(1, int(num))
                seen.add("repeat")

            elif ch == "[":
                # 未开放的语法，明确报错而不是吞掉
                end = mods.find("]", pos)
                body = mods[pos + 1:end] if end > 0 else ""
                diags.append(Diagnostic(
                    LEVEL_WARNING, "W005",
                    f"方括号语法尚未启用，内容 [{body}] 被忽略", line, col, snippet))
                pos = (end + 1) if end > 0 else len(mods)

            else:
                diags.append(Diagnostic(
                    LEVEL_ERROR, "E002",
                    f"动作 {tok.value} 后面跟了不支持的记号 {ch!r}", line, col, snippet))
                pos += 1


# ====================================================================== 语法

class Parser:
    """
    Token 流 -> Step 列表。

    只做结构层面的事：把切人前缀挂到角色上、把 `&` 挂到下一个动作上、
    展开 `*N` 重复。不查语义、不补默认值（那是 Resolver 的活）。
    """

    def __init__(self, text, tokens, diags):
        self.text = text
        self.tokens = tokens
        self.diags = diags

    def parse(self):
        steps = []
        pending_prefix = None      # "切" / "变奏"
        pending_parallel = False   # 前面出现过 &，下一个动作要带 parallel

        for tok in self.tokens:
            if tok.kind == T_COMMENT:
                continue

            if tok.kind == T_PREFIX:
                pending_prefix = tok.value
                continue

            if tok.kind == T_AMP:
                # & 属于"下一个动作"，若连续两个 & 只算一次
                if pending_parallel:
                    self.diags.append(Diagnostic(
                        LEVEL_WARNING, "W006", "连续的 & 多余，只保留一个",
                        tok.line, tok.col, _make_snippet(self.text, tok.line, tok.col, 1)))
                pending_parallel = True
                continue

            if tok.kind == T_CHAR:
                steps.append(Step(
                    action={
                        "type": "intro",
                        "next_char": tok.value,        # Resolver 换成数字 id
                        "desc": "",                    # Resolver 填
                        "_prefix": pending_prefix or "切",
                        "_char_key": tok.value,
                    },
                    line=tok.line, col=tok.col, raw=tok.raw,
                    modifiers=("prefix",) if pending_prefix else (),
                ))
                pending_prefix = None
                # & 落在切人上是无意义的：切人不能被并行
                if pending_parallel:
                    self.diags.append(Diagnostic(
                        LEVEL_WARNING, "W007",
                        "切人动作不能并行（会改变在场角色），已忽略 &",
                        tok.line, tok.col, _make_snippet(self.text, tok.line, tok.col, len(tok.raw))))
                    pending_parallel = False
                continue

            if tok.kind == T_ACTION:
                mods = []
                if tok.number:
                    mods.append("number")
                if tok.hold:
                    mods.append("hold")
                if tok.uncancellable:
                    mods.append("uncancel")
                if tok.duration_ms is not None:
                    mods.append("duration")
                if tok.repeat > 1:
                    mods.append("repeat")

                for n in range(tok.repeat):
                    action = {
                        "type": tok.value,             # Resolver 换成 "basic"/"heavy"...
                        "_key": tok.value,
                        "_number": tok.number,
                        "_hold": tok.hold,
                        "_uncancellable": tok.uncancellable,
                        "_duration_ms": tok.duration_ms,
                        "_parallel": pending_parallel,
                    }
                    steps.append(Step(action=action, line=tok.line, col=tok.col,
                                      raw=tok.raw, modifiers=tuple(mods)))
                # & 只作用于紧接着的那一个动作
                pending_parallel = False
                continue

            # T_UNKNOWN 已由 Lexer 报错，这里不用再报
            continue

        if pending_prefix:
            self.diags.append(Diagnostic(
                LEVEL_WARNING, "W008",
                f"结尾的「{pending_prefix}」后面没有跟角色名，已忽略",
                len(self.text.splitlines()) or 1, 1, ""))
        if pending_parallel:
            self.diags.append(Diagnostic(
                LEVEL_WARNING, "W009", "结尾的 & 后面没有动作，已忽略", 1, 1, ""))

        return steps


# ====================================================================== 语义

class Resolver:
    """
    AST -> 最终剧本 dict。

    这里负责所有"翻译"工作：动作字母变类型名、变体号变 variant、
    角色名变槽位 id、补默认值。产出格式与旧解析器**逐字段一致**，
    保证编辑器预览和现有剧本完全不受影响。
    """

    ACTION_TYPES = {
        'a': "basic", 'e': "skill", 'r': "ult", 'q': "echo",
        'z': "heavy", 'f': "execution", 's': "dodge",
        'j': "jump", '跳': "jump", '闪': "dodge",
    }

    DISPLAY_NAMES = {
        'a': "普攻", 'z': "重击", 'e': "技能", 'r': "解放",
        'q': "声骸", 'f': "处决", 'j': "跳跃", '跳': "跳跃",
        's': "闪避", '闪': "闪避",
    }

    def __init__(self, char_lookup, diags, text):
        self.char_lookup = char_lookup
        self.diags = diags
        self.text = text
        self.current_char_id = None   # 由 resolve 逐段推进
        self._emitted = 0             # 已经产出的动作数，用于区分"起手标记"和"中途切人"

    def resolve(self, steps, start_char_id=1):
        self.current_char_id = start_char_id
        self._emitted = 0
        result = []
        for st in steps:
            if st.action["type"] == "intro":
                resolved = self._resolve_intro(st)
                if resolved is not None:
                    result.append(resolved)
                continue
            result.append(self._resolve_action(st))
        return result

    # ------------------------------------------------------------ 动作

    def _resolve_action(self, st):
        a = st.action
        key = a["_key"]
        num = a["_number"]
        action_type = self.ACTION_TYPES.get(key, key)
        desc_name = self.DISPLAY_NAMES.get(key, key.upper())

        variant_parts = []
        # z 永远带 heavy 标签，f 永远带 forte 标签（沿用旧规则，widgets 靠它选边框/角标）
        if key == 'z':
            variant_parts.append("heavy")
        elif key == 'f':
            variant_parts.append("forte")

        # a1 是"第一段普攻"的特例：不加变体，改为要求通用图标
        if num and not (key == 'a' and num == '1'):
            variant_parts.append(num)

        out = {"type": action_type, "desc": f"{desc_name}{num}"}

        if variant_parts:
            out["variant"] = "_".join(variant_parts)

        if a["_hold"]:
            out["hold"] = True
            out["desc"] = f"{out['desc']}(长按)"

        if a["_parallel"]:
            out["parallel"] = True

        if a["_uncancellable"]:
            out["uncancellable"] = True

        if a["_duration_ms"] is not None:
            out["duration_ms"] = int(a["_duration_ms"])

        if key == 'a' and num == '1':
            out["force_general"] = True

        # 记录来源位置，供编辑器高亮（不进 JSON，放在旁边映射里）
        out["_line"] = st.line
        out["_col"] = st.col
        self._emitted += 1
        return out

    # ------------------------------------------------------------ 切人

    def _resolve_intro(self, st):
        a = st.action
        key = a["_char_key"]
        entry = self.char_lookup.get(key)
        if entry is None:
            # Lexer 保证只有 char_lookup 里的 key 才会被识别成 T_CHAR，
            # 走到这里说明 char_lookup 被改过，属于内部错误
            self.diags.append(Diagnostic(
                LEVEL_ERROR, "E010", f"角色 {key} 不在角色表里", st.line, st.col,
                _make_snippet(self.text, st.line, st.col, len(st.raw))))
            return None

        cid, en_name, full_zh = entry
        if cid == self.current_char_id:
            # 起手位置写当前角色是**正常习惯**（"爱aaaa…"表示"从爱弥斯开始"），
            # 这时候保持安静；只有打到一半又写当前角色，才可能真是笔误。
            if self._emitted > 0:
                self.diags.append(Diagnostic(
                    LEVEL_WARNING, "W001",
                    f"「{st.raw}」指向的角色（{full_zh}）已经在场，没有生成切人动作。"
                    f"如果这是笔误，检查是否写错角色",
                    st.line, st.col, _make_snippet(self.text, st.line, st.col, len(st.raw))))
            return None

        prefix = a.get("_prefix") or "切"
        self.current_char_id = cid
        return {
            "type": "intro",
            "next_char": cid,
            "desc": f"{prefix}-{full_zh}",
            "_line": st.line,
            "_col": st.col,
        }


# ====================================================================== 反向

class ScriptWriter:
    """
    剧本 dict -> 黑话字符串。

    这是"编辑器不再吞字段"的基础：编辑器拿到 JSON 后可以先用它还原出
    字符串（含 + ! & {ms} *N），用户改完再解析回去，字段才不会丢。
    """

    LETTERS = {
        "basic": "a", "skill": "e", "ult": "r", "echo": "q",
        "heavy": "z", "execution": "f", "dodge": "s", "jump": "j",
    }

    @classmethod
    def render(cls, script, char_names=None):
        """
        :param script: 剧本动作数组
        :param char_names: {槽位 id: 中文名}，用于拼切人；缺省用 desc 里的名字
        """
        char_names = char_names or {}
        parts = []
        for act in script:
            if act.get("type") == "intro":
                nid = act.get("next_char")
                name = char_names.get(nid) or _name_from_desc(act.get("desc", ""))
                if not name:
                    continue
                prefix = "(变奏)" if str(act.get("desc", "")).startswith("变奏") else ""
                parts.append(f"{prefix}{name}")
                continue

            letter = cls.LETTERS.get(act.get("type"))
            if not letter:
                continue

            # 从 variant 里抽回数字部分；z/f 的 heavy/forte 是自动加的，不回写
            variant = act.get("variant") or ""
            num = ""
            for piece in variant.split("_"):
                if piece.isdigit():
                    num = piece
                    break

            suffix = num
            if act.get("hold") and letter != "z":
                suffix += "+"
            if act.get("uncancellable"):
                suffix += "!"
            # parallel 要写在"前一个动作"之后，这里先记着，拼的时候补
            if act.get("duration_ms"):
                suffix += "{%s}" % act["duration_ms"]

            token = letter + suffix
            if act.get("parallel") and parts:
                # & 属于前一个动作之后、当前动作之前
                parts.append("&" + token)
            else:
                parts.append(token)

        return "".join(parts)


def _name_from_desc(desc):
    """从 "切-爱弥斯" / "变奏-琳奈" 里抽出角色名。"""
    for sep in ("-", "－", "—"):
        if sep in desc:
            return desc.split(sep, 1)[1].strip()
    return ""


# ====================================================================== 门面

class ScriptParser:
    """
    对外唯一入口：字符串 <-> 剧本动作数组。

    用法：

        p = ScriptParser(team_mapping)
        actions, diags = p.parse_with_diagnostics("爱aaaa莫aaaz&q")
        if any(d.is_error for d in diags):
            print(d.render())

    旧解析器的 `parse(text)` 语义保留了（返回纯动作数组），
    旧文件 tools/generic_parser.py 只是对这里的薄封装。
    """

    def __init__(self, team_mapping):
        """
        :param team_mapping: {中文全名: (槽位id, 英文名, [代称...])}
                             兼容旧格式 {名字: (id, 英文名, 别名列表)}
        """
        self.team_mapping = team_mapping
        self.char_lookup = {}
        for full_zh, data in team_mapping.items():
            cid, en_name, aliases = data
            self.char_lookup[full_zh] = (cid, en_name, full_zh)
            for alias in aliases or []:
                alias = alias.strip()
                if alias:
                    self.char_lookup[alias] = (cid, en_name, full_zh)

        self.lexer = Lexer(Resolver.ACTION_TYPES.keys(), self.char_lookup)

    # ------------------------------------------------------------ 主流程

    def parse_with_diagnostics(self, text, start_char_id=1):
        """
        完整解析，返回 (动作数组, 诊断列表)。

        诊断**不会中断解析**：遇到坏字符就记一条 E001，继续往下走。
        这样用户一次能看到所有错误，而不是改一个跑一次。
        """
        text = text or ""
        if not text.strip():
            return [], [Diagnostic(LEVEL_INFO, "I001", "脚本为空")]

        tokens, diags = self.lexer.tokenize(text)
        steps = Parser(text, tokens, diags).parse()
        actions = Resolver(self.char_lookup, diags, text).resolve(steps, start_char_id)

        # 内部字段不对外暴露，只留 (_line/_col) 供 UI 定位
        cleaned = []
        for act in actions:
            cleaned.append({
                k: v for k, v in act.items() if not k.startswith("_") or k in ("_line", "_col")
            })

        if not cleaned and not any(d.is_error for d in diags):
            diags.append(Diagnostic(LEVEL_WARNING, "W010", "没有解析出任何动作，检查是否只写了注释"))

        return cleaned, diags

    def parse(self, text, start_char_id=1):
        """
        兼容旧接口：只要动作数组，诊断丢弃。

        注意：这是**有损**的入口，专供不关心错误的旧调用方。
        新代码请用 parse_with_diagnostics。
        """
        actions, _ = self.parse_with_diagnostics(text, start_char_id)
        return [{k: v for k, v in a.items() if not k.startswith("_")} for a in actions]

    def render(self, script, char_names=None):
        """反向序列化，见 ScriptWriter.render。"""
        return ScriptWriter.render(script, char_names)
