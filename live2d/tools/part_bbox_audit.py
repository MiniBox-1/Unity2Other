# -*- coding: utf-8 -*-
r"""Per-source-part bbox audit: our model (segments merged) vs Unity true bounds."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity2live2d.moc3 import CubismCore  # noqa: E402

REF = ROOT / "Products" / "_unity_ref"


def bbox_iou(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    ua = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / ua if ua > 0 else 0.0


def audit(name):
    pkg = ROOT / "Products" / name
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    ref_file = REF / f"{name}.skinbounds.json"
    ref = json.loads(ref_file.read_text(encoding="utf-8"))["parts"]
    ref_boxes = {}
    for r in ref:
        cx, cy = r["c"]
        sx, sy = r["s"]
        ref_boxes[r["name"]] = (cx - sx / 2, cy - sy / 2, cx + sx / 2, cy + sy / 2)

    pid = model.part_ids()
    groups = {}
    for i in range(len(model.drawable_ids())):
        src = pid[i].split("_", 2)[-1]
        hit = None
        for rn in ref_boxes:
            if src == rn or src.startswith(rn + "_"):
                hit = rn
                break
        if hit is None:
            continue
        v = model.vertices(i)
        if not v:
            continue
        xs = [a[0] for a in v]
        ys = [a[1] for a in v]
        g = groups.setdefault(hit, [1e9, 1e9, -1e9, -1e9])
        g[0] = min(g[0], min(xs)); g[1] = min(g[1], min(ys))
        g[2] = max(g[2], max(xs)); g[3] = max(g[3], max(ys))

    ious = []
    worst = []
    for rn, g in groups.items():
        i = bbox_iou(g, ref_boxes[rn])
        ious.append(i)
        worst.append((i, rn))
    worst.sort()
    return ious, worst


def main(names=None):
    if names is None:
        names = sorted(p.name for p in (ROOT / "Products").iterdir()
                       if p.is_dir() and (p / f"{p.name}.model3.json").exists()
                       and (ROOT / "Products" / "_unity_ref" / f"{p.name}.skinbounds.json").exists())
    rows = []
    for n in names:
        try:
            ious, worst = audit(n)
        except Exception as e:
            print(f"{n}: ERR {type(e).__name__}")
            continue
        if not ious:
            continue
        mean = float(np.mean(ious))
        rows.append((mean, n, len(ious), worst[:3]))
    rows.sort()
    good = sum(1 for r in rows if r[0] >= 0.9)
    print(f"models={len(rows)} mean-part-IoU>=0.9: {good}")
    for mean, n, k, w in rows[:15]:
        print(f"  {mean:.3f} parts={k:3d} {n}   worst={[(round(a, 2), b[:22]) for a, b in w]}")
    (ROOT / "Products" / "_part_bbox_audit.json").write_text(
        json.dumps([(round(m, 3), n) for m, n, _, _ in rows], ensure_ascii=False, indent=2),
        encoding="utf-8")


if __name__ == "__main__":
    main()
