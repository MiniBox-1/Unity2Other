# -*- coding: utf-8 -*-
r"""Quantify vertex outliers (stray geometry far from the main cluster)."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model)

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")


def main(name):
    mdl, parts = build_character_model(
        str(PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"), str(PROJ / "Assets"))
    w = _world_matrices(mdl, {})
    xs, ys = [], []
    per_part = []
    for p in parts:
        if not (p.mesh or {}).get("positions"):
            continue
        v = _skin_mesh(p, p.mesh, w)
        if not v:
            continue
        pxs = [a[0] for a in v]; pys = [a[1] for a in v]
        xs += pxs; ys += pys
        per_part.append((p.name, len(v), min(pxs), max(pxs), min(pys), max(pys)))
    x = np.array(xs); y = np.array(ys)
    print(f"{name}: verts={len(x)}")
    print(f"  x min/max={x.min():.2f}/{x.max():.2f}  p1/p99={np.percentile(x,1):.2f}/{np.percentile(x,99):.2f}")
    print(f"  y min/max={y.min():.2f}/{y.max():.2f}  p1/p99={np.percentile(y,1):.2f}/{np.percentile(y,99):.2f}")
    cx, cy = np.median(x), np.median(y)
    d = np.hypot(x - cx, y - cy)
    print(f"  median dist={np.median(d):.2f} p99={np.percentile(d,99):.2f} max={d.max():.2f}")
    # parts whose bbox is far from median
    far = [pp for pp in per_part
           if max(abs(pp[2] - cx), abs(pp[3] - cx), abs(pp[4] - cy), abs(pp[5] - cy)) > 3 * np.percentile(d, 90)]
    print(f"  far parts: {len(far)}")
    for pp in far[:6]:
        print(f"    {pp[0][:36]:36s} n={pp[1]:4d} bbox=({pp[2]:.1f},{pp[3]:.1f},{pp[4]:.1f},{pp[5]:.1f})")


if __name__ == "__main__":
    for n in sys.argv[1:]:
        main(n)
