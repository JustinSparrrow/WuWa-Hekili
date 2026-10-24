"""
库街区 wiki 角色数据爬虫（v2）

站点：https://wiki.kurobbs.com/mc/
- 列表页 `/mc/catalogue/list?fid=1099&sid=1105`（共鸣者分类，当前 65 个）
- 详情页 `/mc/item/<id>`

为什么之前那版跑不通
--------------------
1. **只抓了单个角色**：URL 硬编码成某一个 item，没有"遍历"这一步
2. **选择器靠猜**：`.char-stats-table` / `.skill-introduce-content__item--active`
   这类 class 在现版本页面里已经不存在了，全部静默失败（异常被 try 吞掉，
   所以看起来"跑完了"，实际字段全空）
3. **抓的不是项目要的东西**：`stats_90`（90 级属性）、`skills_lv10`（技能倍率）、
   `resonance_chains`（共鸣链）对"连招提示"没有直接作用

现在抓什么、为什么
------------------
项目真正需要的只有三类，其余都是锦上添花：

| 数据 | 用途 | 缺了会怎样 |
|---|---|---|
| 角色 → **武器类型** | 生成 `Character_Occupation.txt` | 普攻/重击落不到 `_general/normal_attack/<武器>/` |
| 角色 → 元素 / 稀有度 | 剧本备注、悬浮窗显示 | 无（纯信息） |
| 中文名 ↔ 英文名 | 素材目录用英文名 | 剧本里选不到角色 |

游戏数值（属性、倍率、共鸣链）对"下一步按哪个键"没有帮助，默认不抓。
需要时加 `--with-stats`。

页面结构（2026-10 实测，改版后需要重新核对）
-------------------------------------------
    列表页   a[href*='/item/'] 卡片内：
             .card-footer span         角色名
             [class*='card-star-N']    稀有度（N=4/5）
             .card-skill-attr-icon img[src*='role-attr-']   元素（URL 里含拼音）
    详情页   .role-tags .text-ellipsis
             形如 "性别：女" / "出生：梦州" / "武器：迅刀" / "属性：导电"
             page.title() 形如 "锁暝-鸣潮WIKI官网-..."

用法
----
    python tools/factory/wiki_spider.py                # 抓全部（已抓过的跳过）
    python tools/factory/wiki_spider.py --limit 5      # 只抓前 5 个，先试水
    python tools/factory/wiki_spider.py --force        # 全部重抓
    python tools/factory/wiki_spider.py --headful      # 显示浏览器（排查用）
    python tools/factory/wiki_spider.py --occupation   # 顺带生成 Character_Occupation.txt
    python tools/factory/wiki_spider.py --name-map     # 生成中英文名对照表骨架

产出
----
    tools/factory/db/characters.json          汇总（中文名为 key）
    tools/factory/db/name_map.json            中文 → 英文名对照（需要人工补）
    assets/characters/Character_Occupation.txt  仅 --occupation 时写入
"""

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ============================================================ 路径与常量

_HERE = Path(__file__).resolve().parent          # tools/factory
# 独立运行：就地向上找到项目根（含 main.py）并加入 import 路径，再复用统一根查找。
_root = _HERE
while True:
    _root = _root.parent
    if (_root / "main.py").is_file() or _root == _root.parent:
        break
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from utils.paths import project_root             # noqa: E402

_ROOT = project_root()                            # 项目根
_DB_DIR = _HERE / "db"
_AGG_PATH = _DB_DIR / "characters.json"
_NAME_MAP_PATH = _DB_DIR / "name_map.json"
_OCCUPATION_PATH = _ROOT / "assets" / "characters" / "Character_Occupation.txt"

LIST_URL = "https://wiki.kurobbs.com/mc/catalogue/list?fid=1099&sid=1105"
BASE_URL = "https://wiki.kurobbs.com"

