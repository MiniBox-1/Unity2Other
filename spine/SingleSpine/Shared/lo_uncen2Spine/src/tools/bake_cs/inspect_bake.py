# -*- coding: utf-8 -*-
r"""体检一个 bake.json：规模、每帧 delta 幅度、以及"delta 到底动了多少"。

用法:
    python inspect_bake.py <bake.json> [--top 12]
"""

import argparse
import io
import json
import math
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bake")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()

    d = json.load(io.open(a.bake, encoding="utf-8-sig"))
    print("prefab   : %s" % d.get("prefab"))
    print("unity    : %s   animator=%s   fps=%s" % (d.get("unity"), d.get("animator"), d.get("fps")))
    print("dynBones : %s" % ", ".join(b.get("root") or b.get("path") for b in d.get("dynBones", [])))
    print("file     : %.1f MB" % (os.path.getsize(a.bake) / 1048576.0))
    print()
    print("%-8s %-26s %6s %8s %10s %10s" % ("state", "renderer", "verts", "frames", "max|d|", "mean|d|"))
    rends = d.get("renderers", [])
    for cl in d.get("clips", []):
        for ri, r in enumerate(cl.get("data", [])):
            rname = rends[ri]["path"].split("/")[-1] if ri < len(rends) else "?"
            n = 0
            mx = 0.0
            acc = 0.0
            cnt = 0
            for fr in r.get("delta", []):
                n = len(fr) // 2
                for k in range(0, len(fr), 2):
                    m = math.hypot(fr[k], fr[k + 1])
                    mx = max(mx, m)
                    acc += m
                    cnt += 1
            mean = acc / cnt if cnt else 0.0
            print("%-8s %-26s %6d %8d %10.5f %10.5f"
                  % (cl["state"], rname, n,
                     len(r.get("delta", [])), mx, mean))
    print()
    print("单位 = Unity 世界单位（1 单位 ≈ 732.6 px / unitScale）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
