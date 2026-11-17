# -*- coding: utf-8 -*-
r"""Conservative drop: parts entirely outside Unity's content and fully transparent there."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from unity2live2d.moc3 import CubismCore  # noqa: E402
from part_visibility import raster_model, unity_mask  # noqa: E402
from auto_drop import source_name  # noqa: E402

OUT = ROOT / "Products" / "_drop"


def main(name, write=False):
    pkg = ROOT / "Products" / name
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    idmap, size = raster_model(model)
    umask = unity_mask(name, size)
    ys, xs = np.where(umask)
    ubox = (xs.min(), ys.min(), xs.max(), ys.max()) if len(xs) else (0, 0, size[0], size[1])

    drop = []
    for i in range(len(model.drawable_ids())):
        sel = idmap == i
        if sel.sum() < 64:
            continue
        ys2, xs2 = np.where(sel)
        box = (xs2.min(), ys2.min(), xs2.max(), ys2.max())
        inside = not (box[2] < ubox[0] or box[0] > ubox[2] or
                      box[3] < ubox[1] or box[1] > ubox[3])
        hit = float(umask[sel].mean())
        if not inside and hit < 0.02:
            drop.append(source_name(model.part_ids()[i]))

    drop = sorted(set(drop))
    print(f"{name}: conservative drop {len(drop)}: {drop[:6]}")
    if write and drop:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{name}.json").write_text(json.dumps(drop), encoding="utf-8")
    return drop


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    for n in args:
        main(n, write="--write" in sys.argv)