# 武器中文 → 英文（英文要和 assets/characters 下的子目录名一致）
WEAPON_MAP = {
    "迅刀": "sword",
    "长刃": "broadblade",
    "佩枪": "pistols",
    "臂铠": "gauntlets",
    "音感仪": "rectifier",
}

# 元素：中文 → (图标里的拼音, 英文)
ELEMENT_MAP = {
    "导电": ("daodian", "electro"),
    "热熔": ("rerong", "fusion"),
    "冷凝": ("bingning", "glacio"),
    "气动": ("qidong", "aero"),
    "衍射": ("yanshe", "spectro"),
    "湮灭": ("jielin", "havoc"),
}

# 已知的中文 → 英文名对照（种子）。
# 只填**能确认**的；不确定的一律留空，由 db/name_map.json 人工补。
# 猜错会让剧本选到错的素材目录，比留空更难查——留空至少会在报告里被点名。
SEED_NAME_MAP = {
    # —— 已在 assets 里有素材目录的 ——
    "爱弥斯": "Aemeath",
    "琳奈": "Lynae",
    "莫宁": "Mornye",
    "弗洛洛": "Phrolova",
    "守岸人": "Shorekeeper",
    "坎特蕾拉": "Cantarella",
    "奥古斯塔": "Augusta",
    "尤诺": "luno",
    "秧秧": "Yangyang",
    "炽霞": "Chixia",
    "白芷": "Baizhi",
    "渊武": "Yuanwu",
    "桃祈": "Taoqi",
    "散华": "Sanhua",
    "丹瑾": "Danjin",
    "莫特斐": "Mortefi",
    "卡卡罗": "Calcharo",
    "鉴心": "Jianxin",
    "凌阳": "Lingyang",
    "安可": "Encore",
    "维里奈": "Verina",
    "忌炎": "Jiyan",
    "吟霖": "Yinlin",
    "今汐": "Jinhsi",
    "长离": "Changli",
    "相里要": "Xiangli Yao",
    "折枝": "ZheZhi",
    "釉瑚": "Youhu",
    "椿": "Camellya",
    "洛可可": "Roccia",
    "珂莱塔": "Carlotta",
    "布兰特": "Brant",
    "菲比": "Phoebe",
    "赞妮": "Zani",
    "夏空": "Ciaccona",
    "卡提希娅": "Cartethyia",
    "露帕": "Lupa",
    "嘉贝莉娜": "Galbrena",
    "仇远": "Qiuyuan",
    "卜灵": "Buling",
    "千咲": "Chisa",
    "灯灯": "Lumi",
    "陆·赫斯": "Luuk Herssen",
    # —— 漂泊者有多套形态，素材统一用 Rover ——
    "漂泊者-女-导电": "Rover",
    "漂泊者-男-导电": "Rover",
    "漂泊者-女-气动": "Rover",
    "漂泊者-男-气动": "Rover",
    "漂泊者-女-衍射": "Rover",
    "漂泊者-男-衍射": "Rover",
    "漂泊者-女-湮灭": "Rover",
    "漂泊者-男-湮灭": "Rover",
}


# ============================================================ 工具函数

def _log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def _sleep(a=0.8, b=1.6):
    """随机延时。固定间隔的请求节奏太像机器人。"""
    time.sleep(random.uniform(a, b))


def _load_json(path, default):
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _log(f"读取 {path.name} 失败（{e}），按空处理")
        return default


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================ 抓取

