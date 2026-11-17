# -*- coding: utf-8 -*-
r"""尾巴的偏差随时间是"固定平移"还是"越走越歪"？

对每一帧算 e(t) = 产物姿态 - (S*Unity世界 + T)，报告
   mean(e)   —— 整体平移量
   std(e)    —— 逐顶点形状误差
再用"e(t) 相对 e(0) 的变化"看它是常量还是随时间漂。

用法:
    python diag_tail_err_time.py --product <基线产物> --dump <...\lobby__A.json>
        --report <merge_report.json> --part parts_Tail_F [--every 50]
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


def mm(m, v):
    return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2] + m[3],
            m[4] * v[0] + m[5] * v[1] + m[6] * v[2] + m[7])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--dump", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--part", default="parts_Tail_F")
    ap.add_argument("--every", type=int, default=50)
    a = ap.parse_args()

    info = load_json(os.path.join(a.product, "_static_info.json"))
    sk = load_json(find_json(a.product))
    rep = load_json(a.report)
    d = load_json(a.dump)
    unit_k = float(info["unitScale"])
    slots = sk["skins"][0]["attachments"]
    st = d["state"]
    nm = None
    for m in info["partsMeta"]:
        if m["path"].endswith(a.part):
            nm = m["name"]
    S = rep["calibration"][nm]["S"]
    T = rep["calibration"][nm]["T"] or [0.0, 0.0]
    setup = slots[nm][nm]["vertices"]
    n = len(setup) // 2
    pi = next(i for i, p in enumerate(d["parts"])
              if p["path"].replace("\\", "/").endswith(a.part))
    dfr = ((sk["animations"].get(st) or {}).get("deform")
           or {}).get("default", {}).get(nm, {}).get(nm) or []

    def dv_at(t):
        if not dfr:
            return [0.0] * (2 * n)
        if t <= dfr[0]["time"]:
            return dfr[0]["vertices"]
        if t >= dfr[-1]["time"]:
            return dfr[-1]["vertices"]
        for i in range(len(dfr) - 1):
            if dfr[i]["time"] <= t <= dfr[i + 1]["time"]:
                sp = dfr[i + 1]["time"] - dfr[i]["time"]
                u = 0.0 if sp <= 1e-12 else (t - dfr[i]["time"]) / sp
                return [x + (y - x) * u
                        for x, y in zip(dfr[i]["vertices"], dfr[i + 1]["vertices"])]

    print("部件 %s (%s) 单位:px   1px=%.5f 世界单位" % (a.part, st, 1.0 / unit_k))
    print("%8s %14s %14s %14s" % ("t", "mean(e)", "std(e)", "|mean(e)-mean(e0)|"))
    base_mean = None
    drift = []
    for f, fr in enumerate(d["frames"]):
        t = fr["t"]
        dv = dv_at(t)
        pd = fr["parts"][pi]
        m = pd["l2w"]
        vs = pd["verts"]
        ex = ey = 0.0
        es = []
        for i in range(n):
            w = mm(m, (vs[3 * i], vs[3 * i + 1], vs[3 * i + 2]))
            tx = S[0][0] * w[0] + S[0][1] * w[1] + T[0]
            ty = S[1][0] * w[0] + S[1][1] * w[1] + T[1]
            dx = setup[2 * i] + dv[2 * i] - tx
            dy = setup[2 * i + 1] + dv[2 * i + 1] - ty
            ex += dx
            ey += dy
            es.append((dx, dy))
        ex /= n
        ey /= n
        sd = math.sqrt(sum((x - ex) ** 2 + (y - ey) ** 2 for x, y in es) / n)
        if base_mean is None:
            base_mean = (ex, ey)
        dd = math.hypot(ex - base_mean[0], ey - base_mean[1])
        drift.append(dd)
        if f % a.every == 0 or f == len(d["frames"]) - 1:
            print("%8.3f (%7.2f,%7.2f) %14.3f %14.3f" % (t, ex, ey, sd, dd))
    print()
    print("mean(e) 相对首帧的最大漂移 = %.2f px；std(e) 中位 = 形状误差"
          % max(drift))
    return 0


if __name__ == "__main__":
    sys.exit(main())
