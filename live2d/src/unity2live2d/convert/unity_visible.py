# -*- coding: utf-8 -*-
"""使用 Unity 真值（skinbounds dump）里「实际可见的部件名」来裁剪部件集合。

Unity 的自然状态渲染只画 activeInHierarchy 且 renderer.enabled 的物体；
我们按 prefab YAML 推断时容易多画（烟雾/涂鸦等特效件）或少画（被我们误判
为 disabled 的道具）。这里直接用 Unity 侧真实可见列表做对齐。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Set

REF = Path(__file__).resolve().parents[3] / "Products" / "_unity_ref"


def visible_names(name: str) -> Set[str]:
    f = REF / f"{name}.skinbounds.json"
    if not f.exists():
        return set()
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return set()
    return {p["name"] for p in data.get("parts", []) if p.get("name")}


_EFFECT_SHADERS = ("Particles/Additive", "Particles/Multiply",
                   "Particles/Alpha Blended", "Mobile/Particles")


def effect_parts(name: str) -> Set[str]:
    """Unity 里使用粒子/叠加/正片叠底 shader 的部件名。

    moc3 v1 只有普通 alpha 混合，这些特效件无法表达（画成普通混合会变成
    暗块或亮块），因此转换时直接跳过。
    """
    f = REF / f"{name}.mats.json"
    if not f.exists():
        return set()
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return set()
    out = set()
    for p in data.get("parts", []):
        sh = p.get("shader") or ""
        if any(k.lower() in sh.lower() for k in _EFFECT_SHADERS):
            out.add(p["name"])
    return out


def _exempt(name: str) -> bool:
    """`Products\\_nouni.txt` 里的角色跳过可见性裁剪（该裁剪对它们有害）。"""
    f = REF.parent / "_nouni.txt"
    if not f.exists():
        return False
    try:
        names = {x.strip() for x in f.read_text(encoding="utf-8-sig").splitlines() if x.strip()}
    except Exception:
        return False
    return name in names


def filter_parts(parts, name: str, min_cover: float = 0.5):
    """只保留 Unity 里真实可见的部件；覆盖率太低时不裁剪（避免参照缺失误删）。"""
    vis = visible_names(name)
    if not vis or not parts or _exempt(name):
        return parts, 0

    def hit(pname: str) -> bool:
        for v in vis:
            if pname == v or pname.startswith(v + "_"):
                return True
        return False

    kept = [p for p in parts if hit(p.name)]
    if len(kept) < min_cover * len(parts) or not kept:
        return parts, 0
    return kept, len(parts) - len(kept)