class WikiSpider:
    """
    两步走：先抓列表拿到所有 (名字, item_id)，再逐个进详情页。

    列表页其实已经带了名字/星级/元素，理论上可以省掉详情页。
    但仍然要进详情页，因为：
      - 列表页没有**武器类型**，而这正是项目最需要的字段
      - 详情页的 `.role-tags` 是结构化文本，比从图标 URL 猜元素更可靠
    """

    def __init__(self, headful=False):
        self.headful = headful
        self.browser = None
        self.context = None
        self.page = None

    # -------------------------------------------------- 生命周期

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=not self.headful)
        self.context = self.browser.new_context(
            viewport={"width": 1400, "height": 1200},
            # 伪装成普通浏览器，减少被拦的概率
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
        )
        self.page = self.context.new_page()
        return self

    def __exit__(self, *exc):
        try:
            if self.browser:
                self.browser.close()
            self._pw.stop()
        except Exception:
            pass

    # -------------------------------------------------- 列表页

    def fetch_index(self):
        """返回 [{name, href, item_id, rarity, element_key}]"""
        _log(f"打开列表页 {LIST_URL}")
        self.page.goto(LIST_URL, wait_until="networkidle", timeout=60000)
        # 等卡片渲染出来，这是整页的锚点
        self.page.wait_for_selector("a[href*='/item/']", timeout=30000)
        self.page.wait_for_timeout(1500)

        raw = self.page.eval_on_selector_all("a[href*='/item/']", """
          els => els.map(e => {
            const card = e.querySelector('.catalogue-card');
            const starEl = card && card.querySelector('[class*="card-star-"]');
            const starMatch = starEl ? (starEl.className.match(/card-star-(\\d)/) || []) : [];
            const attrImg = card && card.querySelector('.card-skill-attr-icon img');
            const nameEl = card && card.querySelector('.card-footer span');
            const href = (e.getAttribute('href') || '').split('?')[0];
            return {
              href: href,
              name: nameEl ? nameEl.innerText.trim() : '',
              text: (e.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 40),
              rarity: starMatch[1] ? parseInt(starMatch[1], 10) : null,
              element_key: attrImg ? ((attrImg.src.match(/role-attr-([a-z]+)-/) || [])[1] || null) : null
            };
          })""")

        items, seen = [], set()
        for r in raw:
            item_id = r["href"].rstrip("/").split("/")[-1]
            if not item_id.isdigit() or item_id in seen:
                continue
            seen.add(item_id)
            name = r["name"] or r["text"].split(" ")[0]
            items.append({
                "name": name,
                "href": r["href"],
                "item_id": item_id,
                "rarity": r["rarity"],
                "element_key": r["element_key"],
            })

        _log(f"列表页解析到 {len(items)} 个角色")
        return items

    # -------------------------------------------------- 详情页

    def fetch_detail(self, item, retries=2):
        """
        打开详情页，提取 title 与 .role-tags。

        :return: 补全后的字典；失败返回 None
        """
        url = BASE_URL + item["href"]
        for attempt in range(retries + 1):
            try:
                self.page.goto(url, wait_until="networkidle", timeout=60000)
                # 有的页面 .role-tags 在首屏就有；等不到就退回用 title
                try:
                    self.page.wait_for_selector(".role-tags", timeout=12000)
                except Exception:
                    pass

                tags = self.page.eval_on_selector_all(
                    ".role-tags .text-ellipsis",
                    "els => els.map(e => (e.innerText || '').trim())")

                fields = {}
                for t in tags:
                    m = re.match(r"^(.{2,4})[：:]\s*(.+)$", t)
                    if m:
                        fields[m.group(1)] = m.group(2).strip()

                title = self.page.title().split("-")[0].strip()
                result = dict(item)
                result.update({
                    "name_cn": fields.get("名称") or item["name"] or title,
                    "gender": fields.get("性别", ""),
                    "birthplace": fields.get("出生", "") or fields.get("阵营", ""),
                    "weapon_cn": fields.get("武器", ""),
                    "element_cn": fields.get("属性", ""),
                    "url": url,
                })
                return result

            except Exception as e:
                if attempt < retries:
                    _log(f"  重试 {item['name']}（{type(e).__name__}: {e}）")
                    time.sleep(2 + attempt * 2)
                else:
                    _log(f"  放弃 {item['name']}：{type(e).__name__}: {e}")
                    return None


# ============================================================ 后处理

