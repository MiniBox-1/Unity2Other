# -*- coding: utf-8 -*-
r"""Audit: how many drawables sample a transparent texel at their UV centroid."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from unity2live2d.moc3 import CubismCore  # noqa: E402

PRODUCTS = ROOT / "Products"


def audit(model3_path: Path, core):
    m3 = json.loads(model3_path.read_text(encoding="utf-8"))
    base = model3_path.parent
    model = core.load((base / m3["FileReferences"]["Moc"]).read_bytes())
    if model is None:
        return None
    pages = []
    for t in m3["FileReferences"].get("Textures") or []:
        pages.append(np.array(Image.open(base / t).convert("RGBA"))[:, :, 3])
    if not pages:
        return None
    zero = 0
    n = len(model.drawable_ids())
    for i in range(n):
        uv = model.uvs(i)
        if not uv:
            continue
        cu = sum(a for a, b in uv) / len(uv)
        cv = sum(b for a, b in uv) / len(uv)
        tex_i = min(model.drawable(i)["texture"], len(pages) - 1)
        page = pages[tex_i]
        h, w = page.shape
        x = int(np.clip(cu * w, 0, w - 1))
        y = int(np.clip((1.0 - cv) * h, 0, h - 1))
        if page[y, x] == 0:
            zero += 1
    return zero, n


def main():
    core = CubismCore()
    rows = []
    for p in sorted(PRODUCTS.glob("*/[!_]*.model3.json")):
        r = audit(p, core)
        if r:
            rows.append((r[0] / max(1, r[1]), r[0], r[1], p.parent.name))
    rows.sort(reverse=True)
    print(f"models={len(rows)}")
    bad = [r for r in rows if r[0] > 0.3]
    print(f"models with >30% transparent-centroid drawables: {len(bad)}")
    for r in rows[:15]:
        print(f"  {r[0]:.2f} ({r[1]}/{r[2]})  {r[3]}")


if __name__ == "__main__":
    main()
