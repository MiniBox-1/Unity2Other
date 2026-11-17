# -*- coding: utf-8 -*-
r"""Overlay our mask (red) and Unity mask (blue) to visualise differences."""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import unity_iou_audit as A  # noqa: E402


def main(name, ref_dir="Products/_unity_ref_nat", out="Products/_overlay.png"):
    a = A.mask(ROOT / "Products" / name / "preview.png")
    b = A.mask(ROOT / ref_dir / f"{name}.png")
    w = max(a.shape[1], b.shape[1])
    h = max(a.shape[0], b.shape[0])

    def pad(m):
        o = np.zeros((h, w), bool)
        o[:m.shape[0], :m.shape[1]] = m
        return o
    a, b = pad(a), pad(b)
    img = np.full((h, w, 3), 255, np.uint8)
    only_a = a & ~b
    only_b = b & ~a
    both = a & b
    img[both] = (180, 180, 180)
    img[only_a] = (220, 60, 60)
    img[only_b] = (60, 90, 220)
    Image.fromarray(img).save(ROOT / out)
    print(out, "red=ours only, blue=unity only, gray=both")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_AGS_RheinRitter_NS1")
