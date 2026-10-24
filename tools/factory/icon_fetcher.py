"""
鸣潮技能图标下载器 —— 从 nanoka 镜像取游戏原生图标，按项目素材结构入库。

为什么需要这个
--------------
自己做素材只能在游戏里一帧一帧截图再手抠，65 个角色 × 8 个技能 = 500 多张，
不现实。而 wiki 正文里几乎不插技能图标（实测抽样 12 个角色，0 个有），
所以「从 wiki 抓图」这条路走不通。

真正的来源是游戏 UI 资源包。`static.nanoka.cc` 是社区维护的解包资源镜像，
目录结构与游戏内一致：

    {NANOKA}/SkillIcon<拼音代号>/SP_Icon<拼音代号><后缀>.webp

每张 128×128、带 alpha、白色蒙版（游戏运行时按元素色着色）。
对应关系是从 wiki 技能区块的图标引用反查出来的（锁暝页面能对上 7 个）。

后缀含义（实测 6 个角色交叉验证）
--------------------------------
    A1..A6   常态攻击各段，A1 是主图标
    B1..B6   形态变化后的招式（如「念深状态下普攻替换」）
    Y / Y1   共鸣技能（部分角色用 Y1）
    C1..C2   共鸣解放
    D1..D2   共鸣回路
    QTE      变奏技能
    T        延奏技能

不同角色后缀集合不同（忌炎只有 10 个，爱弥斯有 17 个），所以按角色逐个探测，
不用固定清单。

用法
----
    python tools/factory/icon_fetcher.py --list            # 看哪些角色能下、缺什么
    python tools/factory/icon_fetcher.py --limit 3         # 先试 3 个
    python tools/factory/icon_fetcher.py                   # 有英文名的角色全量
    python tools/factory/icon_fetcher.py --char 爱弥斯      # 只下一个
    python tools/factory/icon_fetcher.py --dry-run         # 只看计划不下载
    python tools/factory/icon_fetcher.py --tint            # 按元素色着色（默认保留白色蒙版）
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
# 独立运行：就地向上找到项目根（含 main.py）并加入 import 路径，再复用统一根查找。
_root = HERE
while True:
    _root = os.path.dirname(_root)
    if os.path.exists(os.path.join(_root, "main.py")) or _root == os.path.dirname(_root):
        break
sys.path.insert(0, _root)

from utils.logger import log                        # noqa: E402
from utils.paths import project_root                # noqa: E402

ROOT = str(project_root())

# ---------------------------------------------------------------- 常量

NANOKA = "https://static.nanoka.cc/assets/ww/UIResources/Common/Atlas/SkillIcon"

# CDN 对无 UA 的请求返回 403（urllib 默认 UA 就是空的），必须带
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

DB_DIR = os.path.join(HERE, "db")
CHARACTERS_JSON = os.path.join(DB_DIR, "characters.json")   # wiki_spider 产出
NAME_MAP_JSON = os.path.join(DB_DIR, "name_map.json")       # 中文名 -> 项目英文名
CODE_MAP_JSON = os.path.join(DB_DIR, "code_map.json")       # 中文名 -> 拼音代号（可手工改）

ASSETS_DIR = os.path.join(ROOT, "assets", "characters")

# 后缀 -> (项目子目录, 文件名主干)
#
# A 系列是**技能栏图标**（简洁的武器形/几何形，游戏里技能栏显示的就是它）
# B 系列是**技能演示图**（角色动作剪影，wiki 技能介绍里配的那种）
#
# 这两种在不同角色身上扮演的角色不一样：爱弥斯有完整的 A1~A4，赞妮却一个 A 都没有、
# 只有 B1~B5。所以规则是「有 A 就用 A，没有 A 才拿 B 顶普攻」，
# 见 fetch_character 里的 fallback 逻辑。
SUFFIX_MAP = {
    "A1": ("normal_attack", "normal"),
    "A2": ("normal_attack", "normal_2"),
    "A3": ("normal_attack", "normal_3"),
    "A4": ("normal_attack", "normal_4"),
    "A5": ("normal_attack", "normal_5"),
    "A6": ("normal_attack", "normal_6"),
    "Y":  ("resonance_skill", "skill"),
    "Y1": ("resonance_skill", "skill"),
    "C1": ("resonance_liberation", "liberation"),
    "C2": ("resonance_liberation", "liberation_2"),
    "D1": ("forte_circuit", "forte"),
    "D2": ("forte_circuit", "forte_2"),
    "QTE": ("character", "intro"),
    "T":  ("character", "outro"),
}

# 没有 A 系列时，B 系列顶到普攻槽位用
B_FALLBACK_STEMS = {
    "B1": "normal", "B2": "normal_2", "B3": "normal_3",
    "B4": "normal_4", "B5": "normal_5", "B6": "normal_6",
}

# 探测顺序。先猜常见后缀，命中就把该前缀的全部序号都试完
CANDIDATE_SUFFIXES = (
    [f"A{i}" for i in range(1, 7)]
    + [f"B{i}" for i in range(1, 7)]
    + ["Y", "Y1"]
    + [f"C{i}" for i in range(1, 4)]
    + [f"D{i}" for i in range(1, 4)]
    + ["QTE", "T"]
)

# 元素色（--tint 时把白色蒙版染成元素色）
ELEMENT_TINT = {
    "electro": (177, 140, 255),     # 导电
    "fusion":  (255, 107, 61),      # 热熔
    "glacio":  (91, 200, 255),      # 冷凝
    "aero":    (88, 224, 176),      # 气动
    "spectro": (255, 210, 74),      # 衍射
    "havoc":   (192, 71, 158),      # 湮灭
}

# 拼音能对上但 pypinyin 会读错的，手工钉死
MANUAL_CODES = {
    "长离": "Changli",      # 多音字，zhang -> chang
    "露西": "Lucy",
    "仇远": "Qiuyuan",
    "琳奈": "LinNai",       # LinNai 是驼峰，拼音匹配会漏
    "莫宁": "MoNing",
    "嘉贝莉娜": "JiaBeiLiNa",
    "秧秧·玄翎": "XuanLing",
    "陆·赫斯": "Luhesi",
}


# ---------------------------------------------------------------- 工具

def _fetch(url, timeout=12):
    """下载一个 URL，返回 bytes；失败返回 None。"""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return r.read() if r.status == 200 else None
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)


# ---------------------------------------------------------------- 代号解析

def build_code_map(characters, name_map, saved):
    """
    中文名 -> 拼音代号。

    三条来源，优先级从高到低：
        1. code_map.json 里已有的（人工确认过，永远不覆盖）
        2. MANUAL_CODES 手工钉死的
        3. pypinyin 生成后与已知代号比对

    对不上的宁可留空，也不瞎猜 —— 猜错会静默下到别的角色的图，比没有更难查。

    :param saved: 已加载的 code_map 字典（含 `_known_codes`）。必须由调用方传入，
                  不能在这里重新读文件 —— 首次运行时文件还不存在，重新读会得到
                  空 dict，导致所有拼音匹配全部失效。
    """
    from pypinyin import lazy_pinyin

    low_to_code = {c.lower(): c for c in saved.get("_known_codes", [])}

    resolved, missing = {}, []
    for cn in characters:
        if saved.get(cn):
            resolved[cn] = saved[cn]
            continue

        if cn in MANUAL_CODES:
            resolved[cn] = MANUAL_CODES[cn]
            continue

        # 漂泊者的多个形态在资源里是 Zhujue* / Vision*，靠拼音对不上，跳过
        if "漂泊者" in cn:
            missing.append((cn, "漂泊者形态需手工指定代号"))
            continue

        py = "".join(lazy_pinyin(cn)).lower().replace("·", "")
        if py in low_to_code:
            resolved[cn] = low_to_code[py]
        else:
            missing.append((cn, f"拼音 {py!r} 无对应目录"))

    return resolved, missing


def discover_suffixes(code):
    """
    探测某个角色实际有哪些后缀。

    逐个发 HEAD 不行（CDN 对 HEAD 也返回 403 以外的怪结果），直接 GET 但
    只读 200 状态、丢弃内容。并发 12 路，单角色约 1 秒。
    """
    def probe(suffix):
        url = f"{NANOKA}/SkillIcon{code}/SP_Icon{code}{suffix}.webp"
        return suffix, _fetch(url, timeout=8) is not None

    with ThreadPoolExecutor(max_workers=20) as ex:
        return sorted(s for s, ok in ex.map(probe, CANDIDATE_SUFFIXES) if ok)


# ---------------------------------------------------------------- 下载与落盘

def _maybe_tint(png_bytes, element_en):
    """把白色蒙版染成元素色（--tint 时用）。做不到就退回原图。"""
    color = ELEMENT_TINT.get(element_en)
    if not color:
        return png_bytes
    try:
        from PIL import Image
    except ImportError:
        return png_bytes

    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    r, g, b = color
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            pr, pg, pb, pa = px[x, y]
            if pa == 0:
                continue
            # 用原图的灰度当亮度，色相换成元素色
            lum = (pr * 299 + pg * 587 + pb * 114) // 1000
            px[x, y] = (r * lum // 255, g * lum // 255, b * lum // 255, pa)
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def fetch_character(cn_name, code, en_name, element_en, tint=False, dry_run=False, overwrite=False):
    """
    下载一个角色的全部图标。

    默认**不覆盖已存在的文件**。原因：项目里部分角色是作者手工截图裁的
    （带游戏内元素光晕），观感可能比原始白色蒙版更接近游戏本体；
    而且 `forte_circuit/forte.png` 这种原本是能量条截图，语义和技能图标完全不同。
    要覆盖得显式加 --overwrite。

    :return: (写入文件数, 跳过的后缀列表, 因已存在而跳过的文件名列表)
    """
    suffixes = discover_suffixes(code)
    if not suffixes:
        return 0, ["所有后缀均 404"], []

    written, skipped, existing = 0, [], []

    # 先把要下的后缀筛出来，之后并发下载。串行的话单角色要 10 秒以上，
    # 37 个角色就是 7 分钟，体感太差。
    has_a_series = any(s.startswith("A") for s in suffixes)
    pending = []
    for suffix in suffixes:
        target = SUFFIX_MAP.get(suffix)
        if not target and not has_a_series and suffix in B_FALLBACK_STEMS:
            # 这个角色没有技能栏图标（A 系列），拿演示图（B 系列）顶普攻槽位。
            # 观感上和游戏技能栏不同，但比空着强，而且确实是这个角色的招式。
            target = ("normal_attack", B_FALLBACK_STEMS[suffix])
        if not target:
            skipped.append(suffix)
            continue
        sub_dir, stem = target
        out_path = os.path.join(ASSETS_DIR, en_name, sub_dir, f"{stem}.png")

        if not overwrite and os.path.exists(out_path):
            existing.append(f"{sub_dir}/{stem}.png")
            continue
        pending.append((suffix, sub_dir, stem, out_path))

    if dry_run:
        return len(pending), skipped, existing

    def download(item):
        suffix, sub_dir, stem, out_path = item
        url = f"{NANOKA}/SkillIcon{code}/SP_Icon{code}{suffix}.webp"
        raw = _fetch(url, timeout=15)
        if raw is None:
            return suffix, None
        return suffix, (_maybe_tint(raw, element_en) if tint else _to_png(raw))

    with ThreadPoolExecutor(max_workers=8) as ex:
        for item, (suffix, png) in zip(pending, ex.map(download, pending)):
            if png is None:
                skipped.append(suffix)
                continue
            os.makedirs(os.path.dirname(item[3]), exist_ok=True)
            with open(item[3], "wb") as f:
                f.write(png)
            written += 1

    return written, skipped, existing


def _to_png(webp_bytes):
    """webp -> png。Qt 加载 webp 需要插件，统一转成 png 最省事。"""
    try:
        from PIL import Image
    except ImportError:
        log.error("需要 Pillow 才能把 webp 转 png：pip install pillow")
        return None
    try:
        im = Image.open(io.BytesIO(webp_bytes)).convert("RGBA")
        out = io.BytesIO()
        im.save(out, "PNG")
        return out.getvalue()
    except Exception as e:                      # noqa: BLE001
        log.debug(f"转 png 失败: {e}")
        return None


# ---------------------------------------------------------------- 入口

def main():
    ap = argparse.ArgumentParser(description="从 nanoka 镜像下载鸣潮技能图标")
    ap.add_argument("--char", help="只处理指定角色（中文名，可逗号分隔）")
    ap.add_argument("--limit", type=int, help="只处理前 N 个角色")
    ap.add_argument("--list", action="store_true", help="只列出计划，不下载")
    ap.add_argument("--dry-run", action="store_true", help="模拟执行")
    ap.add_argument("--tint", action="store_true", help="按元素色着色（默认保留白色蒙版）")
    ap.add_argument("--overwrite", action="store_true", help="覆盖已存在的文件（默认跳过）")
    ap.add_argument("--quiet", action="store_true", help="少打点日志")
    ap.add_argument("--refresh-codes", action="store_true",
                    help="重新探测全部拼音代号（首次运行必须带，约 1 分钟）")
    args = ap.parse_args()

    characters = _load_json(CHARACTERS_JSON, {})
    if not characters:
        log.error(f"找不到 {CHARACTERS_JSON}，先跑 wiki_spider.py")
        return 1

    name_map = _load_json(NAME_MAP_JSON, {})
    code_map = _load_json(CODE_MAP_JSON, {})

    # ---- 首次运行：拉一次目录清单，得到全部合法代号 ----
    if args.refresh_codes or not code_map.get("_known_codes"):
        log.info("正在获取角色代号清单（GitHub API，约 3 秒）…")
        raw = _fetch("https://api.github.com/repos/TomyJan/WutheringWaves-UIResources"
                     "/contents/UIResources/Common/Atlas/SkillIcon?ref=3.7", timeout=25)
        if not raw:
            log.error("获取代号清单失败。可直接编辑 db/code_map.json 手工填写。")
            return 1
        try:
            entries = json.loads(raw.decode("utf-8"))
            known = sorted(e["name"].replace("SkillIcon", "") for e in entries if e.get("type") == "dir")
        except (json.JSONDecodeError, KeyError) as e:
            log.error(f"解析代号清单失败: {e}")
            return 1
        code_map["_known_codes"] = known
        log.info(f"共 {len(known)} 个角色代号")

    resolved, unresolved = build_code_map(characters, name_map, code_map)
    code_map.update(resolved)
    if not args.dry_run:
        _save_json(CODE_MAP_JSON, code_map)

    # ---- 组装待办 ----
    tasks, skipped = [], []
    for cn, rec in sorted(characters.items()):
        en = (name_map.get(cn) or "").strip()
        code = resolved.get(cn)
        if args.char and cn not in args.char.split(","):
            continue
        if not code:
            skipped.append((cn, "缺拼音代号（填 db/code_map.json）"))
            continue
        # 缺英文名时用拼音代号当目录名。理由：代号就是游戏内部的官方英文名，
        # 比留空更有用；剧本里写这个名字就能查到图，以后想改也只改目录名。
        if not en:
            en = code
            if not args.quiet:
                log.debug(f"{cn} 缺英文名，暂用代号 {code} 作目录")
        tasks.append((cn, code, en, rec.get("element_en"), rec.get("weapon_en")))

    if args.limit:
        tasks = tasks[:args.limit]

    print()
    print(f"待下载 {len(tasks)} 个角色" + (f"，跳过 {len(skipped)} 个" if skipped else ""))
    for cn, reason in skipped[:10]:
        print(f"    跳过 {cn}: {reason}")
    if len(skipped) > 10:
        print(f"    … 另有 {len(skipped) - 10} 个")
    print()

    if args.list or args.dry_run:
        for cn, code, en, elem, weapon in tasks:
            print(f"  {cn:8s} {en:16s} 代号={code:14s} 元素={elem or '?':10s} 武器={weapon or '?'}")
        return 0

    # ---- 下载 ----
    total_files, total_skipped_existing, failed = 0, 0, []
    for i, (cn, code, en, elem, weapon) in enumerate(tasks, 1):
        began = time.time()
        written, ignored, existing = fetch_character(
            cn, code, en, elem,
            tint=args.tint, overwrite=args.overwrite)
        total_files += written
        total_skipped_existing += len(existing)
        cost = time.time() - began

        if written == 0 and not existing:
            failed.append((cn, en, ignored))
            print(f"  [{i:2d}/{len(tasks)}] {cn:8s} ✗ 无图 {ignored[:3]}")
        else:
            parts = []
            if written:
                parts.append(f"新增 {written} 张")
            if existing:
                parts.append(f"已存在 {len(existing)} 张")
            tail = f"  跳过 {','.join(ignored[:3])}" if ignored else ""
            print(f"  [{i:2d}/{len(tasks)}] {cn:8s} ✓ {' / '.join(parts)} ({cost:.1f}s){tail}")

        time.sleep(0.15)        # 轻微节流，别把镜像打疼

    print()
    log.info(f"完成：新增 {total_files} 张图，{total_skipped_existing} 张因已存在跳过")
    if total_skipped_existing and not args.overwrite:
        print("   想用游戏原图替换手工截图？加 --overwrite 重跑（会覆盖，建议先 git commit）")
    if failed:
        print(f"有 {len(failed)} 个角色没拿到图：")
        for cn, en, why in failed:
            print(f"  {cn} ({en}): {why[:3]}")
    print("\n下一步：python tools/checks/routine_lint.py --assets-only 看覆盖率")
    return 0


if __name__ == "__main__":
    sys.exit(main())
