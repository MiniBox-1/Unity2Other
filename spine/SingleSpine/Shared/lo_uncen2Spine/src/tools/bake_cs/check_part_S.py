# -*- coding: utf-8 -*-
r"""用 PartDataExport 导出的"纯 clip 逐帧部件数据"检验坐标映射口径。

要回答的问题：产物顶点 = S * (Unity 世界顶点) + T 里，S 到底
   (a) 全局一个（各部件共用），还是
   (b) 逐部件 = unit_k / |渲染器 lossyScale| ？

做法（对每个部件）：
  Unity 姿态  w(t,i) = l2w(t) * verts(t,i)            （3 维局部 -> 世界）
  产物姿态    p(t,i) = setup[i] + deform(t)[i]        （产物像素）
  对 (a) 用从 merge_report 拿到的全局 S；对 (b) 用 unit_k/lossyScale；
  各自只解一个平移 T，然后报逐顶点残差。

用法:
    python check_part_S.py --dump <partdump 目录>\<state>__A.json \
        --product <基线产物目录> [--report <merge_report.json>]
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


def mat_vec(m, v):
    return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2] + m[3],
            m[4] * v[0] + m[5] * v[1] + m[6] * v[2] + m[7])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True)
    ap.add_argument("--product", required=True)
    ap.add_argument("--report", default=None)
    a = ap.parse_args()

    dump = load_json(a.dump)
    info = load_json(os.path.join(a.product, "_static_info.json"))
    sk = load_json(find_json(a.product))
    unit_k = float(info["unitScale"])
    slots = sk["skins"][0]["attachments"]
    state = dump["state"]
    times = dump["times"]
    parts = dump["parts"]
    frames = dump["frames"]
    meta = info["partsMeta"]

    glS = None
    if a.report and os.path.isfile(a.report):
        rp = load_json(a.report)
        glS = None
        for nm, c in (rp.get("calibration") or {}).items():
            if c and c.get("S"):
                glS = c["S"]
                break

    if glS:
        print("全局 S（来自 %s）= [[%.3f,%.3f],[%.3f,%.3f]]"
              % (os.path.basename(a.report), glS[0][0], glS[0][1], glS[1][0], glS[1][1]))
    print("state=%s  帧=%d  部件=%d  1px=%.5f 世界单位\n"
          % (state, len(frames), len(parts), 1.0 / unit_k))

    # 产物侧：setup + deform(t)
    dfrd = ((sk["animations"].get(state) or {}).get("deform")
            or {}).get("default") or {}

    def prod_pose(nm, an, t):
        setup = slots[nm][an]["vertices"]
        n = len(setup) // 2
        fr = (dfrd.get(nm) or {}).get(an)
        dv = [0.0] * (2 * n)
        if fr:
            if t <= fr[0]["time"]:
                dv = fr[0]["vertices"]
            elif t >= fr[-1]["time"]:
                dv = fr[-1]["vertices"]
            else:
                for i in range(len(fr) - 1):
                    if fr[i]["time"] <= t <= fr[i + 1]["time"]:
                        span = fr[i + 1]["time"] - fr[i]["time"]
                        u = 0.0 if span <= 1e-12 else (t - fr[i]["time"]) / span
                        dv = [x + (y - x) * u for x, y in zip(fr[i]["vertices"],
                                                              fr[i + 1]["vertices"])]
                        break
        return setup, dv, n

    print("%-20s %6s %10s | %-22s | %-22s"
          % ("部件", "顶点", "lossy", "全局S 残差 中位/最大", "unit_k/lossy 残差 中位/最大"))
    print("-" * 96)
    for pi, p in enumerate(parts):
        rel = p["path"].replace("\\", "/")
        leaf = rel.split("/")[-1]
        nm = None
        for m in meta:
            if (m.get("path") or "").endswith(rel) and m.get("kind") == p["kind"]:
                nm = m["name"]
        if nm is None or nm not in slots:
            print("%-20s   [产物里没有对应槽位]" % leaf)
            continue
        an = nm if nm in slots[nm] else list(slots[nm].keys())[0]
        n = p["n"]
        ls = p["lossyScale"][0]
        S2 = [[unit_k / abs(ls), 0.0], [0.0, unit_k / abs(ls)]] if ls else None
        res = {"gl": [], "ls": []}
        for f, fr in enumerate(frames):
            t = times[f] if f < len(times) else fr["t"]
            setup, dv, nn = prod_pose(nm, an, t)
            if nn != n:
                continue
            pd = fr["parts"][pi]
            m = pd["l2w"]
            acc = {"gl": [0.0, 0.0], "ls": [0.0, 0.0]}
            pairs = {"gl": [], "ls": []}
            for i in range(n):
                v = (pd["verts"][3 * i], pd["verts"][3 * i + 1], pd["verts"][3 * i + 2])
                w = mat_vec(m, v)
                px = setup[2 * i] + dv[2 * i]
                py = setup[2 * i + 1] + dv[2 * i + 1]
                for key, S in (("gl", glS), ("ls", S2)):
                    if S is None:
                        continue
                    tx = S[0][0] * w[0] + S[0][1] * w[1]
                    ty = S[1][0] * w[0] + S[1][1] * w[1]
                    pairs[key].append((tx, ty, px, py))
            for key in ("gl", "ls"):
                if not pairs[key]:
                    continue
                ox = sum(q[2] - q[0] for q in pairs[key]) / len(pairs[key])
                oy = sum(q[3] - q[1] for q in pairs[key]) / len(pairs[key])
                e = [math.hypot(q[2] - (q[0] + ox), q[3] - (q[1] + oy))
                     for q in pairs[key]]
                e.sort()
                res[key].append((e[len(e) // 2], e[-1]))
        def fmt(v):
            if not v:
                return "%10s %10s" % ("-", "-")
            med = sorted(x[0] for x in v)[len(v) // 2]
            mx = max(x[1] for x in v)
            return "%10.4f %10.4f" % (med, mx)
        print("%-20s %6d %10.5f | %s | %s"
              % (leaf, n, ls, fmt(res["gl"]), fmt(res["ls"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
