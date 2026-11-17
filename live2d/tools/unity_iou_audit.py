# -*- coding: utf-8 -*-
r"""Compare our Live2D previews against Unity ground-truth snapshots (silhouette IoU)."""
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REF = Path(os.environ.get("U2L2D_REF_DIR", str(ROOT / "Products" / "_unity_ref")))


def mask(path, h=512):
    from scipy import ndimage as ndi

    im = Image.open(path).convert("RGBA")
    a = np.array(im)[:, :, 3] > 8
    if not a.any():
        return None
    # 只保留主连通块（+ 面积 >= 5% 主块的其他块），避免远端小碎片撑大包围盒
    lab, n = ndi.label(a)
    if n > 1:
        sizes = np.bincount(lab.ravel())
        sizes[0] = 0
        main = int(sizes.argmax())
        keep = np.isin(lab, [i for i in range(1, n + 1)
                             if sizes[i] >= 0.05 * sizes[main] or i == main])
        a = keep
        im = Image.fromarray(np.dstack([np.array(im)[:, :, :3],
                                        (a * 255).astype(np.uint8)]))
    ys, xs = np.where(a)
    sub = im.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    s = h / sub.height
    sub = sub.resize((max(1, int(round(sub.width * s))), h), Image.LANCZOS)
    return np.array(sub)[:, :, 3] > 8


def iou(a, b):
    w = max(a.shape[1], b.shape[1])
    h = max(a.shape[0], b.shape[0])

    def pad(m):
        o = np.zeros((h, w), bool)
        o[:m.shape[0], :m.shape[1]] = m
        return o
    A, B = pad(a), pad(b)
    return float(np.logical_and(A, B).sum()) / max(1, np.logical_or(A, B).sum())


def main():
    rows = []
    for png in sorted(REF.glob("*.png")):
        name = png.stem
        ours = ROOT / "Products" / name / "preview.png"
        if not ours.exists():
            continue
        a = mask(ours)
        b = mask(png)
        if a is None or b is None:
            continue
        rows.append((iou(a, b), name))
    rows.sort()
    print(f"compared={len(rows)}")
    if rows:
        v = [r[0] for r in rows]
        print(f"min={v[0]:.3f} median={v[len(v)//2]:.3f} max={v[-1]:.3f}")
        for th in (0.9, 0.8, 0.7, 0.5):
            print(f"  >= {th:.1f}: {sum(1 for x in v if x >= th)}/{len(v)}")
    print("--- worst 15 ---")
    for s, n in rows[:15]:
        print(f"  {s:.3f}  {n}")
    out = ROOT / "Products" / "_unity_iou.json"
    out.write_text(json.dumps([(round(s, 3), n) for s, n in rows], ensure_ascii=False,
                              indent=2), encoding="utf-8")
    print("report:", out)


if __name__ == "__main__":
    main()
