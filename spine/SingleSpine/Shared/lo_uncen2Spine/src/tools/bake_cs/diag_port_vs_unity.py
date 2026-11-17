# -*- coding: utf-8 -*-
r"""把「移植版(--cs)产物 − 基线产物」的逐顶点位移，和「Unity 录制到的 delta」
直接对拍（都在部件局部空间，只需一个标量换算）。

目的：判定 Tep_1 / curtain 上尾巴的离群到底是谁错 ——
  · 移植版 ≈ Unity 录制 delta  ⇒ 移植版对，合并产物（把 delta 重采样到基线
    稀疏关键帧网格上）错；
  · 移植版和 Unity 录制 delta 都不像 ⇒ 移植版错。

用法:
    python diag_port_vs_unity.py --base <基线产物> --port <移植版产物> ^
        --merged <合并产物> --bake <state.json> --state Tep_1 ^
        --part parts_Tail_B parts_Tail_F
"""

import argparse
import io
import json
import math
import os


def load(p):
    with io.open(p, encoding="utf-8-sig") as fh:
        return json.load(fh)


def find_json(d):
    for fn in os.listdir(d):
        if fn.endswith("_static.json"):
            return os.path.join(d, fn)
    raise SystemExit("no _static.json in %s" % d)


def frames_of(prod, an, part):
    d = (prod["animations"].get(an, {}).get("deform") or {}).get("default") or {}
    if part not in d:
        return None
    sub = d[part]
    return sub[list(sub.keys())[0]]


