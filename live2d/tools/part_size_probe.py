# -*- coding: utf-8 -*-
r"""List the largest parts (bbox area) of a character with kind/sprite info."""
import sys
from pathlib import Path

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
    rows = []
    for p in parts:
        if not (p.mesh or {}).get("positions"):
            continue
        v = _skin_mesh(p, p.mesh, w)
        if not v:
            continue
        xs = [a[0] for a in v]; ys = [a[1] for a in v]
        area = (max(xs) - min(xs)) * (max(ys) - min(ys))
        sp = p.sprite or {}
        rows.append((area, p.name, p.kind, len(v),
                     min(xs), max(xs), min(ys), max(ys),
                     bool(p.flip_x), bool(p.flip_y),
                     sp.get("drawMode"), sp.get("rect"), sp.get("pixelsToUnits")))
    rows.sort(reverse=True)
    print(f"{name}: parts={len(rows)}")
    for r in rows[:10]:
        print(f"  area={r[0]:8.2f} {r[1][:34]:34s} {r[2]:7s} n={r[3]:4d} "
              f"x=[{r[4]:6.2f},{r[5]:6.2f}] y=[{r[6]:6.2f},{r[7]:6.2f}] "
              f"flip={r[8]},{r[9]} mode={r[10]} ppu={r[12]}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_BR_PoniesAnger_NS1")
