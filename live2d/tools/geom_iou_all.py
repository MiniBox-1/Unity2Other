# -*- coding: utf-8 -*-
r"""Geometry IoU (model drawables vs Unity true skinning) for every character."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import geom_iou  # noqa: E402


def names():
    return sorted(p.name for p in (ROOT / "Products").iterdir()
                  if p.is_dir() and (p / f"{p.name}.model3.json").exists()
                  and (ROOT / "Products" / "_unity_ref" / f"{p.name}.bake.json").exists())


def main():
    rows = []
    for n in names():
        try:
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                geom_iou.main(n)
            out = buf.getvalue().strip().splitlines()[-1]
            iou = float(out.split("=")[1].split("(")[0])
            rows.append((iou, n))
        except Exception as e:
            rows.append((-1.0, n + " ERR:" + type(e).__name__))
    rows.sort()
    good = sum(1 for r in rows if r[0] >= 0.95)
    print(f"models={len(rows)}  IoU>=0.95: {good}")
    print("--- worst 20 ---")
    for r in rows[:20]:
        print(f"  {r[0]:.3f}  {r[1]}")
    out = ROOT / "Products" / "_geom_iou.json"
    out.write_text(json.dumps([(round(a, 3), b) for a, b in rows], ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print("report:", out)


if __name__ == "__main__":
    main()
