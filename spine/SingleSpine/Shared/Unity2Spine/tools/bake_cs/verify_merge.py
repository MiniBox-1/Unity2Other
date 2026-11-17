# -*- coding: utf-8 -*-
r"""独立校验：Unity 里「纯 clip 姿态 A / 过完 DynamicBone 姿态 B」的绝对顶点，
分别与 **基线产物** 和 **合并后产物** 在同一时刻逐顶点对账。

判定方式（重要）：不要求绝对误差为 0 —— 转换器离线重算蒙皮本身就有几个像素的
模型误差，绝对对账里它一定会露出来。真正要看的是：

    |合并后 - Unity(B)|  是否  ≈  |基线 - Unity(A)|

即"把 CS 形变加进去之后，产物离 Unity 真值的距离没有变差"。同时直接看
"合并后 - 基线" 与 "S*(B-A)" 的差（这一项应当接近 0）。

标定表来自 merge_cs_bake.py 的报告（--calib merge_report.json）。

用法:
    python verify_merge.py --product <基线产物> --merged <合并后产物>
                           --verify <verify_*.json> --calib <merge_report.json>
"""

import argparse
import io
import json
import math
import os
import sys


def load_json(path):
    with io.open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def find_json(d):
    for fn in os.listdir(d):
        if fn.endswith("_static.json"):
            return os.path.join(d, fn)


def deform_value_at(frames, t):
    if not frames:
        return None
    if t <= frames[0]["time"]:
        return frames[0]["vertices"]
    if t >= frames[-1]["time"]:
        return frames[-1]["vertices"]
    lo, hi = 0, len(frames) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if frames[mid]["time"] <= t:
            lo = mid
        else:
            hi = mid
    a, b = frames[lo], frames[hi]
    span = b["time"] - a["time"]
    u = 0.0 if span <= 1e-12 else (t - a["time"]) / span
    return [x + (y - x) * u
            for x, y in zip(a["vertices"], b["vertices"])]


def mm(m, v):
    return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2] + m[3],
            m[4] * v[0] + m[5] * v[1] + m[6] * v[2] + m[7])


def stat(v):
    v = sorted(v)
    return (v[len(v) // 2], v[int(len(v) * 0.9)], v[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--merged", required=True)
    ap.add_argument("--verify", required=True)
    ap.add_argument("--calib", default=None)
    a = ap.parse_args()

    info = load_json(os.path.join(a.product, "_static_info.json"))
    base_sk = load_json(find_json(a.product))
    merg_sk = load_json(find_json(a.merged))
    vf = load_json(a.verify)
    cal = (load_json(a.calib).get("calibration") or {}) if a.calib else {}

    unit_k = float(info.get("unitScale") or 1.0)
    fx = -1.0 if info.get("flipX") else 1.0
    t = float(vf["time"])
    state = vf["state"]
    meta = info.get("partsMeta") or []
    slots = base_sk["skins"][0]["attachments"]

    def frames_of(sk, nm, an):
        dd = ((sk["animations"].get(state) or {}).get("deform")
              or {}).get("default") or {}
        return (dd.get(nm) or {}).get(an)

    print("state=%s t=%.3f  unitScale=%.3f flipX=%s" % (state, t, unit_k, info.get("flipX")))
    print("%-20s %5s | %9s %9s | %9s %9s | %9s"
          % ("part", "verts", "基线vsA", "p90", "并合vsB", "p90", "并合-基线 vs S(B-A)"))
    print("-" * 92)
    allA, allB, allD = [], [], []
    for r in vf["renderers"]:
        rel = r["path"].replace("\\", "/")
        nm = None
        for m in meta:
            if (m.get("path") or "").endswith(rel) and m.get("kind") == r.get("kind"):
                nm = m["name"]
        leaf = rel.split("/")[-1]
        if nm is None or nm not in slots:
            print("%-20s   [无对应槽位]" % leaf)
            continue
        an = nm if nm in slots[nm] else list(slots[nm].keys())[0]
        setup = slots[nm][an]["vertices"]
        n = len(setup) // 2
        if n != r["n"]:
            print("%-20s   [顶点数不一致]" % leaf)
            continue
        c = cal.get(nm)
        if c and c["S"]:
            S = c["S"]
            T = c.get("T") or [0.0, 0.0]
        else:
            S = [[fx * unit_k, 0.0], [0.0, unit_k]]
            T = [0.0, 0.0]
        da = deform_value_at(frames_of(base_sk, nm, an), t) or [0.0] * (2 * n)
        db = deform_value_at(frames_of(merg_sk, nm, an), t) or [0.0] * (2 * n)
        m = r["l2w"]
        ea, eb, ed = [], [], []
        for k in range(n):
            wa = mm(m, r["a"][k])
            wb = mm(m, r["b"][k])
            pa = (setup[2 * k] + da[2 * k], setup[2 * k + 1] + da[2 * k + 1])
            pb = (setup[2 * k] + db[2 * k], setup[2 * k + 1] + db[2 * k + 1])
            tgt_a = (S[0][0] * wa[0] + S[0][1] * wa[1] + T[0],
                     S[1][0] * wa[0] + S[1][1] * wa[1] + T[1])
            tgt_b = (S[0][0] * wb[0] + S[0][1] * wb[1] + T[0],
                     S[1][0] * wb[0] + S[1][1] * wb[1] + T[1])
            ea.append(math.hypot(pa[0] - tgt_a[0], pa[1] - tgt_a[1]))
            eb.append(math.hypot(pb[0] - tgt_b[0], pb[1] - tgt_b[1]))
            # "并合 - 基线" 应等于 S*(B-A)（这里的 T 项在差分中消掉）
            ddx = (pb[0] - pa[0]) - (tgt_b[0] - tgt_a[0])
            ddy = (pb[1] - pa[1]) - (tgt_b[1] - tgt_a[1])
            ed.append(math.hypot(ddx, ddy))
        sa, sb, sd = stat(ea), stat(eb), stat(ed)
        allA += ea
        allB += eb
        allD += ed
        print("%-20s %5d | %9.3f %9.3f | %9.3f %9.3f | %9.4f"
              % (leaf, n, sa[0], sa[1], sb[0], sb[1], sd[0]))
    print()
    for tag, v in (("基线 vs Unity A   ", allA), ("并合 vs Unity B   ", allB),
                   ("并合-基线 vs S(B-A)", allD)):
        s = stat(v)
        print("汇总 %s : 中位 %8.4f px / p90 %8.4f / 最大 %8.4f  (n=%d)"
              % (tag, s[0], s[1], s[2], len(v)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
