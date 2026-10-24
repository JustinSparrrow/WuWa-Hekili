"""
把 characters.json 拆成每个角色一个档案文件：db/characters/db_<中文名>.json

为什么要拆
----------
`characters.json` 是抓取过程的汇总（65 个角色一个大字典），适合做批量处理，
但不适合人工查阅和版本管理 —— 改一个角色要 diff 几千行。

拆开之后每个文件是一份「角色档案」：基础资料 + 素材清单。项目需要的东西都在里面，
不塞技能描述（那是 wiki 的活，对"该按哪个键"没帮助）。

产物结构
--------
    {
      "name": "爱弥斯",                 # 中文名
      "name_en": "Aemeath",            # 项目素材目录名
      "code": "Aimisi",                # 游戏内部代号（对应图标资源目录）
      "rarity": 5,
      "element": {"cn": "热熔", "en": "fusion"},
      "weapon":  {"cn": "迅刀", "en": "sword"},
      "gender": "女", "birthplace": "...",
      "wiki_url": "https://wiki.kurobbs.com/mc/item/...",
      "assets": {                       # 实际扫目录得到，缺的槽位不出现
        "normal_attack": ["normal.png", "normal_2.png", "normal_3.png"],
        "resonance_skill": ["skill.png"],
        ...
      },
      "asset_source": "nanoka" | "manual" | "mixed",
      "scraped_at": "2026-10-25T05:36:54"
    }

`asset_source` 的判定：图标是 128×128 带 alpha 的算 nanoka 来的，其余尺寸/无 alpha
算手工截图（项目早期素材），两者都有就是 mixed。这样一眼能看出哪些角色还需要补。

用法
----
    python tools/factory/build_db.py                 # 全部生成
    python tools/factory/build_db.py --char 爱弥斯    # 只生成一个
    python tools/factory/build_db.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# 独立运行：就地向上找到项目根（含 main.py）并加入 import 路径，再复用统一根查找。
_root = HERE
while True:
    _root = os.path.dirname(_root)
    if os.path.exists(os.path.join(_root, "main.py")) or _root == os.path.dirname(_root):
        break
sys.path.insert(0, _root)

from utils.logger import log                         # noqa: E402
from utils.paths import project_root                 # noqa: E402

ROOT = str(project_root())

DB_DIR = os.path.join(HERE, "db")
OUT_DIR = os.path.join(DB_DIR, "characters")
CHARACTERS_JSON = os.path.join(DB_DIR, "characters.json")
NAME_MAP_JSON = os.path.join(DB_DIR, "name_map.json")
CODE_MAP_JSON = os.path.join(DB_DIR, "code_map.json")
ASSETS_DIR = os.path.join(ROOT, "assets", "characters")
OCCUPATION_FILE = os.path.join(ASSETS_DIR, "Character_Occupation.txt")

# 项目的素材槽位（与 config.json 的 assets.folder_mapping 对齐）
ASSET_SLOTS = [
    "normal_attack", "heavy", "resonance_skill", "resonance_liberation",
    "echo", "character", "jump", "dodge", "forte_circuit", "concerto_energy",
]


def _load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _classify_icon(path):
    """判断一张图是游戏原生图标还是手工截图。"""
    try:
        from PIL import Image
        with Image.open(path) as im:
            if im.size == (128, 128) and im.mode in ("RGBA", "LA"):
                return "nanoka"
            return "manual"
    except Exception:                        # noqa: BLE001
        return "unknown"


def scan_assets(en_name):
    """
    扫一个角色的素材目录。

    :return: (assets 字典, 来源集合)
    """
    if not en_name:
        return {}, set()

    base = os.path.join(ASSETS_DIR, en_name)
    if not os.path.isdir(base):
        return {}, set()

    assets, sources = {}, set()
    for slot in ASSET_SLOTS:
        slot_dir = os.path.join(base, slot)
        if not os.path.isdir(slot_dir):
            continue
        files = sorted(f for f in os.listdir(slot_dir) if f.lower().endswith(".png"))
        if not files:
            continue
        assets[slot] = files
        for f in files:
            sources.add(_classify_icon(os.path.join(slot_dir, f)))

    return assets, sources


def build_one(cn, rec, name_map, code_map, old):
    """拼一份角色档案。保留旧文件里的非空字段，避免把手工填的内容冲掉。"""
    # 与 icon_fetcher 保持一致：缺英文名时用拼音代号当目录名
    en = (name_map.get(cn) or "").strip() or (code_map.get(cn) or "")
    assets, sources = scan_assets(en)

    if not sources:
        source_label = "none"
    elif sources == {"nanoka"}:
        source_label = "nanoka"
    elif sources == {"manual"}:
        source_label = "manual"
    elif "nanoka" in sources:
        source_label = "mixed"
    else:
        source_label = "manual"

    doc = {
        "name": cn,
        "name_en": en or None,
        "code": code_map.get(cn) or None,
        "rarity": rec.get("rarity"),
        "element": {"cn": rec.get("element_cn"), "en": rec.get("element_en")},
        "weapon": {"cn": rec.get("weapon_cn"), "en": rec.get("weapon_en")},
        "gender": rec.get("gender") or None,
        "birthplace": rec.get("birthplace") or None,
        "wiki_url": rec.get("url"),
        "assets": assets,
        "asset_source": source_label,
        "scraped_at": rec.get("scraped_at"),
    }

    # 旧档案里可能有手工补充的说明，别丢
    for key in ("basic_mechanism", "note", "tags"):
        if old.get(key):
            doc[key] = old[key]

    return doc


def update_occupation(docs):
    """
    把档案里的「英文名=武器类型」补进 Character_Occupation.txt。

    为什么需要这一步：icon_fetcher 新增的角色目录用的是**拼音代号**
    （Daniya / Feixue / Suisui …），而 wiki_spider 生成的映射表里只有
    name_map 的英文名，两边对不上 → 这些角色的普攻/重击掉通用库时
    找不到武器子目录。

    合并策略：保留文件里已有的行（人工改过的参数不丢），只追加缺的。

    :return: 新增条数
    """
    rows = {}
    header = []
    if os.path.exists(OCCUPATION_FILE):
        with open(OCCUPATION_FILE, encoding="utf-8") as f:
            for line in f:
                s = line.rstrip("\n")
                if s.startswith("#") or not s.strip():
                    header.append(s)
                elif "=" in s:
                    k, _, v = s.partition("=")
                    if k.strip() and v.strip():
                        rows[k.strip()] = v.strip()

    added = 0
    for doc in docs:
        en = doc.get("name_en")
        weapon = (doc.get("weapon") or {}).get("en")
        if en and weapon and en not in rows:
            rows[en] = weapon
            added += 1

    if not added:
        return 0

    # 重写整个文件：注释头保持原样，数据按字母序
    out = header[:] if header else ["# 角色 → 武器类型映射"]
    if out and not out[-1].strip():
        pass
    elif out:
        out.append("")
    out.extend(f"{k}={v}" for k, v in sorted(rows.items()))

    with open(OCCUPATION_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    return added


def main():
    ap = argparse.ArgumentParser(description="把 characters.json 拆成每个角色一个档案")
    ap.add_argument("--char", help="只处理指定角色（中文名，可逗号分隔）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    characters = _load(CHARACTERS_JSON, {})
    if not characters:
        log.error(f"找不到 {CHARACTERS_JSON}，先跑 wiki_spider.py")
        return 1

    name_map = _load(NAME_MAP_JSON, {})
    code_map = _load(CODE_MAP_JSON, {})

    targets = sorted(characters)
    if args.char:
        wanted = set(args.char.split(","))
        # 同时接受中文名和英文名
        targets = [c for c in targets if c in wanted or name_map.get(c) in wanted]

    os.makedirs(OUT_DIR, exist_ok=True)

    done, no_asset, docs = 0, [], []
    for cn in targets:
        path = os.path.join(OUT_DIR, f"db_{cn}.json")
        old = _load(path, {})
        doc = build_one(cn, characters[cn], name_map, code_map, old)
        docs.append(doc)

        if not doc["assets"]:
            no_asset.append(cn)

        if not args.dry_run:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=1)

        slots = len(doc["assets"])
        files = sum(len(v) for v in doc["assets"].values())
        print(f"  {cn:9s} {doc['name_en'] or '—':16s} {slots} 槽 {files:2d} 图  "
              f"来源={doc['asset_source']}")
        done += 1

    print()
    log.info(f"已生成 {done} 份档案 -> {OUT_DIR}")

    if not args.dry_run and not args.char:
        added = update_occupation(docs)
        if added:
            log.info(f"Character_Occupation.txt 补了 {added} 条（代号目录也需要武器类型）")
    if no_asset:
        print(f"有 {len(no_asset)} 个角色还没有任何素材：" + " ".join(no_asset[:12])
              + (" …" if len(no_asset) > 12 else ""))
        if not args.dry_run:
            print("   补齐：python tools/factory/icon_fetcher.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
