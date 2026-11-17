# -*- coding: utf-8 -*-
r"""**纯公式测试**：用 Unity 自己 dump 的每步输入（bonePos / target / n）
在 Unity 的空间里跑一遍移植版的公式，看一步之后能不能复现 Unity 的下一帧状态。

这样彻底绕开"坐标映射"带来的循环论证 —— 残差≈0 就说明公式完全正确、
之前那 ~8% 全部来自坐标映射；残差还在就说明这一步的公式确实有差异。

dump 每条粒子每帧 14 个数：
    [pos(3), prev(3), bonePos(3), target(3), n(1), parentIndex(1)]

用法:
    python diag_db_formula.py --dump <alice_db_particles.json> [--steps 1,2,5,20,100]
"""

import argparse
import io
import json
import math
import sys


def sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def add(a, b):
    return [a[i] + b[i] for i in range(3)]


def mul(a, k):
    return [a[i] * k for i in range(3)]


def norm(a):
    return math.sqrt(sum(c * c for c in a))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True)
    ap.add_argument("--steps", default="1,2,5,20,100,300")
    ap.add_argument("--damping", type=float, default=0.07)
    ap.add_argument("--elasticity", type=float, default=0.03)
    ap.add_argument("--stiffness", type=float, default=0.10)
    ap.add_argument("--weight", type=float, default=1.0)
    ap.add_argument("--verbose-frame", type=int, default=-1)
    ap.add_argument("--fresh-target", action="store_true",
                    help="按 Unity 的真实顺序算 target：先 update1，再用"
                         "「步前 target + (父粒子 update1 后 − 步前)」平移修正")
    a = ap.parse_args()

    U = json.load(io.open(a.dump, encoding="utf-8-sig"))
    fr = U["particles"][0]["frames"]
    n = U["particles"][0]["n"]
    par = [int(round(fr[0][i][13])) for i in range(n)]
    num2 = 1.0 + (a.stiffness - 1.0) * a.weight
    print("粒子链父索引: %s" % par)
    print("参数：damping=%.3f elasticity=%.3f stiffness=%.3f weight=%.2f -> num2=%.3f"
          % (a.damping, a.elasticity, a.stiffness, a.weight, num2))
    print()
    print("%7s | %-20s | %-20s" % ("frame", "粒子0 一步后误差", "全部粒子 一步后最大误差"))
    print("-" * 62)
    worst = 0.0
    for f in [int(x) for x in a.steps.split(",")]:
        if f >= len(fr):
            continue
        pos = [list(fr[f - 1][i][0:3]) for i in range(n)]
        prev = [list(fr[f - 1][i][3:6]) for i in range(n)]
        pre = [list(fr[f - 1][i][0:3]) for i in range(n)]      # 步前位置（算平移用）
        for i in range(n):
            if i > 0:
                v = sub(pos[i], prev[i])
                prev[i] = list(pos[i])
                pos[i] = add(pos[i], mul(v, 1.0 - a.damping))
            else:
                prev[i] = list(pos[i])
                pos[i] = list(fr[f][i][6:9])
        for i in range(1, n):
            bone_n = fr[f][i][12]
            target = list(fr[f][i][9:12])
            if a.fresh_target:
                pi0 = par[i]
                # target 只在"父粒子的平移列"上不同 ⇒ 平移差即可
                target = add(target, sub(pos[pi0], pre[pi0]))
            v2 = sub(target, pos[i])
            pos[i] = add(pos[i], mul(v2, a.elasticity))
            if num2 > 0.0:
                v2 = sub(target, pos[i])
                mag = norm(v2)
                num3 = bone_n * (1.0 - num2) * 2.0
                if mag > num3 and mag > 1e-12:
                    pos[i] = add(pos[i], mul(v2, (mag - num3) / mag))
            pi = par[i]
            v3 = sub(pos[pi], pos[i])
            m2 = norm(v3)
            if m2 > 1e-12:
                pos[i] = add(pos[i], mul(v3, (m2 - bone_n) / m2))
        e0 = math.dist(pos[0], fr[f][0][0:3])
        em = max(math.dist(pos[i], fr[f][i][0:3]) for i in range(n))
        worst = max(worst, em)
        print("%7d | %-20.3e | %-20.3e" % (f, e0, em))
        if f == a.verbose_frame:
            print("  逐粒子（%s）:" % f)
            for i in range(n):
                st = fr[f - 1][i]
                cur = fr[f][i]
                print("   i=%d parent=%d" % (i, par[i]))
                print("      in  pos=(%.7f,%.7f,%.7f) prev=(%.7f,%.7f,%.7f)"
                      % (st[0], st[1], st[2], st[3], st[4], st[5]))
                print("      in  bone=(%.7f,%.7f,%.7f) target=(%.7f,%.7f,%.7f) n=%.7f"
                      % (cur[6], cur[7], cur[8], cur[9], cur[10], cur[11], cur[12]))
                print("      Unity out=(%.7f,%.7f,%.7f)   我 out=(%.7f,%.7f,%.7f)  差=%.3e"
                      % (cur[0], cur[1], cur[2], pos[i][0], pos[i][1], pos[i][2],
                         math.dist(pos[i], cur[0:3])))
    print()
    print("最大误差 %.6e（世界单位；粒子尺度约 0.35）" % worst)
    if worst < 1e-6:
        print("==> 公式完全正确：之前那 ~8% 全部来自坐标映射，不是物理。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
