"""
角色元数据（元素 / 稀有度 / 中文名）查询。

数据来源是素材工厂生成的 `db_<中文名>.json`。UI 只用其中很小一部分：
悬浮窗头像圈的元素色、元素徽记。
**没有这份数据也必须能跑** —— 查不到就退回金色，绝不抛异常。

为什么单独一个模块而不是塞进 AssetManager
--------------------------------------
AssetManager 管的是"图从哪来"，这里是"角色是什么属性"。
以后接视觉识别 / 计时器 / 队伍分析都要用元素信息，
放在 utils 里谁都能拿，不必依赖素材目录的结构。
"""

from __future__ import annotations

import glob
import json
import os

from utils.logger import log
from utils.paths import project_root

# 素材工厂可能把 db 写在工具目录，也可能被搬进 configs。
# 两个位置都试一遍，谁在一就用谁。
_DB_DIR_CANDIDATES = (
    os.path.join("configs", "db", "characters"),
    os.path.join("tools", "factory", "db", "characters"),
)

_INDEX: dict | None = None      # 英文名 -> {cn, element, rarity, weapon}


def _load() -> dict:
    """第一次用到时扫一遍 db 目录，之后全部走内存。"""
    global _INDEX
    if _INDEX is not None:
        return _INDEX

    index: dict = {}
    root = str(project_root())

    for rel in _DB_DIR_CANDIDATES:
        folder = os.path.join(root, rel)
        if not os.path.isdir(folder):
            continue
        for path in glob.glob(os.path.join(folder, "db_*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            en = data.get("name_en")
            if not en:
                continue
            index[en] = {
                "cn": data.get("name", ""),
                "element": (data.get("element") or {}).get("en", ""),
                "element_cn": (data.get("element") or {}).get("cn", ""),
                "weapon": (data.get("weapon") or {}).get("en", ""),
                "rarity": data.get("rarity", 0),
            }
        if index:
            log.debug(f"角色元数据加载：{len(index)} 条（{rel}）")
            break

    _INDEX = index
    return _INDEX


def info(char_name: str | None) -> dict:
    """取一个角色的元数据；查不到返回空 dict。"""
    if not char_name:
        return {}
    return _load().get(char_name, {})


def element_of(char_name: str | None) -> str:
    """元素英文名（spectro/fusion/...）；查不到返回空串。"""
    return info(char_name).get("element", "")


def name_cn(char_name: str | None) -> str:
    """中文名；查不到就原样返回英文名。"""
    return info(char_name).get("cn", "") or (char_name or "")
