# -*- coding: utf-8 -*-
r"""DynamicBone **update2 逐项消融**：用 Unity dump 的"步前状态 + 输入 + 步后状态"，
试各种语义变体，看哪一种能把步后状态复现到 ~1e-6（= Unity 真实的写法）。

dump 每粒子 14 个数：[pos, prev, bonePos, target, n, parentIndex]
其中 target = m0·localPos，m0 = 父骨 localToWorldMatrix 但平移列换成**步前**的 p2.m_Position。
Unity 实际用的是 update1 之后的 p2.m_Position ⇒ target_real = target + (p1[p2] − p0[p2])。

用法: python diag_db_ablate.py --dump <dump.json> [--steps 20,100,300]
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


def step(fr, f, n, par, damping, elas, num2, variant, fresh):
    """返回本步每个粒子的 pos（列表）。variant 见 main。"""
    p0 = [list(fr[f - 1][i][0:3]) for i in range(n)]
    v0 = [list(fr[f - 1][i][3:6]) for i in range(n)]
    pos = [list(x) for x in p0]
    prev = [list(x) for x in v0]
    # ---- update1（inert=0、gravity/force=0 ⇒ 只剩阻尼项）
    for i in range(n):
        if i > 0:
            v = sub(pos[i], prev[i])
            prev[i] = list(pos[i])
            pos[i] = add(pos[i], mul(v, 1.0 - damping))
        else:
            prev[i] = list(pos[i])
            pos[i] = list(fr[f][i][6:9])          # = m_Transform.position
    p1 = [list(x) for x in pos]

    # ---- update2
    for i in range(1, n):
        bone_n = fr[f][i][12]
        if variant == "n_from_particles":
            bone_n = norm(sub(pos[par[i]], pos[i]))
        target = list(fr[f][i][9:12])
        if fresh:
            pi = par[i]
            target = add(target, sub(p1[pi], p0[pi]))
        if variant == "no_elasticity":
            pass
        else:
            v2 = sub(target, pos[i])
            pos[i] = add(pos[i], mul(v2, elas))
        if num2 > 0.0 and variant != "no_clamp":
            v2 = sub(target, pos[i])
            if variant == "clamp_old_v2":
                # 有些版本用"弹性前"的 v2 算 mag/num3（不重算）
                v2 = sub(target, [x for x in
                                  (add(p1[i], mul(sub(target, p1[i]), elas))
                                   if variant != "no_elasticity" else p1[i])])
            mag = norm(v2)
            num3 = bone_n * (1.0 - num2) * 2.0
            if variant == "clamp_always" or (mag > num3 and mag > 1e-12):
                pos[i] = add(pos[i], mul(v2, (mag - num3) / mag))
        if variant == "keep_before_elasticity":
            v3 = sub(pos[par[i]], pos[i])
            m2 = norm(v3)
            if m2 > 1e-12:
                pos[i] = add(pos[i], mul(v3, (m2 - bone_n) / m2))
            v2 = sub(target, pos[i])
            pos[i] = add(pos[i], mul(v2, elas))
        v3 = sub(pos[par[i]], pos[i])
        m2 = norm(v3)
        if m2 > 0.0 and variant != "no_keep":
            pos[i] = add(pos[i], mul(v3, (m2 - bone_n) / m2))
    return pos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True)
    ap.add_argument("--steps", default="20,100,300")
    a = ap.parse_args()
    U = json.load(io.open(a.dump, encoding="utf-8-sig"))
    fr = U["particles"][0]["frames"]
    n = U["particles"][0]["n"]
    par = [int(round(fr[0][i][13])) for i in range(n)]
    damping, elas, stiff, weight = 0.07, 0.03, 0.10, 1.0
    num2 = 1.0 + (stiff - 1.0) * weight

    variants = [("base(移植版: fresh target)", True, "base"),
                ("stale target", False, "base"),
                ("no clamp", True, "no_clamp"),
                ("clamp always", True, "clamp_always"),
                ("clamp 用不重算的 v2", True, "clamp_old_v2"),
                ("keep-length 在弹性前", True, "keep_before_elasticity"),
                ("无 keep-length", True, "no_keep"),
                ("n 用粒子距离而非骨距", True, "n_from_particles"),
                ("无弹性项", True, "no_elasticity")]
    steps = [int(x) for x in a.steps.split(",")]
    print("%-28s %s" % ("变体", " ".join("f%-6d" % f for f in steps)))
    for name, fresh, v in variants:
        row = []
        for f in steps:
            pos = step(fr, f, n, par, damping, elas, num2, v, fresh)
            e = max(math.dist(pos[i], fr[f][i][0:3]) for i in range(n))
            row.append("%8.2e" % e)
        print("%-28s %s" % (name, " ".join(row)))
    print()
    print("（数值 = 该变体预测的步后位置与 Unity dump 的步后位置的最大差，世界单位；"
          "粒子尺度≈0.35 ⇒ 1e-6≈0.0008px）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
