# -*- coding: utf-8 -*-
r"""定位某个部件「基线产物 vs Unity 纯 clip 真值」的偏差形状。

做法：取 setup 时刻（t=0，deform 应为 0）
    产物姿态  prod = setup + deform(0)
    Unity 姿态 w   = l2w * absA(0)      （3 维局部顶点 -> 世界）
    标定后目标 tgt = S*w + T
    误差 e = prod - tgt
然后回答三个问题：
  1 e 是常量偏移（那只是 T 没标好）还是随顶点变化（真·几何不一致）？
  2 去掉"最佳相似变换"后还剩多少（是刚性差 vs 形变差）？
  3 误差大的顶点落在网格的哪个区域（用局部 x/z 分布看）？

用法:
    python diag_part_err.py --product <基线产物> --bake <bake.json>
        --report <merge_report.json> --part parts_Body [--top 10]
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


def solve3(M, V):
    M = [list(r) for r in M]
    V = list(V)
    for i in range(3):
        p = max(range(i, 3), key=lambda z: abs(M[z][i]))
        if abs(M[p][i]) < 1e-12:
            return None
        M[i], M[p] = M[p], M[i]
        V[i], V[p] = V[p], V[i]
        for j in range(i + 1, 3):
            f = M[j][i] / M[i][i]
            for q in range(i, 3):
                M[j][q] -= f * M[i][q]
            V[j] -= f * V[i]
    s = [0.0, 0.0, 0.0]
    for i in (2, 1, 0):
        s[i] = (V[i] - sum(M[i][q] * s[q] for q in range(i + 1, 3))) / M[i][i]
    return s


def sq_from_to(rows):
    """最小二乘拟合 目标 = A*源（2x2 + 平移），rows=[(sx,sy,tx,ty)]，返回 (A,最大残差)。"""
    Mt = [[0.0] * 3 for _ in range(3)]
    Vx = [0.0] * 3
    Vy = [0.0] * 3
    for (sx, sy, tx, ty) in rows:
        a3 = (sx, sy, 1.0)
        for p in range(3):
            for q in range(3):
                Mt[p][q] += a3[p] * a3[q]
            Vx[p] += a3[p] * tx
            Vy[p] += a3[p] * ty
    cx = solve3(Mt, Vx)
    cy = solve3(Mt, Vy)
    if cx is None or cy is None:
        return None, None
    mx = max(abs(cx[0] * sx + cx[1] * sy + cx[2] - tx) for sx, sy, tx, ty in rows)
    my = max(abs(cy[0] * sx + cy[1] * sy + cy[2] - ty) for sx, sy, tx, ty in rows)
    return (cx, cy), max(mx, my)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--bake", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--part", required=True)
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()

    info = load_json(os.path.join(a.product, "_static_info.json"))
    sk = load_json(find_json(a.product))
    bake = load_json(a.bake)
    rep = load_json(a.report)
    unit_k = float(info["unitScale"])
    slots = sk["skins"][0]["attachments"]
    calib = rep["calibration"]

    nm = None
    for m in info["partsMeta"]:
        if m["path"].endswith(a.part) and m["kind"] == "skinned":
            nm = m["name"]
    if nm is None:
        raise SystemExit("产物里找不到 skinned 部件 " + a.part)
    an = nm if nm in slots[nm] else list(slots[nm].keys())[0]
    setup = slots[nm][an]["vertices"]
    n = len(setup) // 2
    S = calib[nm]["S"]
    T = calib[nm]["T"] or [0.0, 0.0]
    print("部件 %s slot=%s 顶点=%d  S=[[%.2f,%.2f],[%.2f,%.2f]] T=(%.2f,%.2f) 1px=%.5f 世界单位"
          % (a.part, nm, n, S[0][0], S[0][1], S[1][0], S[1][1], T[0], T[1], 1.0 / unit_k))

    clip = None
    for c in bake["clips"]:
        if c["state"] == bake["clips"][0].get("absState") or c.get("absState") == c["state"]:
            clip = c
    if clip is None:
        raise SystemExit("bake 里没有带 absA 的 clip")
    print("用 absA 所在 clip: %s（t=0，deform 应为 0）" % clip["state"])
    ri = None
    for i, r in enumerate(clip["renderers"]):
        if r["path"].replace("\\", "/").endswith(a.part):
            ri = i
    data = clip["data"][ri]
    av = data["absA"][0]
    m = data["l2w"][0]
    dfr = ((sk["animations"].get(clip["state"]) or {}).get("deform")
           or {}).get("default", {}).get(nm, {}).get(an) or []
    dv = dfr[0]["vertices"] if dfr and abs(dfr[0]["time"]) < 1e-9 else [0.0] * (2 * n)

    rows = []
    errs = []
    for i in range(n):
        px = setup[2 * i] + dv[2 * i]
        py = setup[2 * i + 1] + dv[2 * i + 1]
        lx, ly, lz = av[3 * i], av[3 * i + 1], av[3 * i + 2]
        wx = m[0] * lx + m[1] * ly + m[2] * lz + m[3]
        wy = m[4] * lx + m[5] * ly + m[6] * lz + m[7]
        tx = S[0][0] * wx + S[0][1] * wy + T[0]
        ty = S[1][0] * wx + S[1][1] * wy + T[1]
        errs.append((math.hypot(px - tx, py - ty), px - tx, py - ty, lx, lz))
        rows.append((wx, wy, px, py))

    d = sorted(e[0] for e in errs)
    print()
    print("原始误差 |产物 - 标定后Unity|:  中位 %.2f px / p90 %.2f / 最大 %.2f"
          % (d[len(d) // 2], d[int(len(d) * 0.9)], d[-1]))
    meanx = sum(e[1] for e in errs) / n
    meany = sum(e[2] for e in errs) / n
    varx = sum((e[1] - meanx) ** 2 for e in errs) / n
    vary = sum((e[2] - meany) ** 2 for e in errs) / n
    print("误差均值 (%+.2f,%+.2f)  标准差 (%.2f,%.2f)  → %s"
          % (meanx, meany, math.sqrt(varx), math.sqrt(vary),
             "基本是常量偏移（标定问题）" if math.sqrt(varx + vary) < 2.0
             else "随顶点变化（真·几何不一致）"))
    r2 = sorted(e[0] for e in errs)
    print("去均值后 |误差|: 中位 %.2f / 最大 %.2f px"
          % (r2[len(r2) // 2] * 0 + sorted(math.hypot(e[1] - meanx, e[2] - meany)
                                           for e in errs)[len(errs) // 2],
             max(math.hypot(e[1] - meanx, e[2] - meany) for e in errs)))

    sq, sqmax = sq_from_to(rows)
    if sq:
        cx, cy = sq
        print("单独为这个部件重新拟合（2x2+平移）后 最大残差 %.4f px" % sqmax)
        print("   拟合 A = [[%9.3f,%8.3f],[%9.3f,%9.3f]]  b = (%9.3f,%9.3f)"
              % (cx[0], cx[1], cy[0], cy[1], cx[2], cy[2]))
        print("   全局 S = [[%9.3f,%8.3f],[%9.3f,%9.3f]]" % (S[0][0], S[0][1], S[1][0], S[1][1]))
        r = None
        for rr in clip["renderers"]:
            if rr["path"].replace("\\", "/").endswith(a.part):
                r = rr
        if r:
            ls = r.get("lossyScale")
            print("   渲染器 lossyScale = %s -> unit_k/lossy = %s"
                  % (ls, [round(unit_k / abs(v), 1) if v else None for v in (ls or [])]))

    print()
    print("误差最大的 %d 个顶点（局部 x/z 用来判断落在网格哪个区域）:" % a.top)
    print("  %5s %10s %10s %10s %10s" % ("#", "|e|px", "e.x", "e.y", "局部(x,z)"))
    for (mag, ex, ey, lx, lz) in sorted(errs, key=lambda e: -e[0])[:a.top]:
        print("  %5d %10.2f %10.2f %10.2f   (%8.3f,%8.3f)" % (0, mag, ex, ey, lx, lz))
    return 0


if __name__ == "__main__":
    sys.exit(main())
