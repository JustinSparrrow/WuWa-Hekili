"""
素材目录脚手架：批量建立 / 清理角色素材目录结构。

为什么需要它
------------
`assets/characters/` 下原本有 45 个角色目录、每个 9 个标准子目录，共 405 个。
但实际只有 8 个角色有素材（合计 102 张 png），也就是说 **349 个子目录是空的**。

空目录有两个坏处：
  1. 看起来"支持 45 个角色"，实际只支持 8 个，判断全靠肉眼数图
  2. 素材查找要多扫一堆不存在的目录

所以这里提供两个对称的能力：
  - `create`  新角色要做素材时，一键铺好标准结构（不用手工建 9 个文件夹）
  - `prune`   清理空目录，让"有素材的角色"一眼可见

用法
----
    python tools/scaffold.py --list                # 看看现状
    python tools/scaffold.py --create Aemeath      # 给某个角色铺目录
    python tools/scaffold.py --create-all          # 给所有已知角色铺目录
    python tools/scaffold.py --prune               # 删掉所有空子目录 / 空角色目录

`--prune` 只删**完全空**的目录，任何一个目录里有文件都不动，可以放心跑。
"""

import argparse
import os
import sys

# 独立运行：就地向上找到项目根（含 main.py）并加入 import 路径，再复用统一根查找。
_root = os.path.abspath(__file__)
while True:
    _root = os.path.dirname(_root)
    if os.path.exists(os.path.join(_root, "main.py")) or _root == os.path.dirname(_root):
        break
sys.path.insert(0, _root)

from utils.paths import project_root  # noqa: E402

ROOT = str(project_root())
CHARS_DIR = os.path.join(ROOT, "assets", "characters")

# 标准子目录。顺序即"素材工坊"里 1-8 号键的顺序，改这里要同步 ui/asset_factory.py 的 CATEGORIES
STANDARD_SUBS = [
    "normal_attack",
    "jump",
    "resonance_skill",
    "resonance_liberation",
    "echo",
    "character",
    "forte_circuit",
    "concerto_energy",
    "energy_bar",
]

# 鸣潮当前已知角色（英文名 = 目录名）。新增角色往这里加一行即可。
KNOWN_CHARS = [
    "Aalto", "Aemeath", "Augusta", "Baizhi", "Brant", "Buling",
    "Calcharo", "Camellya", "Cantarella", "Carlotta", "Cartethyia",
    "Changli", "Chisa", "Chixia", "Ciaccona",
    "Danjin", "Encore",
    "Galbrena",
    "Jianxin", "Jinhsi", "Jiyan",
    "Lingyang", "Lumi", "Lupa", "Luuk Herssen", "Lynae",
    "Mornye", "Mortefi",
    "Phoebe", "Phrolova",
    "Qiuyuan",
    "Roccia", "Rover",
    "Sanhua", "Shorekeeper",
    "Taoqi",
    "Verina",
    "Xiangli Yao",
    "Yangyang", "Yinlin", "Youhu", "Yuanwu",
    "Zani", "ZheZhi", "luno",
]

GENERAL_DIR = "_general"


def _png_count(directory):
    """统计目录下（含一层子目录）的 png 数量。"""
    total = 0
    for root, _dirs, files in os.walk(directory):
        total += sum(1 for f in files if f.lower().endswith(".png"))
    return total


def _char_dirs():
    if not os.path.isdir(CHARS_DIR):
        return []
    return sorted(d for d in os.listdir(CHARS_DIR)
                  if os.path.isdir(os.path.join(CHARS_DIR, d)) and d != GENERAL_DIR)


