# -*- coding: utf-8 -*-
r"""Run auto_drop (write mode) for all characters whose IoU is below a threshold."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import auto_drop  # noqa: E402


def main(threshold=0.8):
    report = json.loads((ROOT / "Products" / "_unity_iou.json").read_text(encoding="utf-8"))
    targets = [n for iou, n in report if iou < threshold]
    print(f"targets (<{threshold}): {len(targets)}")
    written = 0
    for n in targets:
        try:
            d = auto_drop.main(n, dry=False)
            if d:
                written += 1
        except Exception as e:
            print(f"  ERR {n}: {type(e).__name__}")
    print("characters with drop list:", written)


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 0.8)
