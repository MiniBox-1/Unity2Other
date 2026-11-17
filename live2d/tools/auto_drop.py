# -*- coding: utf-8 -*-
r"""Compute per-character 'drop list' of parts invisible in Unity's natural render."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from unity2live2d.moc3 import CubismCore  # noqa: E402
from part_visibility import raster_model, unity_mask  # noqa: E402

OUT = ROOT / "Products" / "_drop"


def source_name(part_id: str) -> str:
    """Part_07_parts_body_02_Bone_Body_1 -> parts_body_02"""
    s = part_id
    if s.startswith("Part_"):
        s = s.split("_", 2)[-1]
    for marker in ("_Bone_", "_bone_"):
        if marker in s:
            s = s.split(marker)[0]
    return s


def main(name, min_hit=0.15, min_area=0.004, dry=True):
    pkg = ROOT / "Products" / name
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    idmap, size = raster_model(model)
    umask = unity_mask(name, size)
    ids = model.part_ids()
    canvas_px = size[0] * size[1]

    drop = {}
    for i in range(len(ids)):
        sel = idmap == i
        n = int(sel.sum())
        if n < max(24, min_area * canvas_px):
            continue
        hit = float(umask[sel].mean())
        if hit < min_hit:
            src = source_name(ids[i])
            drop[src] = drop.get(src, 0) + 1
    print(f"{name}: drop candidates {len(drop)}")
    for k, v in list(drop.items())[:10]:
        print(f"   {k[:46]:46s} segs={v}")
    if not dry and drop:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{name}.json").write_text(json.dumps(sorted(drop)), encoding="utf-8")
        print("   written", OUT / f"{name}.json")
    return drop


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    write = "--write" in sys.argv
    for n in args:
        main(n, dry=not write)
