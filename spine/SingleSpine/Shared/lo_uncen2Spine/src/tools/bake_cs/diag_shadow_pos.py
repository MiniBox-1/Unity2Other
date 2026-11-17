# -*- coding: utf-8 -*-
r"""比对两份 U2SFrameDump 里同一批物体的世界位置（找"影子位置不对"是
静态摆放错、还是动画/脚本动过）。

用法:
    python diag_shadow_pos.py --a <静态那份.jsonl> --b <播放中那份.jsonl> ^
        --b-time 1.667 --grep Shadow
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--a-time", type=float, default=None)
    ap.add_argument("--b-time", type=float, default=None)
    ap.add_argument("--grep", default="Shadow")
    a = ap.parse_args()

    ma, _ = read_dump(a.a)
    mb, _ = read_dump(a.b)
    na, nb = obj_paths(ma), obj_paths(mb)
    fa = frame_at(a.a, a.a_time, None)
    fb = frame_at(a.b, a.b_time, None)
    A = {o["i"]: o for o in fa["obj"]}
    B = {o["i"]: o for o in fb["obj"]}
    print("A %s  f=%s t=%.3f" % (os.path.basename(a.a), fa.get("f"),
                                 float(fa.get("t", 0))))
    print("B %s  f=%s t=%.3f" % (os.path.basename(a.b), fb.get("f"),
                                 float(fb.get("t", 0))))
    print("%-46s %-28s %-28s %8s" % ("obj", "A(静态) 世界位置", "B(播放) 世界位置", "Δ"))
    for i in sorted(A):
        p = na.get(i, "")
        if a.grep and a.grep.lower() not in p.lower():
            continue
        if i not in B:
            continue
        pa, pb = A[i].get("pos"), B[i].get("pos")
        if not pa or not pb:
            continue
        d = math.sqrt(sum((pa[k] - pb[k]) ** 2 for k in range(3)))
        print("%-46s (%7.3f,%7.3f,%7.3f)  (%7.3f,%7.3f,%7.3f)  %8.3f"
              % (p.split("/")[-1], pa[0], pa[1], pa[2],
                 pb[0], pb[1], pb[2], d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
