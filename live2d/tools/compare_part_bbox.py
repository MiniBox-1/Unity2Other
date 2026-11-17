# -*- coding: utf-8 -*-
r"""Compare one part's world bbox: Spine product vs Unity extraction."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from spine_preview import bone_worlds, mesh_points  # noqa: E402
from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model)

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
SPINE = Path(r"D:\VB\Convert\Spine\MultiSpine\LO\Products\Current")


def main(name: str, part_key: str):
    base = SPINE / f"{name}.uAnim"
    js = next(p for p in base.glob("*.json") if p.name.endswith("_static.json"))
    d = json.loads(js.read_text(encoding="utf-8"))
    world, order = bone_worlds(d)
    atts = d["skins"][0]["attachments"]
    found = None
    for slot, items in atts.items():
        for k, att in items.items():
            if part_key.lower() in k.lower():
                found = (slot, k, att)
                break
        if found:
            break
    if not found:
        raise SystemExit("part not found in spine")
    slot_name, key, att = found
    slot = next(s for s in d["slots"] if s["name"] == slot_name)
    pts = mesh_points(att, world, order, slot.get("bone"))
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    print(f"SPINE {key[:40]:40s} n={len(pts):4d} x=[{min(xs):8.2f},{max(xs):8.2f}] "
          f"y=[{min(ys):8.2f},{max(ys):8.2f}]")

    mdl, parts = build_character_model(
        str(PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"), str(PROJ / "Assets"))
    w = _world_matrices(mdl, {})
    for p in parts:
        if part_key.lower() in p.name.lower():
            v = _skin_mesh(p, p.mesh, w)
            xs = [a[0] for a in v]; ys = [a[1] for a in v]
            print(f"OURS  {p.name[:40]:40s} n={len(v):4d} "
                  f"x=[{min(xs) * 100:8.2f},{max(xs) * 100:8.2f}] "
                  f"y=[{min(ys) * 100:8.2f},{max(ys) * 100:8.2f}]  (×100)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
