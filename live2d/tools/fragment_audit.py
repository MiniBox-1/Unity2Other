# -*- coding: utf-8 -*-
r"""Detect highly fragmented silhouettes (scattered parts) in previews."""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = ROOT / "Products"


def label_components(mask):
    """4-连通标记（numpy 实现，避免依赖 scipy）。"""
    h, w = mask.shape
    lab = np.zeros((h, w), np.int32)
    cur = 0
    stack = []
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys, xs):
        if lab[y0, x0]:
            continue
        cur += 1
        stack.append((y0, x0))
        lab[y0, x0] = cur
        while stack:
            y, x = stack.pop()
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not lab[ny, nx]:
                    lab[ny, nx] = cur
                    stack.append((ny, nx))
    return lab, cur


def main(limit=12):
    rows = []
    for png in sorted(PRODUCTS.glob("*/preview.png")):
        a = np.array(Image.open(png).convert("RGBA"))[:, :, 3] > 8
        if a.sum() < 100:
            continue
        lab, n = label_components(a)
        areas = np.bincount(lab.ravel())[1:]
        big = areas[areas > max(60, 0.002 * a.sum())]
        total = a.sum()
        # 碎片度：大碎片数量 + 质心离散度
        cents = []
        for i in np.nonzero(areas > max(60, 0.002 * total))[0] + 1:
            ys, xs = np.nonzero(lab == i)
            cents.append((xs.mean(), ys.mean()))
        cents = np.array(cents) if cents else np.zeros((0, 2))
        spread = float(np.std(cents, axis=0).mean() / max(1, a.shape[0])) if len(cents) else 0.0
        rows.append((len(big), spread, png.parent.name, int(total)))
    rows.sort(key=lambda r: (-r[0], -r[1]))
    print(f"models={len(rows)}")
    for r in rows[:limit]:
        print(f"  comps={r[0]:3d} spread={r[1]:.3f} area={r[3]:6d}  {r[2]}")


if __name__ == "__main__":
    main()
