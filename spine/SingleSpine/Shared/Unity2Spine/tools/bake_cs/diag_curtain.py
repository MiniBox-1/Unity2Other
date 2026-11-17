# -*- coding: utf-8 -*-
r"""对比三条产物在指定动画/槽位上的 deform（顶点位移）逐帧幅度。

用途：定位"移植版 --cs"在 curtain 上的尾巴离群 —— 到底是
  ① 移植版多施加了脚本形变，还是
  ② 合并版漏烘了脚本形变。

用法:
    python diag_curtain.py --an 3P_Alice_NS1_curtain --part parts_Tail_F_29 ^
        --baseline <基线产物> --merged <合并产物> --port <移植版产物>
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
    d = (prod["animations"].get(an, {}).get("deform") or {})
    d = d.get("default") or {}
    if part not in d:
        return None
    sub = d[part]
    return sub[list(sub.keys())[0]]


def disp_list(frames):
    """把每帧 vertices 与首帧作差，返回 [(time, max_disp, rms)]。"""
    if not frames:
        return []
    base = frames[0]["vertices"]
    out = []
    for f in frames:
        v = f["vertices"]
        if len(v) != len(base):
            out.append((f["time"], float("nan"), float("nan")))
            continue
        ds = [math.hypot(v[i] - base[i], v[i + 1] - base[i + 1])
              for i in range(0, len(v) - 1, 2)]
        ds.sort()
        out.append((f["time"], ds[-1], ds[len(ds) // 2]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--merged", required=True)
    ap.add_argument("--port", required=True)
    ap.add_argument("--an", required=True)
    ap.add_argument("--part", action="append", required=True)
    a = ap.parse_args()

    P = {"基线": load(find_json(a.baseline)),
         "合并": load(find_json(a.merged)),
         "移植": load(find_json(a.port))}

    for part in a.part:
        print("=" * 78)
        print("动画 %s  槽位 %s" % (a.an, part))
        series = {}
        for tag, prod in P.items():
            fr = frames_of(prod, a.an, part)
            series[tag] = disp_list(fr)
            if fr is None:
                print("  %-4s: 无 deform 记录" % tag)
                continue
            d = series[tag]
            mx = max((x[1] for x in d), default=0.0)
            print("  %-4s: %d 帧  相对首帧 最大位移 %.3f px" % (tag, len(fr), mx))
        keys = [t for t in P]
        if any(series[k] for k in keys):
            ts = sorted(set([x[0] for k in keys for x in series[k]]))
            print("  %-8s %10s %10s %10s" % ("时间", "基线", "合并", "移植"))
            for t in ts:
                row = []
                for k in keys:
                    v = [x for x in series[k] if abs(x[0] - t) < 1e-6]
                    row.append("%9.3f" % v[0][1] if v else "        -")
                print("  %-8.3f %s" % (t, " ".join(row)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
