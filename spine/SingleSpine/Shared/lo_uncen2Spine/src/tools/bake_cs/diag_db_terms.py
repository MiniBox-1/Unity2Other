# -*- coding: utf-8 -*-
r"""把 DynamicBone 的**一步**拆成逐项，找出到底哪一项和 Unity 对不上。

做法（全部在转换器坐标系里做，Unity 的状态用仿射映射搬进来）：
  1 从 Unity 的 f=0 状态出发（= 静止姿态）
  2 按 C# 源码的手算一遍"预测值"：v=pos-prev -> 弹力 3% -> 1.8n 约束 -> 骨长约束
  3 把 Unity 的 f=1 和移植版的 f=1 都拿来和预测值比
  哪一侧离预测远，问题就在哪一项。

用法:
    python diag_db_terms.py --prefab <prefab> --assets <Assets> --dump <db_particles.json>
"""
# --- lo_uncen2Spine: 位置解析（自动插入，见 src/tools\deabs_paths.py）------
import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while _ROOT and not _os.path.isdir(_os.path.join(_ROOT, 'unity2spine')):
    _ROOT = _os.path.dirname(_ROOT)
if _ROOT and _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from unity2spine.env import resolve as _resolve  # noqa: E402
from unity2spine.console import fix_console as _fix_console  # noqa: E402
_fix_console()
# ---------------------------------------------------------------------


import argparse
import io
import json
import math
import os
import sys


from unity2spine.convert.static_prefab_spine import (  # noqa: E402
    load_character, enumerate_clips, make_samplers, assignments_for_entry, trs_mat)
from unity2spine.convert.convert_2dmodel import _world_matrices  # noqa: E402
from unity2spine.convert.cs_runtime import (  # noqa: E402
    parse_cs_components, build_runtime, setup_dynamics, run_global_control,
    step_dynamics, parse_transform_child_order, mat4_pos, _dist)
from validate_cs_port import sample_local_world  # noqa: E402
from diag_db_step import fit_affine, apply_affine  # noqa: E402


def sub(a, b):
    return tuple(a[i] - b[i] for i in range(3))


def add(a, b):
    return tuple(a[i] + b[i] for i in range(3))


def mul(a, k):
    return tuple(a[i] * k for i in range(3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefab", required=True)
    ap.add_argument("--assets", required=True)
    ap.add_argument("--dump", required=True)
    ap.add_argument("--state", default="breast")
    a = ap.parse_args()

    U = json.load(io.open(a.dump, encoding="utf-8-sig"))
    ufr = U["particles"][0]["frames"]
    n = U["particles"][0]["n"]

    mdl, parts = load_character(a.prefab, a.assets, None, animated_only=True)
    mdl.cs_child_order = parse_transform_child_order(a.prefab)
    es = enumerate_clips(mdl, a.assets)
    ent = next(e for e in es if e["state"] == a.state)
    assign = assignments_for_entry(mdl, make_samplers(mdl, es), es, ent)
    comps = parse_cs_components(a.prefab, a.assets)
    lv_rest = {t: trs_mat(td["pos"], td["quat"], td["scale"])
               for t, td in mdl.transforms.items()}
    rt, drv = build_runtime(mdl, comps, lv_rest, _world_matrices(mdl, lv_rest), a.prefab)
    setup_dynamics(rt, drv)
    db = drv["bones"][0]
    dt = 1.0 / float(U.get("fps") or 60.0)

    # 跑一整遍拿映射
    mine = []
    for f in range(len(ufr)):
        lv, world = sample_local_world(mdl, assign, f * dt)
        rt.local = lv
        rt.world = world
        run_global_control(rt, drv)
        step_dynamics(rt, drv, dt)
        mine.append([p.pos for p in db.particles])
    pairs = [(mine[f][i], tuple(ufr[f][i][0:3]))
             for f in range(len(ufr)) for i in range(n)]
    rows = fit_affine(pairs)
    inv = fit_affine([(d, s) for (s, d) in pairs])

    # 从 Unity f=0 出发，手算一步
    f = 1
    lv, world = sample_local_world(mdl, assign, f * dt)
    rt.local = lv
    rt.world = world
    run_global_control(rt, drv)
    # 把粒子设成 Unity f=0（映射到我的坐标系）
    for i in range(n):
        u = ufr[0][i]
        db.particles[i].pos = apply_affine(inv, (u[0], u[1], u[2]))
        db.particles[i].prev = apply_affine(inv, (u[3], u[4], u[5]))
    state0 = [p.pos for p in db.particles]
    print("弹力=%.3f  刚度权重 num2=%.3f  骨长约束前的阈值 = 1.8n"
          % (db.elasticity, 1.0 + (db.stiffness - 1.0) * db.weight))
    print()
    print("%3s %-25s %-25s %-25s" % ("i", "pos0 = Unity f0", "Unity 实际 f1", "按公式预测的 f1"))
    print("%3s %-25s %-25s %-25s" % ("", "", "", "（差 = 我的公式与 Unity 的差别）"))
    pred_all = []
    for i in range(1, n):
        p = db.particles[i]
        p2 = db.particles[p.parent]
        # target：父骨世界矩阵（平移换成 p2.pos）作用到子骨 localPosition
        m = list(rt.world[p2.tf])
        m[3], m[7], m[11] = p2.pos
        lp = mat4_pos(rt.local[p.tf])
        target = (m[0] * lp[0] + m[1] * lp[1] + m[2] * lp[2] + m[3],
                  m[4] * lp[0] + m[5] * lp[1] + m[6] * lp[2] + m[7],
                  m[8] * lp[0] + m[9] * lp[1] + m[10] * lp[2] + m[11])
        bone_n = _dist(rt.pos(p2.tf), rt.pos(p.tf))
        # 预测：只有弹力（3%）+ 两个约束
        cur = state0[i]
        cur = add(cur, mul(sub(target, cur), db.elasticity))
        num2 = 1.0 + (p.stiffness - 1.0) * db.weight
        v2 = sub(target, cur)
        mag = math.sqrt(sum(c * c for c in v2))
        num3 = bone_n * (1.0 - num2) * 2.0
        if mag > num3 and mag > 1e-12:
            cur = add(cur, mul(v2, (mag - num3) / mag))
        v3 = sub(p2.pos, cur)
        m2 = math.sqrt(sum(c * c for c in v3))
        if m2 > 1e-12:
            cur = add(cur, mul(v3, (m2 - bone_n) / m2))
        pred_all.append(cur)
        u1 = apply_affine(inv, tuple(ufr[f][i][0:3]))
        e = math.dist(u1, cur)
        print("%3d (%7.4f,%7.4f,%7.4f) (%7.4f,%7.4f,%7.4f) (%7.4f,%7.4f,%7.4f)  差=%.5f"
              % (i, state0[i][0], state0[i][1], state0[i][2],
                 u1[0], u1[1], u1[2], cur[0], cur[1], cur[2], e))
        print("      target=(%7.4f,%7.4f,%7.4f)  骨长n=%.5f" % (target[0], target[1], target[2], bone_n))
    _ = pred_all
    return 0


if __name__ == "__main__":
    sys.exit(main())