def normalize(rec):
    """把抓来的原始字段补成项目能直接用的形式。"""
    weapon_cn = rec.get("weapon_cn", "")
    element_cn = rec.get("element_cn", "")

    ew = WEAPON_MAP.get(weapon_cn)
    if not ew and weapon_cn:
        _log(f"  ⚠ 未登记的武器类型：{weapon_cn}（{rec.get('name_cn')}），"
             f"请在 WEAPON_MAP 里补上")
    el = ELEMENT_MAP.get(element_cn)
    element_en = el[1] if el else None
    element_key = el[0] if el else rec.get("element_key")

    rec.update({
        "weapon_en": ew,
        "element_en": element_en,
        "element_key": element_key,
        "scraped_at": datetime.now().isoformat(timespec="seconds"),
    })
    return rec


def build_name_map(characters):
    """
    生成/更新"中文名 → 英文名"对照表。

    已有文件里的值优先（人工填过的不能被覆盖），只补空缺。
    """
    existing = _load_json(_NAME_MAP_PATH, {})
    merged = dict(SEED_NAME_MAP)
    merged.update({k: v for k, v in existing.items() if v})

    for name_cn in characters:
        merged.setdefault(name_cn, "")

    # 顺便看看 assets 里有哪些英文目录还没被任何中文名认领
    chars_dir = _ROOT / "assets" / "characters"
    known_en = {v for v in merged.values() if v}
    orphan_dirs = []
    if chars_dir.is_dir():
        for d in sorted(os.listdir(chars_dir)):
            if not os.path.isdir(chars_dir / d) or d == "_general":
                continue
            if d not in known_en:
                orphan_dirs.append(d)

    _save_json(_NAME_MAP_PATH, merged)
    return merged, orphan_dirs


def _read_existing_occupation():
    """
    读现有的 Character_Occupation.txt，返回 {英文名: 武器}。

    为什么需要它：爬虫拿到的英文名目前只有 8 个种子，直接覆盖会把
    手工维护过、但暂时对不上中文名的条目冲掉。合并才是安全的。
    """
    existing = {}
    if not _OCCUPATION_PATH.exists():
        return existing
    for line in _OCCUPATION_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() and v.strip():
            existing[k.strip()] = v.strip()
    return existing


def write_occupation(characters, name_map):
    """
    生成 Character_Occupation.txt。

    格式：`角色英文名=武器类型`。

    **合并而不是覆盖**：以现有文件为基线，爬到的数据只补/改对得上的条目。
    这样即使某个角色的英文名还没填，它原来手工维护的映射也不会丢。
    """
    baseline = _read_existing_occupation()
    merged = dict(baseline)

    written, updated, skipped = 0, [], []
    for name_cn, rec in sorted(characters.items()):
        en = name_map.get(name_cn) or ""
        weapon = rec.get("weapon_en") or ""
        if not (en and weapon):
            reason = "缺英文名" if not en else "缺武器类型"
            skipped.append(f"#   {name_cn}  ({weapon or '未知武器'})  —— {reason}")
            continue
        if en in merged and merged[en] != weapon:
            updated.append(f"#   {en}: {merged[en]} -> {weapon}  ({name_cn})")
        if en not in merged:
            written += 1
        merged[en] = weapon

    lines = [
        "# 角色 → 武器类型映射",
        "# 由 tools/factory/wiki_spider.py --occupation 生成（与原有条目合并）",
        "# 用途：普攻/重击在角色专属目录找不到图时，按武器类型落到",
        "#       assets/characters/_general/normal_attack/<武器>/",
        f"# 生成时间：{datetime.now():%Y-%m-%d %H:%M}",
        "",
    ]
    for en in sorted(merged):
        lines.append(f"{en}={merged[en]}")

    if updated:
        lines += ["", "# ---- 以下条目的武器类型被更新，请确认无误 ----"] + updated
    if skipped:
        lines += ["", "# ---- 以下角色未能写入，补全 db/name_map.json 后重跑 ----"] + skipped

    _OCCUPATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OCCUPATION_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(merged), written, updated, skipped


