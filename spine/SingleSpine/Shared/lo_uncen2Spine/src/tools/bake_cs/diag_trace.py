# -*- coding: utf-8 -*-
r"""对比某个部件在整条动画上的「产物质心」与「Unity 世界质心」，看是不是稳定仿射。

用法:
    python diag_trace.py --product <产物> --bake <bake.json> --part parts_L_hair --state lobby
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


def mm(m, v):
    return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2] + m[3],
            m[4] * v[0] + m[5] * v[1] + m[6] * v[2] + m[7])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--bake", required=True)
    ap.add_argument("--part", default="parts_L_hair")
    ap.add_argument("--state", default="lobby")
    ap.add_argument("--every", type=int, default=15)
    a = ap.parse_args()

    info = load_json(os.path.join(a.product, "_static_info.json"))
    sk = load_json(find_json(a.product))
    bake = load_json(a.bake)
    unit_k = float(info["unitScale"])

    nm = None
    for m in info["partsMeta"]:
        if m["path"].endswith(a.part) and m["kind"] == "skinned":
            nm = m["name"]
    ri = None
    for i, r in enumerate(bake["renderers"]):
        if r["path"].endswith(a.part):
            ri = i
    cl = None
    for c in bake["clips"]:
        if c["state"] == a.state:
            cl = c
    data = cl["data"][ri]
    setup = sk["skins"][0]["attachments"][nm][nm]["vertices"]
    dfr = sk["animations"][a.state]["deform"]["default"][nm][nm]
    dt = 1.0 / float(bake["fps"])
    n = len(setup) // 2

    print("part=%s slot=%s n=%d state=%s  keys=%d  fps=%s"
          % (a.part, nm, n, a.state, len(dfr), bake["fps"]))
    print("%8s | %-24s | %-24s | %-24s" % ("t", "产物质心", "unity世界质心", "world*(u/ls)"))
    ls = bake["renderers"][ri].get("lossyScale")
    s = unit_k / ls[0] if ls and ls[0] else unit_k
    for k in range(0, len(dfr), a.every):
        t = dfr[k]["time"]
        fi = int(round(t / dt))
        if fi >= len(data["absA"]):
            break
        av = data["absA"][fi]
        m = data["l2w"][fi]
        cx = cy = 0.0
        wx = wy = 0.0
        for i in range(n):
            cx += setup[2 * i] + dfr[k]["vertices"][2 * i]
            cy += setup[2 * i + 1] + dfr[k]["vertices"][2 * i + 1]
            w = mm(m, (av[2 * i], av[2 * i + 1], 0.0))
            wx += w[0]
            wy += w[1]
        print("%8.3f | %11.3f %11.3f | %11.5f %11.5f | %11.3f %11.3f"
              % (t, cx / n, cy / n, wx / n, wy / n, wx / n * s, wy / n * s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
