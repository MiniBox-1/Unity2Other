# -*- coding: utf-8 -*-
r"""Compare our t=0 pose (from source clips) with Unity's live per-part bounds."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import numpy as np  # noqa: E402
from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, build_character_model)
from unity2live2d.convert.anim_world import make_sampler  # noqa: E402
from unity2live2d.convert.pipeline import _guid_index, load_states  # noqa: E402

sys.path.insert(0, r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")


def main(name, t=0.0):
    rt = json.loads((ROOT / "Products" / "_unity_rt" / f"{name}.json").read_text(encoding="utf-8"))
    live = {p["n"]: p for p in rt["parts"]}
    prefab = PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"
    mdl, parts = build_character_model(str(prefab), str(PROJ / "Assets"))
    states = load_states(prefab, _guid_index(PROJ / "Assets"))
    print("states:", [s[0] for s in states])
    for sname, _cp, clip in states[:2]:
        g = make_sampler(mdl, clip)(t)
        world = {k: g(k) for k in mdl.transforms}
        matched = 0
        tot = 0
        dsum = 0.0
        for p in parts:
            key = None
            for k in live:
                if p.name == k or p.name.startswith(k + "_"):
                    key = k
                    break
            if key is None:
                continue
            v = _skin_mesh(p, p.mesh, world)
            if not v:
                continue
            xs = [a[0] for a in v]
            ys = [a[1] for a in v]
            c = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
            lc = live[key]["min"], live[key]["max"]
            lcx = (lc[0][0] + lc[1][0]) / 2
            lcy = (lc[0][1] + lc[1][1]) / 2
            dsum += ((c[0] - lcx) ** 2 + (c[1] - lcy) ** 2) ** 0.5
            matched += 1
            tot += 1
        if tot:
            print(f"  {sname:10s} t={t}: matched {matched} mean center diff {dsum / tot:.3f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_AGS_RheinRitter_NS1",
         float(sys.argv[2]) if len(sys.argv) > 2 else 0.0)
