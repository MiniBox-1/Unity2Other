# -*- coding: utf-8 -*-
r"""纯公式对照的 **float32 版**：每步运算都按 np.float32 舍入（Unity 是 float32 数学），
用来验证"每步 2.4e-4 的残差"是不是 float32 舍入造成的。

用法: python diag_db_f32.py --dump <alice_db_particles.json> [--steps ...]
"""

import argparse
import io
import json
import math
import sys

import numpy as np

F = np.float32


def v3(x):
    return np.array(x, dtype=np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True)
    ap.add_argument("--steps", default="1,20,100,300")
    ap.add_argument("--damping", type=float, default=0.07)
    ap.add_argument("--elasticity", type=float, default=0.03)
    ap.add_argument("--stiffness", type=float, default=0.10)
    ap.add_argument("--weight", type=float, default=1.0)
    a = ap.parse_args()

    U = json.load(io.open(a.dump, encoding="utf-8-sig"))
    fr = U["particles"][0]["frames"]
    n = U["particles"][0]["n"]
    par = [int(round(fr[0][i][13])) for i in range(n)]
    num2 = F(F(1.0) + F(F(a.stiffness) - F(1.0)) * F(a.weight))
    one_minus_d = F(F(1.0) - F(a.damping))
    elas = F(a.elasticity)
    print("float32 版：damping=%.3f elasticity=%.3f stiffness=%.3f -> num2=%.3f"
          % (a.damping, a.elasticity, a.stiffness, float(num2)))
    worst = 0.0
    for f in [int(x) for x in a.steps.split(",")]:
        if f >= len(fr):
            continue
        pos = [v3(fr[f - 1][i][0:3]) for i in range(n)]
        prev = [v3(fr[f - 1][i][3:6]) for i in range(n)]
        pre = [v3(fr[f - 1][i][0:3]) for i in range(n)]
        for i in range(n):
            if i > 0:
                v = F(pos[i] - prev[i])
                prev[i] = pos[i].copy()
                pos[i] = F(pos[i] + F(v * one_minus_d))
            else:
                prev[i] = pos[i].copy()
                pos[i] = v3(fr[f][i][6:9])
        for i in range(1, n):
            bone_n = F(fr[f][i][12])
            target = v3(fr[f][i][9:12])
            pi = par[i]
            # Unity 用的是 update1 之后的父粒子位置（矩阵只差平移列）
            target = F(target + F(pos[pi] - pre[pi]))
            v2 = F(target - pos[i])
            pos[i] = F(pos[i] + F(v2 * elas))
            if num2 > F(0.0):
                v2 = F(target - pos[i])
                mag = F(np.sqrt(F(np.dot(v2, v2))))
                num3 = F(F(bone_n * F(F(1.0) - num2)) * F(2.0))
                if mag > num3:
                    pos[i] = F(pos[i] + F(v2 * F(F(mag - num3) / mag)))
            vvv = F(pos[pi] - pos[i])
            m2 = F(np.sqrt(F(np.dot(vvv, vvv))))
            if m2 > F(0.0):
                pos[i] = F(pos[i] + F(vvv * F(F(m2 - bone_n) / m2)))
        e = max(math.dist([float(x) for x in pos[i]], fr[f][i][0:3]) for i in range(n))
        worst = max(worst, e)
        print("  frame %-4d 一步后最大误差 %.3e" % (f, e))
    print("float32 版最大误差 %.6e（对照：double 版 2.45e-4）" % worst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
