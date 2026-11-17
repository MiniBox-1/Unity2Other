# -*- coding: utf-8 -*-
r"""对等比较：**产品里尾巴的形变变化量** vs **Unity 纯 clip 下尾巴的实际位移**。

两者用同一把尺子：
  产品   ：deform(f) - deform(0)          （都相对各自的首帧，消掉常量偏移）-> ×1 就是产物 px
  Unity  ：世界顶点(f) - 世界顶点(0)       -> ×unit_k 换成产物 px
如果产品说动 194px、Unity 说动 3px，那就是转换器自己把尾巴"编"动了。

用法:
    python cmp_tail_motion.py --product <基线产物> --dump-dir <partdump 目录> [--part parts_Tail_F]
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
    ap.add_argument("--dump-dir", required=True)
    ap.add_argument("--part", default="parts_Tail_F")
    a = ap.parse_args()

    info = load_json(os.path.join(a.product, "_static_info.json"))
    sk = load_json(find_json(a.product))
    unit_k = float(info["unitScale"])
    slots = sk["skins"][0]["attachments"]
    nm = None
    for m in info["partsMeta"]:
        if m["path"].endswith(a.part):
            nm = m["name"]

    print("部件 %s -> 产物槽位 %s   （1 px = %.5f 世界单位）" % (a.part, nm, 1.0 / unit_k))
    print("%-8s | %-26s | %-26s" % ("clip", "产品 deform 变化量(px)", "Unity 纯clip 位移(px)"))
    print("-" * 76)
    for fn in sorted(os.listdir(a.dump_dir)):
        if not fn.endswith("__A.json"):
            continue
        st = fn[: -len("__A.json")]
        d = load_json(os.path.join(a.dump_dir, fn))
        pi = None
        for i, p in enumerate(d["parts"]):
            if p["path"].replace("\\", "/").endswith(a.part):
                pi = i
        if pi is None:
            continue
        n = d["parts"][pi]["n"]
        base = None
        umax = 0.0
        for fr in d["frames"]:
            pd = fr["parts"][pi]
            m = pd["l2w"]
            vs = pd["verts"]
            w = [mm(m, (vs[3 * i], vs[3 * i + 1], vs[3 * i + 2])) for i in range(n)]
            if base is None:
                base = w
                continue
            umax = max(umax, max(math.hypot(w[i][0] - base[i][0], w[i][1] - base[i][1])
                                 for i in range(n)))
        # 产品侧
        fr = ((sk["animations"].get(st) or {}).get("deform") or {}).get("default", {})
        dfr = (fr.get(nm) or {}).get(nm) or []
        pmax = 0.0
        pmax_abs = 0.0
        if dfr:
            v0 = dfr[0]["vertices"]
            for f in dfr:
                vv = f["vertices"]
                pmax = max(pmax, max(math.hypot(vv[2 * i] - v0[2 * i],
                                                vv[2 * i + 1] - v0[2 * i + 1])
                                     for i in range(min(n, len(vv) // 2))))
                pmax_abs = max(pmax_abs,
                               max((math.hypot(vv[2 * i], vv[2 * i + 1])
                                    for i in range(min(n, len(vv) // 2))), default=0.0))
            pmax = sorted([max(math.hypot(f["vertices"][2 * i] - v0[2 * i],
                                          f["vertices"][2 * i + 1] - v0[2 * i + 1])
                               for i in range(min(n, len(v0) // 2))) for f in dfr])[-1]
        print("%-8s | 变化 %8.2f  （最大绝对值 %8.2f） | %8.2f"
              % (st, pmax, pmax_abs, umax * unit_k))
    return 0


if __name__ == "__main__":
    sys.exit(main())
