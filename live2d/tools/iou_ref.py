# -*- coding: utf-8 -*-
r"""IoU of our preview against an arbitrary reference dir."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import unity_iou_audit as A  # noqa: E402


def main(ref_dir, names):
    for n in names:
        ours = ROOT / "Products" / n / "preview.png"
        ref = Path(ref_dir) / f"{n}.png"
        if not ours.exists() or not ref.exists():
            print(f"{n}: missing")
            continue
        a, b = A.mask(ours), A.mask(ref)
        if a is None or b is None:
            print(f"{n}: empty")
            continue
        print(f"{n}: IoU={A.iou(a, b):.3f} vs {Path(ref_dir).name}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
