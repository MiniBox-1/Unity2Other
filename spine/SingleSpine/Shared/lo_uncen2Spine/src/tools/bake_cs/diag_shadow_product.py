# -*- coding: utf-8 -*-
r"""把三个位置摆一起：**产物**（setup+deform）/ **Unity 播放中** / **Unity 静态姿态**，
都在产物像素空间（用 calib 的 S/T 换算），用来判断"影子位置不对"是
  · 产物根本没跟动画（≈ 静态那列），还是
  · 产物跟了但跟错了（既不是静态也不是播放）。

用法:
    python diag_shadow_product.py --product <产物目录> --anim breast --time 3.36 ^
        --verify <framedump_to_verify 生成的 verify.json> ^
        --calib <calib.json> [--static <静态 dump.jsonl>] [--grep Shadow]
"""

import argparse
import io
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from read_framedump import frame_at, obj_paths, read_dump  # noqa: E402


def load_json(p):
    with io.open(p, encoding="utf-8-sig") as fh:
        return json.load(fh)


def find_json(d):
    for fn in os.listdir(d):
        if fn.endswith("_static.json"):
            return os.path.join(d, fn)


def deform_at(frames, t):
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
            return [a + (b - a) * u for a, b in
                    zip(frames[i]["vertices"], frames[i + 1]["vertices"])]
    return frames[-1]["vertices"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--anim", required=True)
    ap.add_argument("--time", type=float, required=True)
    ap.add_argument("--verify", required=True)
    ap.add_argument("--calib", required=True)
    ap.add_argument("--static", default=None)
    ap.add_argument("--grep", default="Shadow")
    a = ap.parse_args()

    S = load_json(find_json(a.product))
    info = load_json(os.path.join(a.product, "_static_info.json"))
    cal = load_json(a.calib).get("calibration") or {}
    unit_k = float(info.get("unitScale") or 1.0)
    fx = -1.0 if info.get("flipX") else 1.0
    ox, oy = (info.get("origin") or [0.0, 0.0])[:2]
    A = S["animations"][a.anim]
    deform = (A.get("deform") or {}).get("default") or {}
    atts = S["skins"][0]["attachments"]
    meta = {m.get("name"): m for m in info.get("partsMeta") or []}

    vf = load_json(a.verify)
    st = None
    if a.static:
        ms, _ = read_dump(a.static)
        ns = obj_paths(ms)
        fs = frame_at(a.static, None, None)
        st = ({o["i"]: o for o in fs["obj"]}, ns)

    print("%-26s %-22s %-22s %-22s %8s" %
          ("part", "产物(px)", "Unity播放(px)", "Unity静态(px)", "产物-播放"))
    for r in vf["renderers"]:
        rel = r["path"]
        nm = None
        for m in (info.get("partsMeta") or []):
            if (m.get("path") or "").endswith(rel):
                nm = m["name"]
        if not nm:
            continue
        if a.grep and a.grep.lower() not in (rel or "").lower():
            continue
        an = nm if nm in atts[nm] else list(atts[nm].keys())[0]
        setup = atts[nm][an]["vertices"]
        n = len(setup) // 2
        if n != r["n"]:
            print("%-26s [顶点数不一致 %d/%d]" % (nm, n, r["n"]))
            continue
        d = deform_at((deform.get(nm) or {}).get(an), a.time) or [0.0] * (2 * n)
        pverts = [(setup[2 * k] + d[2 * k], setup[2 * k + 1] + d[2 * k + 1])
                  for k in range(n)]
        c = cal.get(nm) or {}
        SS = c.get("S") or [[fx * unit_k, 0.0], [0.0, unit_k]]
        TT = c.get("T") or [0.0, 0.0]
        pcx = sum(setup[2 * k] + d[2 * k] for k in range(n)) / n
        pcy = sum(setup[2 * k + 1] + d[2 * k + 1] for k in range(n)) / n

        def cen(verts3):
            m = r["l2w"]
            xs = []
            for v in verts3:
                wx = m[0] * v[0] + m[1] * v[1] + m[2] * v[2] + m[3]
                wy = m[4] * v[0] + m[5] * v[1] + m[6] * v[2] + m[7]
                xs.append((SS[0][0] * wx + SS[0][1] * wy + TT[0],
                           SS[1][0] * wx + SS[1][1] * wy + TT[1]))
            return (sum(p[0] for p in xs) / len(xs),
                    sum(p[1] for p in xs) / len(xs))

        ux, uy = cen(r["a"])
        # Unity 侧逐顶点 px（同一 S/T），再算**最近邻**距离 —— 顶点顺序不同时
        # 逐顶点差会很大但最近邻很小（用来区分"真的错位" vs "只是顺序不同"）
        m = r["l2w"]
        uverts = []
        for v in r["a"]:
            wx = m[0] * v[0] + m[1] * v[1] + m[2] * v[2] + m[3]
            wy = m[4] * v[0] + m[5] * v[1] + m[6] * v[2] + m[7]
            uverts.append((SS[0][0] * wx + SS[0][1] * wy + TT[0],
                           SS[1][0] * wx + SS[1][1] * wy + TT[1]))
        cx = sum(p[0] for p in pverts) / n
        cy = sum(p[1] for p in pverts) / n

        def nn_of(verts):
            v = []
            for p in verts:
                v.append(min(math.hypot(p[0] - q[0], p[1] - q[1])
                             for q in uverts))
            v.sort()
            return v

        nn = nn_of(pverts)
        best = ("原始", nn[-1], nn[len(nn) // 2])
        for tag, mx, my in (("翻X", True, False), ("翻Y", False, True),
                            ("翻XY", True, True)):
            mv = [((cx - (p[0] - cx)) if mx else p[0],
                   (cy - (p[1] - cy)) if my else p[1]) for p in pverts]
            v = nn_of(mv)
            if v[-1] < best[1]:
                best = (tag, v[-1], v[len(v) // 2])
        sx, sy = (None, None)
        if st:
            # 静态那份：用同一 l2w 不行（姿态不同），改用对象世界位置换算
            objs, names = st
            for i, o in objs.items():
                if names.get(i, "") == rel and o.get("pos"):
                    p = o["pos"]
                    sx = fx * unit_k * (p[0] - ox)
                    sy = unit_k * (p[1] - oy)
                    break
        e = math.hypot(pcx - ux, pcy - uy)
        es = "-" if sx is None else "%.1f" % math.hypot(pcx - sx, pcy - sy)
        print("%-26s (%8.1f,%8.1f)   (%8.1f,%8.1f)   %-22s %8.1f  最近邻(%s) 中位%.2f/最大%.2f"
              % (nm, pcx, pcy, ux, uy,
                 "-" if sx is None else "(%8.1f,%8.1f)" % (sx, sy), e,
                 best[0], best[2], best[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
