# -*- coding: utf-8 -*-
r"""Check whether a small global shift/scale explains the residual IoU gap."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import unity_iou_audit as A  # noqa: E402


def iou(a, b):
    inter = np.logical_and(a, b).sum()
    uni = np.logical_or(a, b).sum()
    return float(inter / uni) if uni else 0.0


def pad_to(a, b):
    h = max(a.shape[0], b.shape[0])
    w = max(a.shape[1], b.shape[1])
    oa = np.zeros((h, w), bool)
    ob = np.zeros((h, w), bool)
    oa[:a.shape[0], :a.shape[1]] = a
    ob[:b.shape[0], :b.shape[1]] = b
    return oa, ob


def best_shift(a, b, r=8):
    oa, ob = pad_to(a, b)
    best = (0, 0, iou(oa, ob))
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            s = np.roll(np.roll(oa, dy, axis=0), dx, axis=1)
            v = iou(s, ob)
            if v > best[2]:
                best = (dx, dy, v)
    return best


def main(name):
    ours = A.mask(ROOT / "Products" / name / "preview.png")
    ref = A.mask(ROOT / "Products" / "_unity_ref_nat" / f"{name}.png")
    if ours is None or ref is None:
        print(name, "no mask")
        return
    oa, ob = pad_to(ours, ref)
    base = iou(oa, ob)
    dx, dy, shifted = best_shift(ours, ref)
    print(f"{name}: base={base:.3f} best_shift=({dx},{dy}) -> {shifted:.3f} "
          f"| px ours={ours.sum()} ref={ref.sum()} ratio={ours.sum() / max(1, ref.sum()):.3f}")


if __name__ == "__main__":
    for n in sys.argv[1:]:
        main(n)
