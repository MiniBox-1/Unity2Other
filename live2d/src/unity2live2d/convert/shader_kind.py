# -*- coding: utf-8 -*-
"""从 prefab + 材质资源判断部件的 shader 类型（不依赖任何 Unity 运行时/真值）。

做法：
1. 部件对象带材质 GUID（库已解析）；
2. 用 Assets 下 `.meta` 建 GUID → 资源 的索引（进程内缓存）；
3. 读 `.mat` 的 `m_Shader: {fileID, guid}`；
4. 查内置 shader id 常量表 `unity_shader_ids.json`（一次性学习、与角色无关）。

moc3 v1 只有普通 alpha 混合，粒子/叠加/正片叠底类 shader 无法表达，
因此在转换时跳过这些部件。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Tuple

TABLE_PATH = Path(__file__).with_name("unity_shader_ids.json")

GUID_RE = re.compile(r"guid:\s*([0-9a-f]{32})")
SHADER_RE = re.compile(r"m_Shader:\s*\{fileID:\s*(-?\d+),\s*guid:\s*([0-9a-f]{32})")

EFFECT_KEYWORDS = ("Particles/Additive", "Particles/Multiply",
                   "Particles/Alpha Blended", "Mobile/Particles")


@lru_cache(maxsize=8)
def _table() -> Dict[str, str]:
    if not TABLE_PATH.exists():
        return {}
    data = json.loads(TABLE_PATH.read_text(encoding="utf-8-sig"))
    return {k: v["shader"] if isinstance(v, dict) else v for k, v in data.items()}


@lru_cache(maxsize=4)
def _meta_index(assets_root: str) -> Dict[str, Path]:
    root = Path(assets_root)
    out: Dict[str, Path] = {}
    for meta in root.rglob("*.meta"):
        try:
            txt = meta.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        m = GUID_RE.search(txt)
        if m:
            out.setdefault(m.group(1), meta.with_name(meta.name[:-5]))
    return out


def shader_of_material(mat_path: Path) -> Optional[str]:
    try:
        txt = mat_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    m = SHADER_RE.search(txt)
    if not m:
        return None
    return _table().get(f"{m.group(1)}|{m.group(2)}")


def is_effect_part(part, assets_root: str) -> bool:
    """该部件的材质是否使用了 moc3 v1 无法表达的特效 shader。"""
    mats = getattr(part, "materials", None) or []
    if not mats:
        return False
    idx = _meta_index(str(assets_root))
    for g in mats:
        p = idx.get(g)
        if p is None or not p.exists():
            continue
        sh = shader_of_material(p) or ""
        if any(k.lower() in sh.lower() for k in EFFECT_KEYWORDS):
            return True
    return False
