# -*- coding: utf-8 -*-
r"""Flag suspicious silhouettes (extreme aspect / low fill / tiny area)."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = ROOT / "Products"


def main():
    rows = []
    for png in sorted(PRODUCTS.glob("*/preview.png")):
        a = np.array(Image.open(png).convert("RGBA"))[:, :, 3] > 8
        if a.sum() == 0:
            rows.append((png.parent.name, 0, 0, 0))
            continue
        ys, xs = np.where(a)
        w = xs.max() - xs.min() + 1
        h = ys.max() - ys.min() + 1
        fill = a.sum() / max(1, w * h)
        aspect = w / max(1, h)
        rows.append((png.parent.name, round(aspect, 2), round(fill, 3), int(a.sum())))

    print(f"previews={len(rows)}")
    odd = [r for r in rows if r[1] > 3.5 or r[1] < 0.2 or r[2] < 0.12]
    print(f"suspicious={len(odd)}")
    for r in odd[:25]:
        print(f"  aspect={r[1]:5.2f} fill={r[2]:.3f} area={r[3]:6d}  {r[0]}")


if __name__ == "__main__":
    main()
