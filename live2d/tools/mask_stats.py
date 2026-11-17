# -*- coding: utf-8 -*-
r"""Precision/recall between our render and Unity natural snapshot."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import unity_iou_audit as A  # noqa: E402


def main(names):
    for n in names:
        ours = ROOT / "Products" / n / "preview.png"
        ref = ROOT / "Products" / "_unity_ref_nat" / f"{n}.png"
        a, b = A.mask(ours), A.mask(ref)
        if a is None or b is None:
            print(n, "empty")
            continue
        w = max(a.shape[1], b.shape[1])
        h = max(a.shape[0], b.shape[0])

        def pad(m):
            o = np.zeros((h, w), bool)
            o[:m.shape[0], :m.shape[1]] = m
            return o
        a, b = pad(a), pad(b)
        inter = np.logical_and(a, b).sum()
        prec = inter / max(1, a.sum())
        rec = inter / max(1, b.sum())
        print(f"{n}: IoU={inter / max(1, np.logical_or(a, b).sum()):.3f} "
              f"precision={prec:.3f} recall={rec:.3f} ours_px={a.sum()} unity_px={b.sum()}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["2DModel_AGS_RheinRitter_NS1"])
