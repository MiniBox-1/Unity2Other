# -*- coding: utf-8 -*-
r"""LBS using Unity-dumped bone world matrices + our bindposes; compare to bounds."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import build_character_model  # noqa: E402

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
REF = ROOT / "Products" / "_unity_ref"


def mul4(a, b):
    return [sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4)]


def xform(m, v):
    x, y, z = v
    return (m[0] * x + m[1] * y + m[2] * z + m[3],
            m[4] * x + m[5] * y + m[6] * z + m[7],
            m[8] * x + m[9] * y + m[10] * z + m[11])


def main(name, part):
    mdl, parts = build_character_model(
        str(PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"), str(PROJ / "Assets"))
    p = next(q for q in parts if q.name.startswith(part))
    mesh = p.mesh
    dump = json.loads((REF / f"{name}.bones.json").read_text(encoding="utf-8"))["parts"][0]
    bones = dump["bones"]

    out = []
    for vi, v in enumerate(mesh["positions"]):
        w = mesh["weights"][vi]
        bi = mesh["boneIndexRaw"][vi]
        px = py = pz = 0.0
        for k in range(min(4, len(w))):
            ww = float(w[k])
            if ww == 0:
                continue
            idx = int(round(float(bi[k])))
            if idx >= len(bones) or idx >= len(mesh["bindposes"]):
                continue
            m = mul4(bones[idx]["m"], mesh["bindposes"][idx])
            q = xform(m, v)
            px += q[0] * ww
            py += q[1] * ww
            pz += q[2] * ww
        out.append((px, py, pz))

    xs = [a[0] for a in out]
    ys = [a[1] for a in out]
    print(f"{p.name}: unity-bone LBS  x=({min(xs):.3f},{max(xs):.3f}) y=({min(ys):.3f},{max(ys):.3f})")
    b = {r["name"]: r for r in json.loads(
        (REF / f"{name}.bounds.json").read_text(encoding="utf-8"))["parts"]}.get(part)
    if b:
        cx, cy = b["c"]
        sx, sy = b["s"]
        print(f"   unity bounds     x=({cx - sx / 2:.3f},{cx + sx / 2:.3f}) y=({cy - sy / 2:.3f},{cy + sy / 2:.3f})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_BR_Khan_N",
         sys.argv[2] if len(sys.argv) > 2 else "kh_parts_body")
