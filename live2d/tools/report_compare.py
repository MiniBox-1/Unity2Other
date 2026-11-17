# -*- coding: utf-8 -*-
r"""Summarize _compare_report.json: distribution, completeness filter, worst list."""
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(path: Path, min_ratio: float = 0.6):
    rows = json.loads(path.read_text(encoding="utf-8"))
    ok = [r for r in rows if "iou" in r]
    err = [r for r in rows if "error" in r]

    def ratio(r):
        sp, src = r.get("spine_meshes"), r.get("src_parts")
        if not sp or not src:
            return None
        return sp / src

    trusted = [r for r in ok if (ratio(r) or 0) >= min_ratio]
    weak_ref = [r for r in ok if (ratio(r) or 0) < min_ratio]

    def dist(rs, label):
        if not rs:
            return
        v = sorted(r["iou"] for r in rs)
        print(f"\n[{label}] n={len(rs)}  min={v[0]:.3f} p10={v[len(v)//10]:.3f} "
              f"median={statistics.median(v):.3f} max={v[-1]:.3f}")
        for th in (0.7, 0.85, 0.95):
            print(f"   >= {th:.2f}: {sum(1 for x in v if x >= th)}/{len(v)}")

    print(f"total={len(rows)} ok={len(ok)} errors={len(err)}")
    dist(trusted, "Spine 产物较完整（可信参照）")
    dist(weak_ref, "Spine 产物不完整（参照不可信）")

    print("\n--- 可信参照里最差 15 ---")
    for r in sorted(trusted, key=lambda x: x["iou"])[:15]:
        print(f"{r['iou']:.3f} cover={r.get('cover', 0):.2f} "
              f"spine/ours={r.get('spine_meshes')}/{r.get('src_parts')}  {r['name']}")

    if err:
        print("--- errors ---")
        for r in err[:6]:
            print(r["name"], r.get("error"))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "Products" / "_compare_report.json")
