# -*- coding: utf-8 -*-
r"""揪出"合并量 != S*(B-A)"的真凶：逐部件比较
  bake.json 里的 delta（转世界）  vs  verify json 里的 (B-A)（转世界）。

用法:
    python diag_delta_match.py --bake <bake.json> --verify <verify_*.json> --state Start --time 3.0
"""

import argparse
import io
import json
import math
import sys


def load_json(p):
    with io.open(p, encoding="utf-8-sig") as fh:
        return json.load(fh)


def xf3(m, d):
    return (m[0] * d[0] + m[1] * d[1] + m[2] * d[2],
            m[4] * d[0] + m[5] * d[1] + m[6] * d[2])


def mm3(m, v):
    return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2] + m[3],
            m[4] * v[0] + m[5] * v[1] + m[6] * v[2] + m[7])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bake", required=True)
    ap.add_argument("--verify", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--time", type=float, required=True)
    a = ap.parse_args()

    bake = load_json(a.bake)
    vf = load_json(a.verify)
    cl = None
    for c in bake["clips"]:
        if c["state"] == a.state:
            cl = c
    times = cl["times"]
    k = min(range(len(times)), key=lambda i: abs(times[i] - a.time))
    print("bake state=%s 用第 %d 个关键帧 t=%.5f（目标 %.3f，差 %.2e s）"
          % (a.state, k, times[k], a.time, abs(times[k] - a.time)))
    print("%-22s %8s %10s %10s" % ("part", "verts", "中位", "最大"))
    print("-" * 56)
    tot = []
    for v in vf["renderers"]:
        leaf = v["path"].split("/")[-1]
        idx = None
        for i, r in enumerate(cl["renderers"]):
            if r["path"].replace("\\", "/").endswith(v["path"].replace("\\", "/")):
                idx = i
        if idx is None:
            print("%-22s   [bake 里没有这个部件]" % leaf)
            continue
        data = cl["data"][idx]
        d = data["delta"][k]
        m = data["l2w"][k]
        n = v["n"]
        errs = []
        for vi in range(n):
            wd = xf3(m, (d[3 * vi], d[3 * vi + 1], d[3 * vi + 2]))
            dw = (mm3(v["l2w"], v["b"][vi])[0] - mm3(v["l2w"], v["a"][vi])[0],
                  mm3(v["l2w"], v["b"][vi])[1] - mm3(v["l2w"], v["a"][vi])[1])
            errs.append(math.hypot(wd[0] - dw[0], wd[1] - dw[1]))
        errs.sort()
        tot += errs
        print("%-22s %8d %10.3e %10.3e"
              % (leaf, n, errs[len(errs) // 2], errs[-1]))
    tot.sort()
    print("汇总: 中位 %.3e / 最大 %.3e   (单位=世界单位；1 世界单位≈%d px)"
          % (tot[len(tot) // 2], tot[-1], 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
