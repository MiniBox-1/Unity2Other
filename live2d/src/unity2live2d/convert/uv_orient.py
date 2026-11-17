# -*- coding: utf-8 -*-
"""用纹理自身判断 UV 的 V 朝向（不依赖任何 Unity 真值）。

对每个部件取若干 UV 采样点，比较两种取向下「采样点落在不透明像素上的比例」：
- A：`ty = (1 - v) * H`（当前存储约定，渲染器就是这么采样的）
- B：`ty = v * H`
如果 B 明显优于 A，说明该角色的源 UV 朝向与常规相反，需要整体翻一次。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Iterable, Tuple

import numpy as np
from PIL import Image


@lru_cache(maxsize=256)
def _alpha(path: str) -> np.ndarray | None:
    try:
        im = Image.open(path).convert("RGBA")
    except Exception:
        return None
    a = np.asarray(im)[:, :, 3]
    return a


def _flat_uv(mesh) -> list:
    raw = list(mesh.get("uvs") or [])
    if raw and isinstance(raw[0], (tuple, list)):
        return [c for uv in raw for c in uv]
    return list(raw)


def needs_flip(uv_flat, texture_path, grid: int = 6,
               max_raw: float = 0.02, min_flip: float = 0.25) -> bool:
    """保守判据：当前朝向几乎全透明、翻过来却明显有内容时才翻。

    只用于「位置对但采样到透明像素」的部件（例如 RheinRitter 的 Mesh 部件
    UV 朝向与常规相反），不会影响本来就正常的部件。
    """
    if not uv_flat or not texture_path or len(uv_flat) < 8:
        return False
    a = _alpha(str(texture_path))
    if a is None or a.size == 0:
        return False
    h, w = a.shape
    us = uv_flat[0::2]
    vs = uv_flat[1::2]
    u0, u1 = max(0.0, min(us)), min(1.0, max(us))
    v0, v1 = max(0.0, min(vs)), min(1.0, max(vs))
    if (u1 - u0) * (v1 - v0) < 0.0002:
        return False
    raw = flip = 0
    for i in range(grid):
        for j in range(grid):
            u = u0 + (u1 - u0) * (i + 0.5) / grid
            v = v0 + (v1 - v0) * (j + 0.5) / grid
            x = int(np.clip(u * w, 0, w - 1))
            raw += 1 if a[int(np.clip((1.0 - v) * h, 0, h - 1)), x] > 8 else 0
            flip += 1 if a[int(np.clip(v * h, 0, h - 1)), x] > 8 else 0
    n = grid * grid
    return (raw / n) < max_raw and (flip / n) > min_flip


def prefers_flip(uv_flat, texture_path, grid: int = 6, ratio: float = 1.3) -> bool:
    """单个部件：`1-v` 是否明显比 `v` 更贴合不透明区域（只用贴图判断）。"""
    if not uv_flat or not texture_path or len(uv_flat) < 8:
        return False
    a = _alpha(str(texture_path))
    if a is None or a.size == 0:
        return False
    h, w = a.shape
    us = uv_flat[0::2]
    vs = uv_flat[1::2]
    u0, u1 = max(0.0, min(us)), min(1.0, max(us))
    v0, v1 = max(0.0, min(vs)), min(1.0, max(vs))
    if (u1 - u0) * (v1 - v0) < 0.0005:
        return False
    raw = flip = 0.0
    for i in range(grid):
        for j in range(grid):
            u = u0 + (u1 - u0) * (i + 0.5) / grid
            v = v0 + (v1 - v0) * (j + 0.5) / grid
            x = int(np.clip(u * w, 0, w - 1))
            raw += 1.0 if a[int(np.clip((1.0 - v) * h, 0, h - 1)), x] > 8 else 0.0
            flip += 1.0 if a[int(np.clip(v * h, 0, h - 1)), x] > 8 else 0.0
    if raw + flip <= 0:
        return False
    return flip > raw * ratio


def decide_flip(parts, grid: int = 8, min_area: float = 0.002) -> Tuple[bool, float]:
    """返回 (是否需要整体翻 V, 置信度 0..1)。

    对每个部件取 UV 包围盒，在盒内均匀采样，统计「不透明比例」，两种朝向各算一次，
    按包围盒面积加权后比较。部件贴图是紧贴美术的，正确朝向的不透明比例明显更高。
    """
    score_raw = 0.0
    score_flip = 0.0
    for p in parts:
        mesh = p.mesh or {}
        uv = _flat_uv(mesh)
        tex = getattr(p, "texture_path", None)
        if not uv or not tex or len(uv) < 8:
            continue
        a = _alpha(str(tex))
        if a is None or a.size == 0:
            continue
        h, w = a.shape
        us = uv[0::2]
        vs = uv[1::2]
        u0, u1 = max(0.0, min(us)), min(1.0, max(us))
        v0, v1 = max(0.0, min(vs)), min(1.0, max(vs))
        if (u1 - u0) * (v1 - v0) < min_area:
            continue
        weight = (u1 - u0) * (v1 - v0)
        su = sv = 0.0
        cnt = 0
        for i in range(grid):
            for j in range(grid):
                u = u0 + (u1 - u0) * (i + 0.5) / grid
                v = v0 + (v1 - v0) * (j + 0.5) / grid
                x = int(np.clip(u * w, 0, w - 1))
                y_raw = int(np.clip((1.0 - v) * h, 0, h - 1))
                y_flip = int(np.clip(v * h, 0, h - 1))
                su += 1.0 if a[y_raw, x] > 8 else 0.0
                sv += 1.0 if a[y_flip, x] > 8 else 0.0
                cnt += 1
        if cnt:
            score_raw += weight * su / cnt
            score_flip += weight * sv / cnt
    total = score_raw + score_flip
    if total <= 0:
        return False, 0.0
    flip = score_flip > score_raw * 1.2
    conf = abs(score_flip - score_raw) / total
    return flip, conf
