# -*- coding: utf-8 -*-
r"""Test two readings of a Spine mesh: bone-transformed vs raw, compare bbox to ours."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from spine_preview import apply, bone_worlds, mesh_points  # noqa: E402
from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model)

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
SPINE = Path(r"D:\VB\Convert\Spine\MultiSpine\LO\Products\Current")


def bbox(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return (min(xs), max(xs), min(ys), max(ys))


def main(name, key):
    base = SPINE / f"{name}.uAnim"
    js = next(p for p in base.glob("*.json") if p.name.endswith("_static.json"))
    d = json.loads(js.read_text(encoding="utf-8"))
    world, order = bone_worlds(d)
    atts = d["skins"][0]["attachments"]
    att = None
    for slot, items in atts.items():
        if key in items:
            att = items[key]; break
    v = att["vertices"]
    # raw weighted sum without bone transforms
    raw = []
    i = 0
    while i < len(v):
        n = int(v[i]); i += 1
        px = py = 0.0
        for _ in range(n):
            x, y, w = v[i + 1], v[i + 2], v[i + 3]
            i += 4
            px += x * w; py += y * w
        raw.append((px, py))
    slot = next(s for s in d["slots"] if s["name"] == next(
        k for k, items in atts.items() if key in items))
    pts = mesh_points(att, world, order, slot.get("bone"))
    print("SPINE transformed bbox:", [round(x, 2) for x in bbox(pts)])
    print("SPINE raw         bbox:", [round(x, 2) for x in bbox(raw)])

    mdl, parts = build_character_model(
        str(PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"), str(PROJ / "Assets"))
    w = _world_matrices(mdl, {})
    for p in parts:
        if key in p.name:
            verts = _skin_mesh(p, p.mesh, w)
            b = bbox(verts)
            print("OURS  (×100)      bbox:", [round(x * 100, 2) for x in b])
            break


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
