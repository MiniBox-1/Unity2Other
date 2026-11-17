# -*- coding: utf-8 -*-
r"""Compute silhouette IoU for specific characters (optional package dir)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import unity_iou_audit as A  # noqa: E402


def main(names, pkg_root=None):
    for n in names:
        ours = Path(pkg_root or (ROOT / "Products")) / n / "preview.png"
        ref = ROOT / "Products" / "_unity_ref_nat" / f"{n}.png"
        if not ours.exists() or not ref.exists():
            print(f"{n}: missing ({ours.exists()=}, {ref.exists()=})")
            continue
        a, b = A.mask(ours), A.mask(ref)
        if a is None or b is None:
            print(f"{n}: empty mask")
            continue
        print(f"{n}: IoU={A.iou(a, b):.3f}")


if __name__ == "__main__":
    pkg = os.environ.get("U2L2D_PKG")
    main(sys.argv[1:], pkg)
