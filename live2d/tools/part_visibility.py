# -*- coding: utf-8 -*-
r"""Decide per-part visibility by comparing our render with Unity's natural snapshot.

For each drawable of our model we rasterize its triangles, map our canvas onto the
Unity snapshot (content-bbox alignment) and measure what fraction of its pixels
land on non-transparent Unity pixels. Parts far below the model median are 'extra'.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity2live2d.moc3 import CubismCore  # noqa: E402

REF = ROOT / "Products" / "_unity_ref_nat"


def raster_model(model, height=512):
    """Return (id_map, canvas_box) with drawable index per pixel."""
    w, h, ox, oy, ppu = model.canvas()
    s = height / h
    W = max(1, int(round(w * s)))
    H = height
    img = Image.new("I", (W, H), -1)
    d = ImageDraw.Draw(img)
    for i in range(len(model.drawable_ids())):
        v = model.vertices(i)
        idx = model.indices(i)
        pts = [((x * ppu + ox) * s, H - (y * ppu + oy) * s) for x, y in v]
        for t in range(0, len(idx) - 2, 3):
            a, b, c = idx[t], idx[t + 1], idx[t + 2]
            if max(a, b, c) >= len(pts):
                continue
            d.polygon([pts[a], pts[b], pts[c]], fill=i)
    return np.array(img), (W, H)


def unity_mask(name, size):
    p = REF / f"{name}.png"
    im = Image.open(p).convert("RGBA")
    a = np.array(im)[:, :, 3] > 8
    ys, xs = np.where(a)
    if len(xs) == 0:
        return np.zeros(size[::-1], bool)
    sub = im.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)).resize(size, Image.LANCZOS)
    return np.array(sub)[:, :, 3] > 8


def main(name):
    pkg = ROOT / "Products" / name
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    idmap, size = raster_model(model)
    umask = unity_mask(name, size)

    ids = model.part_ids()
    stats = []
    for i in range(len(model.drawable_ids())):
        sel = idmap == i
        n = int(sel.sum())
        if n < 32:
            continue
        hit = float(umask[sel].mean())
        stats.append((hit, n, i, ids[i]))

    if not stats:
        return
    hits = np.array([s[0] for s in stats])
    med = float(np.median(hits))
    print(f"{name}: drawables={len(stats)} median_hit={med:.3f}")
    extra = [s for s in stats if s[0] < 0.15 and s[1] > 0.005 * size[0] * size[1]]
    extra.sort()
    print(f"  suspicious (hit<0.15, large): {len(extra)}")
    for h, n, i, aid in extra[:8]:
        print(f"    hit={h:.2f} px={n:6d} #{i} {aid[:40]}")


if __name__ == "__main__":
    for n in sys.argv[1:] or ["2DModel_BR_WarWolf_NS1"]:
        main(n)