# ============================================================ 主流程

def main():
    ap = argparse.ArgumentParser(description="库街区鸣潮 wiki 角色数据爬虫")
    ap.add_argument("--limit", type=int, default=0, help="只抓前 N 个角色（调试用）")
    ap.add_argument("--force", action="store_true", help="忽略已有数据，全部重抓")
    ap.add_argument("--headful", action="store_true", help="显示浏览器窗口")
    ap.add_argument("--occupation", action="store_true",
                    help="爬完后生成 Character_Occupation.txt")
    ap.add_argument("--name-map", action="store_true", help="只生成中英文名对照表骨架")
    args = ap.parse_args()

    _DB_DIR.mkdir(parents=True, exist_ok=True)
    characters = {} if args.force else _load_json(_AGG_PATH, {})
    if characters:
        _log(f"已有 {len(characters)} 个角色的数据，跳过它们（--force 重抓）")

    if args.name_map:
        # 不联网，纯粹给已有数据建表
        merged, orphans = build_name_map(characters)
        _log(f"已写入 {_NAME_MAP_PATH}（{len(merged)} 条）")
        if orphans:
            _log(f"assets 里还有 {len(orphans)} 个英文目录没对上中文名："
                 f"{', '.join(orphans[:10])}{' …' if len(orphans) > 10 else ''}")
        return 0

    try:
        with WikiSpider(headful=args.headful) as spider:
            index = spider.fetch_index()
            if args.limit:
                index = index[:args.limit]

            todo = [it for it in index if it["name"] not in characters]
            _log(f"待抓取 {len(todo)} 个（总 {len(index)}）")

            for i, item in enumerate(todo, 1):
                _log(f"[{i}/{len(todo)}] {item['name']}")
                detail = spider.fetch_detail(item)
                if not detail:
                    continue
                rec = normalize(detail)
                characters[rec["name_cn"]] = rec

                # 每抓一个就落盘：中断了不用从头再来
                _save_json(_AGG_PATH, characters)
                _sleep()
    except ImportError:
        _log("缺少 playwright，请先运行：pip install playwright && playwright install chromium")
        return 1
    except KeyboardInterrupt:
        _log("手动中断，已抓到的数据已保存")
    except Exception as e:
        _log(f"运行异常：{type(e).__name__}: {e}")
        return 1

    if not characters:
        _log("没有抓到任何数据")
        return 1

    # ---- 收尾：整理 + 报告 ----
    name_map, orphans = build_name_map(characters)

    missing_weapon = [n for n, r in characters.items() if not r.get("weapon_en")]
    missing_en = [n for n in characters if not name_map.get(n)]

    print()
    print("=" * 64)
    _log(f"共 {len(characters)} 个角色，数据保存在 {_AGG_PATH}")
    if missing_weapon:
        _log(f"⚠ {len(missing_weapon)} 个角色没抓到武器类型：{', '.join(missing_weapon[:8])}")
    if missing_en:
        _log(f"ℹ {len(missing_en)} 个角色还没有英文名，补 {_NAME_MAP_PATH.name} 后重跑")
    if orphans:
        _log(f"ℹ assets 里 {len(orphans)} 个目录没对上中文名："
             f"{', '.join(orphans[:8])}{' …' if len(orphans) > 8 else ''}")

    if args.occupation:
        total, added, updated, skipped = write_occupation(characters, name_map)
        _log(f"已写入 {_OCCUPATION_PATH}：共 {total} 条（新增 {added}，更新 {len(updated)}）")
        if updated:
            _log(f"  {len(updated)} 条武器类型发生了变化，文件末尾有明细，请确认")
        if skipped:
            _log(f"  {len(skipped)} 个角色因缺英文名/武器未写入（文件末尾有注释）")
    else:
        _log("想生成 Character_Occupation.txt，重跑时加 --occupation")

    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
