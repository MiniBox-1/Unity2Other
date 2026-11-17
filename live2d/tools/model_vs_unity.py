# -*- coding: utf-8 -*-
r"""For each moc3 drawable, find distance to nearest Unity part centroid."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity2live2d.moc3 import CubismCore  # noqa: E402

REF = ROOT / "Products" / "_unity_ref"


def main(name):
    pkg = ROOT / "Products" / name
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    ref_file = REF / f"{name}.skinbounds.json"
    if not ref_file.exists():
        ref_file = REF / f"{name}.bounds.json"
    parts = json.loads(ref_file.read_text(encoding="utf-8"))["parts"]
    cs = np.array([p["c"] for p in parts])

    bad = []
    for i in range(len(model.drawable_ids())):
        v = model.vertices(i)
        if not v:
            continue
        xs = [a[0] for a in v]
        ys = [a[1] for a in v]
        c = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        d = np.hypot(cs[:, 0] - c[0], cs[:, 1] - c[1]).min()
        if d > 0.12:
            bad.append((d, i, model.drawable_ids()[i]))
    bad.sort(reverse=True)
    print(f"{name}: drawables={len(model.drawable_ids())} far>0.12: {len(bad)}")
    for d, i, aid in bad[:12]:
        print(f"  d={d:.3f} #{i} {aid}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_BR_Khan_N")
