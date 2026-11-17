# -*- coding: utf-8 -*-
r"""Flat-color render of a moc3 with drawable ids, plus per-drawable bbox report."""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from unity2live2d.moc3 import CubismCore  # noqa: E402

COLORS = [(220, 60, 60), (60, 120, 220), (60, 180, 90), (200, 160, 40),
          (160, 80, 200), (30, 160, 160), (230, 120, 30), (90, 90, 90),
          (200, 60, 160), (100, 160, 60), (60, 60, 200), (180, 100, 100)]


def main(model3: Path, out: Path, height=900):
    import json
    m3 = json.loads(model3.read_text(encoding="utf-8"))
    base = model3.parent
    core = CubismCore()
    model = core.load((base / m3["FileReferences"]["Moc"]).read_bytes())
    w, h, ox, oy, ppu = model.canvas()
    s = height / h
    W = int(w * s)
    img = Image.new("RGBA", (W, height), (255, 255, 255, 255))
    dr = ImageDraw.Draw(img)
    ids = model.drawable_ids()
    order = sorted(range(len(ids)), key=lambda i: model.drawable(i)["render_order"])
    rows = []
    for i in order:
        v = model.vertices(i)
        idx = model.indices(i)
        pts = [((x * ppu + ox) * s, height - (y * ppu + oy) * s) for x, y in v]
        col = COLORS[i % len(COLORS)]
        for t in range(0, len(idx) - 2, 3):
            a, b, c = idx[t], idx[t + 1], idx[t + 2]
            dr.polygon([pts[a], pts[b], pts[c]], fill=col + (255,))
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        rows.append(((max(xs) - min(xs)) * (max(ys) - min(ys)), i, ids[i],
                     min(xs), max(xs), min(ys), max(ys)))
    img.save(out)
    rows.sort(reverse=True)
    print(f"drawables={len(ids)}")
    for r in rows[:8]:
        print(f"  area={r[0]:9.0f} idx={r[1]:3d} {r[2][:44]:44s} "
              f"x=[{r[3]:6.0f},{r[4]:6.0f}] y=[{r[5]:6.0f},{r[6]:6.0f}]")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]),
         int(sys.argv[3]) if len(sys.argv) > 3 else 900)
