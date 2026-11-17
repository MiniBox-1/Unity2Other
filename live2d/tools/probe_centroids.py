# -*- coding: utf-8 -*-
r"""Compare mesh-local vs skinned centroids to spot extraction problems."""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model)

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
ASSETS = PROJ / "Assets"


def main(name):
    prefab = ASSETS / "Prefabs" / f"{name}.uAnim.prefab"
    mdl, parts = build_character_model(str(prefab), str(ASSETS))
    world = _world_matrices(mdl, {})
    rows = []
    for p in parts:
        mesh = p.mesh or {}
        if not mesh.get("positions"):
            continue
        v = [(a[0], a[1]) for a in _skin_mesh(p, mesh, world)]
        sx = sum(a[0] for a in v) / len(v)
        sy = sum(a[1] for a in v) / len(v)
        pos = mesh["positions"]
        lx = sum(a[0] for a in pos) / len(pos)
        ly = sum(a[1] for a in pos) / len(pos)
        rows.append((math.hypot(sx, sy), math.hypot(lx, ly), p.name,
                     lx, ly, sx, sy, len(v)))
    rows.sort(reverse=True)
    print(f"{'sk_d':>7} {'loc_d':>7}  {'part':40s} local -> skinned")
    for r in rows[:12]:
        print(f"{r[0]:7.2f} {r[1]:7.2f}  {r[2][:40]:40s} "
              f"({r[3]:6.2f},{r[4]:6.2f}) -> ({r[5]:6.2f},{r[6]:6.2f}) n={r[7]}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_ST_Tiamat_NS1")
