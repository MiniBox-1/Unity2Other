# -*- coding: utf-8 -*-
r"""Check whether dumped per-part bounds line up with the rendered image."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RT = ROOT / "Products" / "_unity_rt"


def main(name):
    d = json.loads((RT / f"{name}.json").read_text(encoding="utf-8"))
    img = np.array(Image.open(RT / f"{name}.png").convert("RGBA"))
    H, W = img.shape[:2]
    a = img[:, :, 3] > 8
    xmin, xmax, ymin, ymax = d["xmin"], d["xmax"], d["ymin"], d["ymax"]

    def to_px(x, y):
        u = (x - xmin) / (xmax - xmin) * W
        v = H - (y - ymin) / (ymax - ymin) * H
        return u, v

    empty = 0
    total = 0
    worst = []
    for p in d["parts"]:
        u0, v1 = to_px(p["min"][0], p["min"][1])
        u1, v0 = to_px(p["max"][0], p["max"][1])
        u0, u1 = sorted((max(0, int(u0)), min(W - 1, int(u1))))
        v0, v1 = sorted((max(0, int(v0)), min(H - 1, int(v1))))
        if u1 <= u0 or v1 <= v0:
            continue
        sub = a[v0:v1 + 1, u0:u1 + 1]
        cov = float(sub.mean()) if sub.size else 0.0
        total += 1
        if cov < 0.05:
            empty += 1
            worst.append((cov, p["n"]))
    print(f"{name}: parts={total} 覆盖<5% 的部件: {empty}")
    for c, n in sorted(worst)[:8]:
        print(f"   {c:.2f}  {n[:40]}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_AGS_RheinRitter_NS1")
