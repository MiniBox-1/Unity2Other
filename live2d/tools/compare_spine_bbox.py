# -*- coding: utf-8 -*-
r"""Compare per-attachment world bbox between the Spine product and our extraction."""
import json
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
SPINE = Path(r"D:\VB\Convert\Spine\MultiSpine\LO\Products\Current")


def spine_world_bones(data):
    bones = {b["name"]: b for b in data.get("bones", [])}
    cache = {}

    def get(name):
        if name in cache:
            return cache[name]
        b = bones[name]
        px, py = float(b.get("x", 0)), float(b.get("y", 0))
        rot = math.radians(float(b.get("rotation", 0)))
        sx, sy = float(b.get("scaleX", 1)), float(b.get("scaleY", 1))
        local = (math.cos(rot) * sx, math.sin(rot) * sx,
                 -math.sin(rot) * sy, math.cos(rot) * sy, px, py)
        p = b.get("parent")
        m = local if not p else mul(get(p), local)
        cache[name] = m
        return m

    return get


def mul(m, n):
    a, b, c, d, tx, ty = m
    e, f, g, h, ux, uy = n
    return (a * e + c * f, b * e + d * f, a * g + c * h, b * g + d * h,
            a * ux + c * uy + tx, b * ux + d * uy + ty)


def ap(m, p):
    return (m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5])


def main(name):
    base = SPINE / f"{name}.uAnim"
    js = next(base.glob("*.json"), None)
    if js is None:
        raise SystemExit(f"no spine json in {base}")
    data = json.loads(js.read_text(encoding="utf-8"))
    getb = spine_world_bones(data)
    bone_order = [b["name"] for b in data.get("bones", [])]
    skin = (data.get("skins") or [{}])[0]
    atts = skin.get("attachments") or {}

    print("spine attachments:", len(atts))
    for key, items in list(atts.items()):
        if not any("Back_Hair_001" in k for k in items):
            continue
        for k, att in items.items():
            if att.get("type") != "mesh":
                continue
            verts = att["vertices"]
            pts = []
            i = 0
            while i < len(verts):
                n = int(verts[i])
                i += 1
                px = py = 0.0
                for _ in range(n):
                    bi = int(verts[i]); x = verts[i + 1]; y = verts[i + 2]; w = verts[i + 3]
                    i += 4
                    m = getb(bone_order[bi])
                    q = ap(m, (x, y))
                    px += q[0] * w
                    py += q[1] * w
                pts.append((px, py))
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            print(f"SPINE {k[:44]:44s} n={len(pts):3d} "
                  f"x=[{min(xs):6.2f},{max(xs):6.2f}] y=[{min(ys):6.2f},{max(ys):6.2f}]")

    mdl, parts = build_character_model(str(ASSETS / "Prefabs" / f"{name}.uAnim.prefab"), str(ASSETS))
    world = _world_matrices(mdl, {})
    for p in parts:
        if "Back_Hair_001" in p.name:
            v = [(a[0], a[1]) for a in _skin_mesh(p, p.mesh, world)]
            xs = [a[0] for a in v]; ys = [a[1] for a in v]
            print(f"OURS  {p.name[:44]:44s} n={len(v):3d} "
                  f"x=[{min(xs):6.2f},{max(xs):6.2f}] y=[{min(ys):6.2f},{max(ys):6.2f}]")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_ST_Tiamat_NS1")
