# -*- coding: utf-8 -*-
r"""查"标定出来的 T 为什么不是那个常量"：按 merge_cs_bake.py 的取法重建 rows，
逐行打印 (产物质心 相对 S*世界质心) 的值，看它到底是不是常量。

用法:
    python diag_T_bug.py --product <产物> --bake <bake.json> --report <merge_report.json>
        --part parts_Tail_F [--rows 10]
"""

import argparse
import io
import json
import os
import sys


def load_json(p):
    with io.open(p, encoding="utf-8-sig") as fh:
        return json.load(fh)


def find_json(d):
    for fn in os.listdir(d):
        if fn.endswith("_static.json"):
            return os.path.join(d, fn)


def mm3(m, v):
    return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2] + m[3],
            m[4] * v[0] + m[5] * v[1] + m[6] * v[2] + m[7])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--bake", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--part", default="parts_Tail_F")
    ap.add_argument("--rows", type=int, default=10)
    a = ap.parse_args()

    info = load_json(os.path.join(a.product, "_static_info.json"))
    sk = load_json(find_json(a.product))
    bake = load_json(a.bake)
    rep = load_json(a.report)
    slots = sk["skins"][0]["attachments"]
    nm = None
    for m in info["partsMeta"]:
        if m["path"].endswith(a.part):
            nm = m["name"]
    S = rep["calibration"][nm]["S"]
    T = rep["calibration"][nm]["T"]
    print("报告里的 S=[[%.3f,%.3f],[%.3f,%.3f]]  T=(%.3f,%.3f)"
          % (S[0][0], S[0][1], S[1][0], S[1][1], T[0], T[1]))

    cl = next(c for c in bake["clips"] if c.get("absState") == c["state"])
    times = cl["times"]
    aevery = int(cl.get("absEvery") or 1)
    print("用 absState=%s  关键帧 %d 个  absEvery=%d" % (cl["state"], len(times), aevery))
    setup = slots[nm][nm]["vertices"]
    n = len(setup) // 2
    dfr = ((sk["animations"].get(cl["state"]) or {}).get("deform")
           or {}).get("default", {}).get(nm, {}).get(nm) or []
    kmap = {}
    for fr in dfr:
        kmap[round(float(fr["time"]), 6)] = fr["vertices"]

    ri = next(i for i, r in enumerate(cl["renderers"])
              if r["path"].replace("\\", "/").endswith(a.part))
    data = cl["data"][ri]
    print("%8s %12s %22s %22s" % ("k", "t", "prod质心", "S*世界质心+报告T"))
    shown = 0
    rows = []
    for k, t in enumerate(times):
        if k % aevery:
            continue
        ai = k // aevery
        if ai >= len(data.get("absA") or []):
            break
        dv = kmap.get(round(float(t), 6))
        if dv is None:
            continue
        av = data["absA"][ai]
        m = data["l2w"][k]
        cx = cy = wx = wy = 0.0
        for i in range(n):
            cx += setup[2 * i] + dv[2 * i]
            cy += setup[2 * i + 1] + dv[2 * i + 1]
            w = mm3(m, (av[3 * i], av[3 * i + 1], av[3 * i + 2]))
            wx += w[0]
            wy += w[1]
        cx /= n; cy /= n; wx /= n; wy /= n
        rows.append((cx - (S[0][0] * wx + S[0][1] * wy),
                     cy - (S[1][0] * wx + S[1][1] * wy)))
        if shown < a.rows:
            print("%8d %12.3f (%9.2f,%9.2f) (%9.2f,%9.2f)  差=(%7.2f,%7.2f)"
                  % (k, t, cx, cy, S[0][0] * wx + S[0][1] * wy + T[0],
                     S[1][0] * wx + S[1][1] * wy + T[1],
                     cx - (S[0][0] * wx + S[0][1] * wy) - T[0],
                     cy - (S[1][0] * wx + S[1][1] * wy) - T[1]))
            shown += 1
    mx = sum(r[0] for r in rows) / len(rows)
    my = sum(r[1] for r in rows) / len(rows)
    sd = (sum((r[0] - mx) ** 2 + (r[1] - my) ** 2 for r in rows) / len(rows)) ** 0.5
    print()
    print("行数=%d  (产物 - S*世界) 的均值 = (%.3f,%.3f)  标准差 = %.3f px" % (len(rows), mx, my, sd))
    print("报告里的 T = (%.3f,%.3f)   与均值差 = (%.3f,%.3f)"
          % (T[0], T[1], mx - T[0], my - T[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
