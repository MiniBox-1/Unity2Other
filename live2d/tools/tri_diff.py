# -*- coding: utf-8 -*-
r"""Compare moc3 drawable triangles with Unity-baked triangles per part."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity2live2d.moc3 import CubismCore  # noqa: E402

REF = ROOT / "Products" / "_unity_ref"


def main(name):
    pkg = ROOT / "Products" / name
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    bake = {p["name"]: p for p in json.loads(
        (REF / f"{name}.bake.json").read_text(encoding="utf-8"))["parts"]}
    pid = model.part_ids()

    shown = 0
    for i in range(len(model.drawable_ids())):
        pn = pid[i].split("_", 2)[-1]
        hit = None
        for rn in bake:
            if pn == rn or pn.startswith(rn + "_"):
                hit = rn
                break
        if hit is None:
            continue
        ours_v = model.vertices(i)
        ours_t = model.indices(i)
        ref_v = bake[hit]["verts"]
        ref_t = bake[hit]["tris"]
        nv = len(ref_v) // 2
        print(f"#{i} {pn[:30]:30s} ours v={len(ours_v)} t={len(ours_t)//3} | "
              f"unity v={nv} t={len(ref_t)//3} | "
              f"tri-match={sorted(set(ours_t)) == list(range(len(ours_v))) if len(ours_v) else False}")
        shown += 1
        if shown >= 6:
            break


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_BR_Khan_N")
