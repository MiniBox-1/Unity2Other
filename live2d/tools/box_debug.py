# -*- coding: utf-8 -*-
r"""Print our model bbox vs Unity bbox for the first N parts of a character."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity2live2d.moc3 import CubismCore  # noqa: E402


def main(name, limit=5):
    pkg = ROOT / "Products" / name
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    m = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    ref = {r["name"]: r for r in json.loads(
        (ROOT / "Products" / "_unity_ref" / f"{name}.skinbounds.json")
        .read_text(encoding="utf-8"))["parts"]}
    pid = m.part_ids()
    shown = 0
    for i in range(len(m.drawable_ids())):
        src = pid[i].split("_", 2)[-1]
        hit = next((rn for rn in ref if src == rn or src.startswith(rn + "_")), None)
        if hit is None:
            continue
        v = m.vertices(i)
        xs = [a[0] for a in v]
        ys = [a[1] for a in v]
        r = ref[hit]
        ocx, ocy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        osx, osy = max(xs) - min(xs), max(ys) - min(ys)
        uv = m.uvs(i)
        us = [a for a, b in uv]
        vs = [b for a, b in uv]
        bake = json.loads((ROOT / "Products" / "_unity_ref" / f"{name}.bake.json")
                          .read_text(encoding="utf-8"))["parts"]
        bl = next((b for b in bake if b["name"] == hit), None)
        uinfo = ""
        if bl:
            bu = bl["uvs"][0::2]
            bv = bl["uvs"][1::2]
            uinfo = (f" | uv ours=({min(us):.3f},{max(us):.3f})x({min(vs):.3f},{max(vs):.3f})"
                     f" unity=({min(bu):.3f},{max(bu):.3f})x({min(bv):.3f},{max(bv):.3f})")
        print(f"{hit[:24]:24s} ours c=({ocx:6.2f},{ocy:6.2f}) s=({osx:5.2f},{osy:5.2f})"
              f" | unity c=({r['c'][0]:6.2f},{r['c'][1]:6.2f}) s=({r['s'][0]:5.2f},{r['s'][1]:5.2f}){uinfo}")
        shown += 1
        if shown >= limit:
            break


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_BR_Khan_N",
         int(sys.argv[2]) if len(sys.argv) > 2 else 5)
