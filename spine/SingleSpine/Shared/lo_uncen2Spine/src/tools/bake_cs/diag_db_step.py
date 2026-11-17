# -*- coding: utf-8 -*-
r"""DynamicBone 的**单步隔离测试**。

思路：用 Unity 导出的粒子状态（dump_db_particles.cs）**喂**本移植版，
只跑一步，再和 Unity 的下一帧状态比 —— 这样能把"某一步公式不对"和
"误差逐帧累积"彻底分开。

第一步先拟合两个坐标系的映射（转换器世界 -> Unity 世界，应是一个仿射），
残差为 0 就说明两边只是差一个整体变换。

用法:
    python diag_db_step.py --prefab <prefab> --assets <Assets> \
        --dump <alice_db_particles.json> --state breast [--steps 1,2,5,20,100]
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
    step_dynamics)
from validate_cs_port import sample_local_world  # noqa: E402


def solve(M, V):
    n = len(M)
    a = [list(M[i]) + [V[i]] for i in range(n)]
    for col in range(n):
        p = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[p] = a[p], a[col]
        d = a[col][col]
        if abs(d) < 1e-12:
            return None
        a[col] = [x / d for x in a[col]]
        for r in range(n):
            if r != col:
                f = a[r][col]
                a[r] = [x - f * y for x, y in zip(a[r], a[col])]
    return [a[i][n] for i in range(n)]


def fit_affine(pairs):
    """pairs=[(src3,dst3)] -> (A(3x3 行主序), t3) 最小二乘。"""
    Mt = [[0.0] * 4 for _ in range(4)]
    for (s, _d) in pairs:
        v = (s[0], s[1], s[2], 1.0)
        for i in range(4):
            for j in range(4):
                Mt[i][j] += v[i] * v[j]
    rows = []
    for k in range(3):
        V = [0.0] * 4
        for (s, d) in pairs:
            v = (s[0], s[1], s[2], 1.0)
            for i in range(4):
                V[i] += v[i] * d[k]
        rows.append(solve(Mt, V))
    return rows


def apply_affine(rows, p):
    return tuple(rows[k][0] * p[0] + rows[k][1] * p[1] + rows[k][2] * p[2] + rows[k][3]
                 for k in range(3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefab", required=True)
    ap.add_argument("--assets", required=True)
    ap.add_argument("--dump", required=True)
    ap.add_argument("--state", default="breast")
    ap.add_argument("--steps", default="1,2,5,20,100")
    a = ap.parse_args()

    U = json.load(io.open(a.dump, encoding="utf-8-sig"))
    udb = U["particles"][0]
    ufr = udb["frames"]
    n = udb["n"]

    mdl, parts = load_character(a.prefab, a.assets, None, animated_only=True)
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

    # --- 1) 先跑一整遍，收集 (转换器世界, Unity 世界) 的对应，拟合仿射
    pairs = []
    mine = []
    for f in range(len(ufr)):
        lv, world = sample_local_world(mdl, assign, f * dt)
        rt.local = lv
        rt.world = world
        run_global_control(rt, drv)
        step_dynamics(rt, drv, dt)
        mine.append([p.pos for p in db.particles])
    for f in range(len(ufr)):
        for i in range(n):
            pairs.append((mine[f][i], tuple(ufr[f][i][0:3])))
    rows = fit_affine(pairs)
    res = max(math.dist(apply_affine(rows, s), d) for (s, d) in pairs)
    print("坐标系拟合：转换器世界 -> Unity 世界，仿射残差 = %.3e（7 粒子 × %d 帧）"
          % (res, len(ufr)))
    print()

    # --- 2) 单步隔离：喂 Unity 的上一帧状态，跑一步，比 Unity 的下一帧
    inv_rows = None
    try:
        inv_rows = fit_affine([(d, s) for (s, d) in pairs])
    except Exception:
        pass
    print("%7s | %-22s | %-22s" % ("frame", "单步后 我的粒子0 误差", "单步后 我的全部粒子最大误差"))
    print("-" * 70)
    for f in [int(x) for x in a.steps.split(",")]:
        if f >= len(ufr):
            continue
        # 把 Unity 在 f-1 的状态搬进我的坐标系
        for i in range(n):
            p = db.particles[i]
            u = ufr[f - 1][i]
            p.pos = apply_affine(inv_rows, (u[0], u[1], u[2]))
            p.prev = apply_affine(inv_rows, (u[3], u[4], u[5]))
        lv, world = sample_local_world(mdl, assign, f * dt)
        rt.local = lv
        rt.world = world
        run_global_control(rt, drv)
        step_dynamics(rt, drv, dt)
        e0 = math.dist(apply_affine(rows, db.particles[0].pos), tuple(ufr[f][0][0:3]))
        em = max(math.dist(apply_affine(rows, db.particles[i].pos),
                           tuple(ufr[f][i][0:3])) for i in range(n))
        print("%7d | %-22.3e | %-22.3e" % (f, e0, em))
    print()
    print("说明：如果【单步最大误差】≈0，说明公式是对的、误差只是逐帧累积；"
          "如果单步就大，说明这一步的公式对不上。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