def value_at(frames, t):
    if t <= frames[0]["time"]:
        return frames[0]["vertices"]
    if t >= frames[-1]["time"]:
        return frames[-1]["vertices"]
    for i in range(len(frames) - 1):
        if frames[i]["time"] <= t <= frames[i + 1]["time"]:
            sp = frames[i + 1]["time"] - frames[i]["time"]
            u = 0.0 if sp <= 1e-12 else (t - frames[i]["time"]) / sp
            return [a + (b - a) * u
                    for a, b in zip(frames[i]["vertices"],
                                    frames[i + 1]["vertices"])]
    return frames[-1]["vertices"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--port", required=True)
    ap.add_argument("--merged", default=None)
    ap.add_argument("--bake", required=True, help="录制片段 json")
    ap.add_argument("--state", required=True)
    ap.add_argument("--part", nargs="+", required=True)
    a = ap.parse_args()

    B = load(find_json(a.base))
    P = load(find_json(a.port))
    M = load(find_json(a.merged)) if a.merged else None
    bk = load(a.bake)
    kt = [float(t) for t in bk["keyTimes"]]
    ridx = {r["path"].split("/")[-1]: i for i, r in enumerate(bk["renderers"])}

    for part in a.part:
        fb = frames_of(B, a.state, part)
        fp = frames_of(P, a.state, part)
        fm = frames_of(M, a.state, part) if M else None
        if fb is None or fp is None:
            print("%s: 缺产物 deform" % part)
            continue
        # 录制数据里找同名渲染器（烘 json 里的名字不含槽位后缀 _29 之类）
        key = None
        for nm in ridx:
            if part.startswith(nm) or nm.startswith(part.split("_")[0]):
                if nm in part or part in nm:
                    key = nm
        if key is None:
            for nm in ridx:
                if nm.split("_")[1] == part.split("_")[1]:
                    key = nm
        if key is None:
            print("%s: 录制 json 里找不到对应渲染器（有：%s）"
                  % (part, list(ridx)))
            continue
        bi = ridx[key]
        n = bk["renderers"][bi]["n"]
        dat = bk["data"][bi]
        print("=" * 78)
        print("状态 %s  槽位 %s  (录制渲染器 %s, n=%d, 关键帧 %d)"
              % (a.state, part, key, n, len(kt)))

        # 逐关键帧：产物的 Δ(顶点空间, px) 与 录制 Δ(局部空间, 世界单位)
        pairs_p = []      # (port-base, unity)
        pairs_m = []
        for k in range(len(kt)):
            t = kt[k]
            b0 = value_at(fb, t)
            p0 = value_at(fp, t)
            if len(b0) != 2 * n or len(p0) != 2 * n:
                continue
            raw = dat["delta"][k] if k < len(dat["delta"]) else None
            if raw is None:
                continue
            for i in range(n):
                ux, uy = raw[3 * i], raw[3 * i + 1]
                pdx, pdy = p0[2 * i] - b0[2 * i], p0[2 * i + 1] - b0[2 * i + 1]
                pairs_p.append((pdx, pdy, ux, uy))
                if fm is not None:
                    m0 = value_at(fm, t)
                    if len(m0) == 2 * n:
                        pairs_m.append((m0[2 * i] - b0[2 * i],
                                        m0[2 * i + 1] - b0[2 * i + 1], ux, uy))

        def fit2x2(pairs, tag, matrix=None):
            """最小二乘求 2x2 矩阵 M： [px,py] ≈ M·[ux,uy]。

            拟合残差 = 产物位移与 Unity 记录位移（经固定线性映射）之差，
            是"两条路线的 CS 位移是否同一个向量场"的判据。
            """
            if not pairs:
                return None
            if matrix is None:
                # 正规方程：未知 (a,b,c,d)，px=a*ux+b*uy, py=c*ux+d*uy
                sxx = sum(p[2] * p[2] for p in pairs)
                sxy = sum(p[2] * p[3] for p in pairs)
                syy = sum(p[3] * p[3] for p in pairs)
                sxz = sum(p[2] * p[0] for p in pairs)
                syz = sum(p[3] * p[0] for p in pairs)
                sxw = sum(p[2] * p[1] for p in pairs)
                syw = sum(p[3] * p[1] for p in pairs)
                det = sxx * syy - sxy * sxy
                if abs(det) < 1e-12:
                    return None
                a = (sxz * syy - syz * sxy) / det
                b = (syz * sxx - sxz * sxy) / det
                c = (sxw * syy - syw * sxy) / det
                d = (syw * sxx - sxw * sxy) / det
                matrix = (a, b, c, d)
            a, b, c, d = matrix
            errs = []
            for p in pairs:
                errs.append(math.hypot(p[0] - (a * p[2] + b * p[3]),
                                       p[1] - (c * p[2] + d * p[3])))
            errs.sort()
            upx = sorted(math.hypot(p[2], p[3]) for p in pairs)
            print("  %-6s M=[[%8.2f,%8.2f],[%8.2f,%8.2f]]  残差 中位 %.3f / p90 %.3f / 最大 %.3f px"
                  % (tag, a, b, c, d, errs[len(errs) // 2],
                     errs[int(len(errs) * 0.9)], errs[-1]))
            print("         （Unity 记录 delta 幅值 中位 %.3f / 最大 %.3f 单位）"
                  % (upx[len(upx) // 2], upx[-1]))
            return matrix

        Mp = fit2x2(pairs_p, "移植")
        if pairs_m:
            fit2x2(pairs_m, "合并", Mp)

        # 每 0.5s 打一行：三者在该时刻的"尾端位移"对比
        dur = max(float(kt[-1]), fb[-1]["time"])
        print("  %-7s %11s %11s %11s %11s" % ("t", "unityΔpx", "移植Δpx",
                                              "合并Δpx", "移植-合并px"))
        t = 0.0
        kuse = None
        if Mp:
            a, b, c, d = Mp
            kuse = math.hypot(0.5 * (a + d), 0.5 * (c - b))
        if not kuse:
            kuse = 1.0
        while t <= dur + 1e-9:
            b0 = value_at(fb, t)
            p0 = value_at(fp, t)
            kk = min(range(len(kt)), key=lambda q: abs(kt[q] - t))
            raw = dat["delta"][kk]
            u = max(math.hypot(raw[3 * i], raw[3 * i + 1]) for i in range(n))
            dp = max(math.hypot(p0[2 * i] - b0[2 * i], p0[2 * i + 1] - b0[2 * i + 1])
                     for i in range(n))
            if fm is not None:
                m0 = value_at(fm, t)
                dm = max(math.hypot(m0[2 * i] - b0[2 * i], m0[2 * i + 1] - b0[2 * i + 1])
                         for i in range(n))
                dpm = max(math.hypot(p0[2 * i] - m0[2 * i], p0[2 * i + 1] - m0[2 * i + 1])
                          for i in range(n))
            else:
                dm = dpm = float("nan")
            print("  %-7.2f %11.1f %11.1f %11.1f %11.1f"
                  % (t, u * kuse, dp, dm, dpm))
            t += 0.5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
