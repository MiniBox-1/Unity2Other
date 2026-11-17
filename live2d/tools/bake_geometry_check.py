# -*- coding: utf-8 -*-
r"""Rebuild a moc3 straight from Unity-baked world meshes and compare silhouette."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from unity2live2d.convert.static_model import StaticPart, build_static  # noqa: E402

REF = ROOT / "Products" / "_unity_ref"


def load(name):
    data = json.loads((REF / f"{name}.bake.json").read_text(encoding="utf-8"))
    parts = []
    for i, p in enumerate(data["parts"]):
        vs = [(p["verts"][j], p["verts"][j + 1]) for j in range(0, len(p["verts"]), 2)]
        uvs = [p["uvs"][j] for j in range(len(p["uvs"]))]
        tris = p["tris"]
        if len(vs) < 3 or not tris:
            continue
        parts.append(StaticPart(name=f"{p['name']}_{i}", verts=vs, uvs=uvs,
                                indices=tris, texture=Path("dummy.png"),
                                sorting_order=p.get("sort", 0), order=i))
    return parts


def mask(p, h=512):
    im = Image.open(p).convert("RGBA")
    a = np.array(im)[:, :, 3] > 8
    ys, xs = np.where(a)
    sub = im.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    s = h / sub.height
    sub = sub.resize((max(1, int(sub.width * s)), h))
    return np.array(sub)[:, :, 3] > 8


def main(name):
    parts = load(name)
    res = build_static(parts, name + "_bake")
    out = REF / f"{name}.bake.model3.json"
    REF.mkdir(parents=True, exist_ok=True)
    moc = REF / f"{name}.bake.moc3"
    moc.write_bytes(res.moc)
    (REF / f"{name}.bake.model3.json").write_text(json.dumps({
        "Version": 3,
        "FileReferences": {"Moc": moc.name, "Textures": []},
    }), encoding="utf-8")

    from flat_drawables import main as flat_main
    png = REF / f"{name}.bake.png"
    flat_main(REF / f"{name}.bake.model3.json", png, 600)

    a = mask(png)
    b = mask(REF / f"{name}.png")
    w = max(a.shape[1], b.shape[1])
    h = max(a.shape[0], b.shape[0])

    def pad(m):
        o = np.zeros((h, w), bool)
        o[:m.shape[0], :m.shape[1]] = m
        return o
    A, B = pad(a), pad(b)
    print(f"{name}: parts={len(parts)} IoU(baked vs unity)="
          f"{np.logical_and(A, B).sum() / max(1, np.logical_or(A, B).sum()):.3f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_BR_Khan_N")