def cmd_list():
    chars = _char_dirs()
    if not chars:
        print(f"没有找到角色目录：{CHARS_DIR}")
        return 0

    have, empty = [], []
    total_png = 0
    for c in chars:
        n = _png_count(os.path.join(CHARS_DIR, c))
        total_png += n
        (have if n else empty).append((c, n))

    print(f"素材根目录：{CHARS_DIR}")
    print(f"角色目录 {len(chars)} 个，png 合计 {total_png} 张\n")

    print(f"有素材（{len(have)} 个）：")
    for c, n in sorted(have, key=lambda kv: -kv[1]):
        print(f"  {c:20s} {n:3d} 张")
    if empty:
        print(f"\n空壳（{len(empty)} 个）：")
        print("  " + ", ".join(c for c, _ in empty))

    empty_subs = sum(
        1 for c in chars
        for s in STANDARD_SUBS
        if os.path.isdir(os.path.join(CHARS_DIR, c, s)) and _png_count(os.path.join(CHARS_DIR, c, s)) == 0
    )
    print(f"\n空子目录：约 {empty_subs} 个（可用 --prune 清理）")
    return 0


def cmd_create(char_name):
    target = os.path.join(CHARS_DIR, char_name)
    created = 0
    for sub in STANDARD_SUBS:
        path = os.path.join(target, sub)
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            created += 1
    print(f"{char_name}: 新建 {created} 个目录，已就绪 {len(STANDARD_SUBS)} 个")
    print(f"  路径 {target}")
    print("  下一步：把该角色的图标按 kebab 命名放进去，"
          "或用 tools/factory/asset_factory_gui.py 从录像批量裁切")
    return 0


def cmd_create_all():
    missing = [c for c in KNOWN_CHARS if not os.path.isdir(os.path.join(CHARS_DIR, c))]
    for c in missing:
        os.makedirs(os.path.join(CHARS_DIR, c), exist_ok=True)
    for c in KNOWN_CHARS:
        target = os.path.join(CHARS_DIR, c)
        for sub in STANDARD_SUBS:
            os.makedirs(os.path.join(target, sub), exist_ok=True)
    print(f"已为 {len(KNOWN_CHARS)} 个角色铺好标准结构"
          f"（其中 {len(missing)} 个是新建的）")
    return 0


def cmd_prune(dry_run=False):
    """
    删除空目录。**只删完全空的**：任何一层有文件都跳过。

    :param dry_run: 只打印不删除
    """
    removed_subs = 0
    removed_chars = 0

    for char in _char_dirs():
        char_path = os.path.join(CHARS_DIR, char)
        for sub in os.listdir(char_path):
            sub_path = os.path.join(char_path, sub)
            if not os.path.isdir(sub_path):
                continue
            if os.listdir(sub_path):      # 非空，保留
                continue
            if not dry_run:
                os.rmdir(sub_path)
            removed_subs += 1
            print(f"  {'[预演] ' if dry_run else ''}删除空子目录 {char}/{sub}")

        # 角色目录本身也空了
        if not os.listdir(char_path):
            if not dry_run:
                os.rmdir(char_path)
            removed_chars += 1
            print(f"  {'[预演] ' if dry_run else ''}删除空角色目录 {char}")

    print(f"\n共 {'将' if dry_run else '已'}删除 {removed_subs} 个子目录、"
          f"{removed_chars} 个空角色目录")
    if dry_run:
        print("加 --prune 直接执行；想恢复用 --create-all")
    return 0


def main():
    ap = argparse.ArgumentParser(description="素材目录脚手架")
    ap.add_argument("--list", action="store_true", help="查看现状")
    ap.add_argument("--create", metavar="角色", help="给指定角色铺标准子目录")
    ap.add_argument("--create-all", action="store_true", help="给所有已知角色铺标准子目录")
    ap.add_argument("--prune", action="store_true", help="删除所有空目录")
    ap.add_argument("--dry-run", action="store_true", help="配合 --prune，只预演不删除")
    args = ap.parse_args()

    if not os.path.isdir(CHARS_DIR):
        print(f"素材目录不存在：{CHARS_DIR}")
        return 1

    if args.list or not any([args.create, args.create_all, args.prune]):
        return cmd_list()
    if args.create:
        return cmd_create(args.create)
    if args.create_all:
        return cmd_create_all()
    if args.prune:
        return cmd_prune(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
