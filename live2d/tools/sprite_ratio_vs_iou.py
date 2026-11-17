# -*- coding: utf-8 -*-
r"""Correlate sprite-part ratio with the Live2D-vs-Spine IoU."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import build_character_model  # noqa: E402

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
PRODUCTS = ROOT / "Products"


def main(limit=0):
    rows = json.loads((PRODUCTS / "_compare_report.json").read_text(encoding="utf-8"))
    rows = [r for r in rows if "iou" in r]
    if limit:
        rows = rows[:limit]
    out = []
    for r in rows:
        name = r["name"]
        pf = PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"
        if not pf.exists():
            continue
        try:
            _, parts = build_character_model(str(pf), str(PROJ / "Assets"))
        except Exception:
            continue
        n = len(parts) or 1
        sp = sum(1 for p in parts if p.kind == "sprite")
        out.append((sp / n, r["iou"], name, len(parts)))
    out.sort()
    if not out:
        return
    # 分桶
    buckets = {"<0.2": [], "0.2-0.5": [], "0.5-0.8": [], ">=0.8": []}
    for ratio, iou, name, n in out:
        key = ("<0.2" if ratio < 0.2 else "0.2-0.5" if ratio < 0.5
               else "0.5-0.8" if ratio < 0.8 else ">=0.8")
        buckets[key].append(iou)
    import statistics
    print(f"n={len(out)}")
    for k, v in buckets.items():
        if v:
            print(f"  sprite 占比 {k:8s}: n={len(v):3d} median IoU={statistics.median(v):.3f} "
                  f"mean={sum(v)/len(v):.3f}")
    print("\n最差的 10 个（含 sprite 占比）:")
    for ratio, iou, name, n in sorted(out, key=lambda t: t[1])[:10]:
        print(f"  {iou:.3f} sprite={ratio:.2f} parts={n:3d} {name}")

    low = [t for t in out if t[0] < 0.2]
    print(f"\nsprite 占比 <0.2 的角色共 {len(low)} 个，最差 10 个:")
    for ratio, iou, name, n in sorted(low, key=lambda t: t[1])[:10]:
        print(f"  {iou:.3f} sprite={ratio:.2f} parts={n:3d} {name}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
