# -*- coding: utf-8 -*-
r"""两份 Spine 产物在**产物空间**里逐顶点对比（单位=产物像素）。

用途：把"移植版（转换器自己算 CS）产物"和"已验证的录制+合并产物"直接比 ——
两边都是同一套产物坐标，**不需要任何跨坐标系换算**，是最终验收口径。

用法:
    python cmp_products.py --a <产物A> --b <产物B> [--top 10]
"""

import argparse
import io
import json
import math
import os
import sys


def load_json(p):
    with io.open(p, encoding="utf-8-sig") as fh:
        return json.load(fh)


def find_json(d):
    for fn in os.listdir(d):
        if fn.endswith("_static.json"):
            return os.path.join(d, fn)


def value_at(frames, t):
    if not frames:
        return None
    if t <= frames[0]["time"]:
        return frames[0]["vertices"]
    if t >= frames[-1]["time"]:
        return frames[-1]["vertices"]
    for i in range(len(frames) - 1):
        if frames[i]["time"] <= t <= frames[i + 1]["time"]:
            sp = frames[i + 1]["time"] - frames[i]["time"]
            u = 0.0 if sp <= 1e-12 else (t - frames[i]["time"]) / sp
            return [x + (y - x) * u
                    for x, y in zip(frames[i]["vertices"], frames[i + 1]["vertices"])]
    return frames[-1]["vertices"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="产物 A（例如移植版）")
    ap.add_argument("--b", required=True, help="产物 B（例如已验证的合并版）")
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()

    A = load_json(find_json(a.a))
    B = load_json(find_json(a.b))
    at = A["skins"][0]["attachments"]
    bt = B["skins"][0]["attachments"]
    print("A=%s  %d 槽位" % (os.path.basename(a.a.rstrip("\\/")), len(at)))
    print("B=%s  %d 槽位" % (os.path.basename(a.b.rstrip("\\/")), len(bt)))
    only_a = sorted(set(at) - set(bt))
    only_b = sorted(set(bt) - set(at))
    if only_a:
        print("只在 A 里的槽位: %s" % only_a[:6])
    if only_b:
        print("只在 B 里的槽位: %s" % only_b[:6])
    print()
    print("%-12s %-22s %8s %10s %10s" % ("动画", "槽位", "顶点", "中位px", "最大px"))
    print("-" * 70)
    worst = []
    for an in sorted(set(A.get("animations", {})) & set(B.get("animations", {}))):
        da = ((A["animations"][an].get("deform") or {}).get("default") or {})
        db = ((B["animations"][an].get("deform") or {}).get("default") or {})
        for nm in sorted(set(da) & set(db)):
            fa = da[nm][list(da[nm].keys())[0]]
            fb = db[nm][list(db[nm].keys())[0]]
            n = len(at[nm][list(at[nm].keys())[0]]["vertices"]) // 2
            ts = sorted(set([f["time"] for f in fa]) |
                        set([f["time"] for f in fb]))
            ea = []
            for t in ts:
                va = value_at(fa, t)
                vb = value_at(fb, t)
                if not va or not vb or len(va) != len(vb):
                    continue
                for i in range(n):
                    ea.append(math.hypot(va[2 * i] - vb[2 * i],
                                         va[2 * i + 1] - vb[2 * i + 1]))
            if not ea:
                continue
            ea.sort()
            worst.append((ea[len(ea) // 2], ea[-1], an, nm, n))
    worst.sort(reverse=True)
    for (med, mx, an, nm, n) in worst[:a.top]:
        print("%-12s %-22s %8d %10.4f %10.4f" % (an, nm, n, med, mx))
    allv = []
    for an in sorted(set(A.get("animations", {})) & set(B.get("animations", {}))):
        da = ((A["animations"][an].get("deform") or {}).get("default") or {})
        db = ((B["animations"][an].get("deform") or {}).get("default") or {})
        for nm in sorted(set(da) & set(db)):
            fa = da[nm][list(da[nm].keys())[0]]
            fb = db[nm][list(db[nm].keys())[0]]
            for t in sorted(set([f["time"] for f in fa]) |
                            set([f["time"] for f in fb])):
                va = value_at(fa, t)
                vb = value_at(fb, t)
                if va and vb and len(va) == len(vb):
                    allv += [math.hypot(va[2 * i] - vb[2 * i],
                                        va[2 * i + 1] - vb[2 * i + 1])
                             for i in range(len(va) // 2)]
    allv.sort()
    print()
    print("全部 %d 个差值：中位 %.4f px / p90 %.4f / 最大 %.4f"
          % (len(allv), allv[len(allv) // 2], allv[int(len(allv) * 0.9)], allv[-1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
