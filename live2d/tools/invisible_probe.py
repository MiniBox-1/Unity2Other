# -*- coding: utf-8 -*-
r"""Inspect why specific parts render transparent (texture page / UV / alpha)."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity2live2d.moc3 import CubismCore  # noqa: E402

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")


def main(name, needles):
    pkg = ROOT / "Products" / name
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    texs = [pkg / t for t in (m3["FileReferences"]["Textures"] or [])]
    pid = model.part_ids()

    for i, p in enumerate(pid):
        if not any(n in p for n in needles):
            continue
        d = model.drawable(i)
        uv = model.uvs(i)
        us = [a for a, b in uv]
        vs = [b for a, b in uv]
        t = int(d["texture"])
        print(f"#{i} {p[:46]:46s} tex={t} u=({min(us):.3f},{max(us):.3f}) "
              f"v=({min(vs):.3f},{max(vs):.3f})")
        if 0 <= t < len(texs) and texs[t].exists():
            a = np.asarray(Image.open(texs[t]).convert("RGBA"))[:, :, 3]
            h, w = a.shape
            u0 = int(np.clip(min(us) * w, 0, w - 1))
            u1 = int(np.clip(max(us) * w, 0, w - 1))
            v0 = int(np.clip((1 - max(vs)) * h, 0, h - 1))
            v1 = int(np.clip((1 - min(vs)) * h, 0, h - 1))
            sub = a[v0:v1 + 1, u0:u1 + 1]
            print(f"    page={texs[t].name} alpha_mean={sub.mean():.1f} "
                  f"opaque_frac={(sub > 8).mean():.3f} rect=({u0},{v0})-({u1},{v1})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:] or ["Tail_01", "Gun_L_U"])
