# -*- coding: utf-8 -*-
r"""Find drawables that end up invisible in our own render (alpha ~0 in their bbox)."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from unity2live2d.moc3 import CubismCore  # noqa: E402
from part_visibility import raster_model  # noqa: E402


def main(name):
    pkg = ROOT / "Products" / name
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    idmap, _ = raster_model(model)
    img = np.array(Image.open(pkg / "preview.png").convert("RGBA"))
    if img.shape[0] != idmap.shape[0]:
        img = np.array(Image.fromarray(img).resize((idmap.shape[1], idmap.shape[0])))
    alpha = img[:, :, 3] > 8
    pid = model.part_ids()
    bad = []
    for i in range(len(pid)):
        sel = idmap == i
        n = int(sel.sum())
        if n < 100:
            continue
        cov = float(alpha[sel].mean())
        if cov < 0.05:
            bad.append((i, pid[i], n))
    print(f"{name}: drawables={len(pid)} invisible={len(bad)}")
    for i, p, n in bad[:12]:
        print(f"  #{i:3d} px={n:6d} {p[:56]}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_AGS_RheinRitter_NS1")
