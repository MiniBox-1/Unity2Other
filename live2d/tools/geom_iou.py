# -*- coding: utf-8 -*-
r"""Direct geometry IoU: our moc3 drawable triangles vs Unity-baked triangles."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity2live2d.moc3 import CubismCore  # noqa: E402

REF = ROOT / "Products" / "_unity_ref"
SIZE = 512


def raster(tris_pts, tris_idx):
    """tris_pts: list of (x,y) already normalized to 0..1 (y up)."""
    img = Image.new("L", (SIZE, SIZE), 0)
    d = ImageDraw.Draw(img)
    for t in range(0, len(tris_idx) - 2, 3):
        a, b, c = tris_idx[t], tris_idx[t + 1], tris_idx[t + 2]
        if max(a, b, c) >= len(tris_pts):
            continue
        pts = [(tris_pts[a][0] * SIZE, (1 - tris_pts[a][1]) * SIZE),
               (tris_pts[b][0] * SIZE, (1 - tris_pts[b][1]) * SIZE),
               (tris_pts[c][0] * SIZE, (1 - tris_pts[c][1]) * SIZE)]
        d.polygon(pts, fill=255)
    return np.array(img) > 0


def norm(pts, k=5.0):
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    mx, my = np.median(xs), np.median(ys)
    madx = max(1e-6, np.median(np.abs(xs - mx)) * 1.4826)
    mady = max(1e-6, np.median(np.abs(ys - my)) * 1.4826)
    keep = (np.abs(xs - mx) <= k * madx) & (np.abs(ys - my) <= k * mady)
    x0, x1 = xs[keep].min(), xs[keep].max()
    y0, y1 = ys[keep].min(), ys[keep].max()
    w = max(1e-9, x1 - x0)
    h = max(1e-9, y1 - y0)
    s = 1.0 / max(w, h)
    ox = (1 - w * s) / 2
    oy = (1 - h * s) / 2
    return [((p[0] - x0) * s + ox, (p[1] - y0) * s + oy) for p in pts]


def main(name):
    pkg = ROOT / "Products" / name
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())

    # 收集我们所有 drawable 的三角形
    ours_pts, ours_idx = [], []
    for i in range(len(model.drawable_ids())):
        v = model.vertices(i)
        t = model.indices(i)
        base = len(ours_pts)
        ours_pts.extend(v)
        ours_idx.extend([base + x for x in t])

    bake = json.loads((REF / f"{name}.bake.json").read_text(encoding="utf-8"))["parts"]
    ref_pts, ref_idx = [], []
    for p in bake:
        vs = [(p["verts"][j], p["verts"][j + 1]) for j in range(0, len(p["verts"]), 2)]
        base = len(ref_pts)
        ref_pts.extend(vs)
        ref_idx.extend([base + x for x in p["tris"]])

    a = raster(norm(ours_pts), ours_idx)
    b = raster(norm(ref_pts), ref_idx)
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    print(f"{name}: geometry IoU = {inter / max(1, union):.3f} "
          f"(ours px {a.sum()}, unity px {b.sum()})")
    Image.fromarray((a * 255).astype(np.uint8)).save(ROOT / "Products" / "_geo_ours.png")
    Image.fromarray((b * 255).astype(np.uint8)).save(ROOT / "Products" / "_geo_unity.png")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_BR_Khan_N")
