# -*- coding: utf-8 -*-
r"""Build a moc3 from Unity-baked world meshes (geometry-only sanity check)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity2live2d.moc3.builder import Moc3Builder  # noqa: E402

REF = ROOT / "Products" / "_unity_ref"


def main(name: str):
    data = json.loads((REF / f"{name}.bake.json").read_text(encoding="utf-8"))
    parts = data["parts"]
    xs = [v for p in parts for v in p["verts"][0::2]]
    ys = [v for p in parts for v in p["verts"][1::2]]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    ppu = 1000.0
    margin = 0.05
    w = (maxx - minx) * (1 + 2 * margin) * ppu
    h = (maxy - miny) * (1 + 2 * margin) * ppu
    b = Moc3Builder(w, h, ppu=ppu)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    root = b.add_part("Root")
    for i, p in enumerate(parts):
        vs = [(p["verts"][j] - cx, -(p["verts"][j + 1] - cy)) for j in range(0, len(p["verts"]), 2)]
        uvs = [(p["uvs"][j], 1.0 - p["uvs"][j + 1]) for j in range(0, len(p["uvs"]), 2)]
        tris = p["tris"]
        if len(vs) < 3 or not tris:
            continue
        b.add_artmesh(root, f"P{i}", vs, uvs, tris, texture=0)
    out = REF / f"{name}.bake.moc3"
    b.write(str(out))
    print("wrote", out, "parts", len(parts))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_BR_Khan_N")
