# -*- coding: utf-8 -*-
"""读取动画片段里对 GameObject 显隐（m_IsActive / activeSelf）的曲线。

这些 prefab 的多套变体是靠**动画**切换显隐的：YAML 里 m_IsActive 全是 1，
但默认状态在 t=0 把不需要的那几份设为 0。只读资源即可判定，不需要 Unity。
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Dict

KEY_RE = re.compile(r"time:\s*(-?[0-9.eE+]+)\s*\n\s*value:\s*(-?[0-9.eE+]+)")
PATH_RE = re.compile(r"^\s*path:\s*(.*)$", re.M)


def _split_curves(text: str):
    parts = re.split(r"^\s*-\s*curve:\s*$", text, flags=re.M)
    return parts[1:]


def inactive_names(clip_path: Path, t: float = 0.0) -> Dict[str, bool]:
    """返回 {物体名: 是否在 t 时刻隐藏}。"""
    try:
        text = Path(clip_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    out: Dict[str, bool] = {}
    for block in _split_curves(text):
        if "attribute: m_IsActive" not in block and "attribute: activeSelf" not in block:
            continue
        pm = PATH_RE.search(block)
        if not pm:
            continue
        path = pm.group(1).strip().strip("'\"")
        if not path:
            continue
        pts = []
        for a, b in KEY_RE.findall(block):
            try:
                tv, vv = float(a), float(b)
            except ValueError:
                continue
            if not (math.isnan(tv) or math.isinf(tv)):
                pts.append((tv, vv))
        if not pts:
            continue
        pts.sort()
        val = pts[0][1]
        for i in range(len(pts) - 1):
            t0, v0 = pts[i]
            t1, v1 = pts[i + 1]
            if t0 <= t <= t1:
                val = v0 if t1 <= t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
                break
            if t >= t1:
                val = v1
        out[path.split("/")[-1]] = val < 0.5
    return out
