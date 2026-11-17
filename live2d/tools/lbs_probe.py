# -*- coding: utf-8 -*-
r"""Compute LBS with bindposes ourselves and compare against Unity renderer.bounds."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _world_matrices, build_character_model)

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
REF = ROOT / "Products" / "_unity_ref"


def mul4(a, b):
    return [sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4)]


def xform(m, v):
    x, y, z = v
    return (m[0] * x + m[1] * y + m[2] * z + m[3],
            m[4] * x + m[5] * y + m[6] * z + m[7],
            m[8] * x + m[9] * y + m[10] * z + m[11])


def main(name, part_prefix):
    mdl, parts = build_character_model(
        str(PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"), str(PROJ / "Assets"))
    world = _world_matrices(mdl, {})
    bounds = {r["name"]: r for r in json.loads(
        (REF / f"{name}.bounds.json").read_text(encoding="utf-8"))["parts"]}

    for p in parts:
        if not p.name.startswith(part_prefix):
            continue
        mesh = p.mesh
        pos = mesh["positions"]
        bps = mesh.get("bindposes") or []
        wts = mesh.get("weights") or []
        raw = mesh.get("boneIndexRaw") or []
        bones = [b for b in (p.bones or []) if b]

        out = []
        for vi, v in enumerate(pos):
            px = py = pz = 0.0
            w = wts[vi] if vi < len(wts) else (1.0,)
            bi = raw[vi] if vi < len(raw) else (0,)
            for k in range(min(len(w), 4)):
                ww = float(w[k])
                if ww == 0:
                    continue
                idx = int(round(float(bi[k]))) if k < len(bi) else 0
                if idx >= len(bones) or idx >= len(bps):
                    continue
                bw = world.get(bones[idx])
                if bw is None:
                    continue
                bp = bps[idx]
                # 行主序 bindpose（Unity 是列主序？先按列主序转置试）
                m = mul4(bw, bp)
                q = xform(m, v)
                px += q[0] * ww
                py += q[1] * ww
                pz += q[2] * ww
            out.append((px, py, pz))

        xs = [a[0] for a in out]
        ys = [a[1] for a in out]
        b = bounds.get(part_prefix)
        print(f"{p.name}: LBS bbox x=({min(xs):.3f},{max(xs):.3f}) y=({min(ys):.3f},{max(ys):.3f})")
        if b:
            cx, cy = b["c"]
            sx, sy = b["s"]
            print(f"   unity  x=({cx - sx / 2:.3f},{cx + sx / 2:.3f}) y=({cy - sy / 2:.3f},{cy + sy / 2:.3f})")
        break


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_BR_Khan_N",
         sys.argv[2] if len(sys.argv) > 2 else "kh_parts_body")
