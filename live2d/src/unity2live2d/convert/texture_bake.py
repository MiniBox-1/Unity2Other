# -*- coding: utf-8 -*-
"""把「叠加/正片叠底」特效件烘焙成普通 alpha 贴图。

moc3 v1 只有普通 alpha 混合；这类部件的贴图往往是 **alpha=0 但 RGB 很亮**
（Unity 用 `Blend One One` 直接加色），按普通混合画出来就完全不可见。

烘焙做法（每个特效件只改它自己在图集里的矩形，互不重叠）：
- `alpha_new = clamp(max(rgb)/255 * boost)`；RGB 保持不变（直通 alpha）；
- 这样普通「over」混合近似原来的加色发光，且能被 moc3 v1 表达。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np
from PIL import Image


@dataclass
class BakeRect:
    page: int
    u0: float
    v0: float
    u1: float
    v1: float
    boost: float = 1.0


def bake_pages(pages: List[Path], rects: List[BakeRect]) -> int:
    """按页烘焙；返回实际烘焙的矩形数。"""
    by_page = {}
    for r in rects:
        by_page.setdefault(r.page, []).append(r)
    done = 0
    for idx, rs in by_page.items():
        if idx >= len(pages) or not pages[idx].exists():
            continue
        img = Image.open(pages[idx]).convert("RGBA")
        arr = np.asarray(img).astype(np.float32)
        h, w = arr.shape[:2]
        touched = False
        for r in rs:
            x0 = int(np.clip(round(r.u0 * w), 0, w - 1))
            x1 = int(np.clip(round(r.u1 * w), 0, w - 1))
            cands = []
            for flip in (True, False):
                y0 = int(np.clip(round(((1.0 - r.v1) if flip else r.v0) * h), 0, h - 1))
                y1 = int(np.clip(round(((1.0 - r.v0) if flip else r.v1) * h), 0, h - 1))
                if y1 <= y0 or x1 <= x0:
                    continue
                cands.append((float(arr[y0:y1 + 1, x0:x1 + 1, :3].sum()), y0, y1))
            if not cands:
                continue
            # 选「RGB 能量更高」的那一侧：真正的美术/发光在那儿
            cands.sort(reverse=True)
            _, y0, y1 = cands[0]
            if x1 <= x0 or y1 <= y0:
                continue
            sub = arr[y0:y1 + 1, x0:x1 + 1]
            rgb = sub[:, :, :3]
            a_old = sub[:, :, 3] / 255.0
            lum = rgb.max(axis=2) / 255.0 * r.boost
            a_new = np.clip(np.maximum(a_old, lum), 0.0, 1.0)
            sub[:, :, 3] = a_new * 255.0
            arr[y0:y1 + 1, x0:x1 + 1] = sub
            touched = True
            done += 1
        if touched:
            Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA").save(pages[idx])
    return done
