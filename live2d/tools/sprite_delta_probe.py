# -*- coding: utf-8 -*-
r"""Per-part vertex delta between our extraction and the Spine product.

If the delta is constant per part, print it next to sprite pivot/offset so we can
see which pivot convention the Spine converter used.
"""
import json
import sys
from pathlib import Path

import numpy as np

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


def main(name: str):
    base = SPINE / f"{name}.uAnim"
    js = next(p for p in base.glob("*.json") if p.name.endswith("_static.json"))
    d = json.loads(js.read_text(encoding="utf-8"))
    world, order = bone_worlds(d)
    atts = d["skins"][0]["attachments"]
    slot_of = {s["name"]: s for s in d["slots"]}

    mdl, parts = build_character_model(
        str(PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"), str(PROJ / "Assets"))
    w = _world_matrices(mdl, {})
    ours = {p.name: p for p in parts}

    rows = []
    for slot_name, items in atts.items():
        for att_name, att in items.items():
            if att.get("type") != "mesh" or att_name not in ours:
                continue
            p = ours[att_name]
            if p.kind != "sprite":
                continue
            sv = mesh_points(att, world, order, slot_of[slot_name].get("bone"))
            ov = [(v[0] * 100, v[1] * 100) for v in _skin_mesh(p, p.mesh, w)]
            if len(sv) != len(ov):
                continue
            dv = np.array(sv) - np.array(ov)
            mean = dv.mean(axis=0)
            std = dv.std(axis=0)
            sp = p.sprite or {}
            rows.append((att_name, mean, std, sp.get("pivot"), sp.get("offset"),
                         sp.get("rect"), sp.get("pixelsToUnits")))

    print(f"matched sprite parts: {len(rows)}")
    rows.sort(key=lambda r: float(max(r[2])), reverse=True)
    print("--- 差异最大的 12 个（std 大 = 非纯平移）---")
    for r in rows[:12]:
        name_, mean, std, pivot, offset, rect, ppu = r
        print(f"{name_[:30]:30s} d=({mean[0]:7.2f},{mean[1]:7.2f}) "
              f"std=({std[0]:5.2f},{std[1]:5.2f}) pivot={pivot} off={offset}")
    print("--- 平移量统计 ---")
    consts = {}
    for name_, mean, std, *_ in rows:
        if float(max(std)) < 0.01:
            key = (round(float(mean[0]), 2), round(float(mean[1]), 2))
            consts[key] = consts.get(key, 0) + 1
    for k, v in sorted(consts.items(), key=lambda kv: -kv[1])[:6]:
        print(f"  delta={k}  parts={v}")
        name_, mean, std, pivot, offset, rect, ppu = r
        print(f"{name_[:30]:30s} d=({mean[0]:7.2f},{mean[1]:7.2f}) "
              f"std=({std[0]:5.2f},{std[1]:5.2f}) "
              f"pivot={pivot} off={offset} ppu={ppu}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_BR_Khan_N")
