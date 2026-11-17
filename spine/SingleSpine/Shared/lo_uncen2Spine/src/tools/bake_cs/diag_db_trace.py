# -*- coding: utf-8 -*-
r"""移植版 DynamicBone **整段逐帧**对拍 Unity 的粒子 dump：
看误差是"缓慢累积"（公式系统性差异）还是"某帧突变"（事件/重置点）。

用法:
    python diag_db_trace.py --prefab <prefab> --assets <Assets> \
        --dump <alice_db_particles.json> --state breast [--every 20]
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

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from unity2spine.convert.static_prefab_spine import (      # noqa: E402
    load_character, enumerate_clips, make_samplers, assignments_for_entry, trs_mat)
from unity2spine.convert.convert_2dmodel import _world_matrices  # noqa: E402
from unity2spine.convert.cs_runtime import (                      # noqa: E402
    parse_cs_components, build_runtime, setup_dynamics, run_global_control,
    step_dynamics)
from validate_cs_port import sample_local_world                    # noqa: E402
from diag_db_step import fit_affine, apply_affine                  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefab", required=True)
    ap.add_argument("--assets", required=True)
    ap.add_argument("--dump", required=True)
    ap.add_argument("--state", default="breast")
    ap.add_argument("--every", type=int, default=20)
    a = ap.parse_args()

    U = json.load(io.open(a.dump, encoding="utf-8-sig"))
    udb = U["particles"][0]
    ufr = udb["frames"]
    n = udb["n"]
    print("Unity dump: go=%s 粒子=%d 帧=%d" % (udb["go"], n, len(ufr)))

    mdl, _parts = load_character(a.prefab, a.assets, None, animated_only=True)
    es = enumerate_clips(mdl, a.assets)
    ent = next(e for e in es if e["state"] == a.state)
    assign = assignments_for_entry(mdl, make_samplers(mdl, es), es, ent)
    comps = parse_cs_components(a.prefab, a.assets)
    lv_rest = {t: trs_mat(td["pos"], td["quat"], td["scale"])
               for t, td in mdl.transforms.items()}
    rt, drv = build_runtime(mdl, comps, lv_rest, _world_matrices(mdl, lv_rest),
                            a.prefab)
    setup_dynamics(rt, drv)
    db = drv["bones"][0]
    dt = 1.0 / float(U.get("fps") or 60.0)

    mine = []
    inbone = []       # 步前：该粒子骨头的世界位置（转换器空间）
    inn = []          # 步前：骨长 n
    for f in range(len(ufr)):
        lv, world = sample_local_world(mdl, assign, f * dt)
        rt.local = lv
        rt.world = world
        run_global_control(rt, drv)
        bpos = []
        nval = []
        for i, p in enumerate(db.particles):
            bpos.append(tuple(rt.pos(p.tf)) if p.tf is not None else (0.0, 0.0, 0.0))
            if p.parent >= 0:
                p2 = db.particles[p.parent]
                if p.tf is not None:
                    nval.append(math.sqrt(sum(
                        (rt.pos(p2.tf)[k] - rt.pos(p.tf)[k]) ** 2 for k in range(3))))
                else:
                    nval.append(math.sqrt(sum((rt.pos(p2.tf)[k]) ** 2 for k in range(3))))
            else:
                nval.append(0.0)
        inbone.append(bpos)
        inn.append(nval)
        step_dynamics(rt, drv, dt)
        mine.append([tuple(p.pos) for p in db.particles])

    pairs = [(mine[f][i], tuple(ufr[f][i][0:3]))
             for f in range(len(ufr)) for i in range(n)]
    rows = fit_affine(pairs)
    resid = [math.sqrt(sum((apply_affine(rows, s)[k] - d[k]) ** 2 for k in range(3)))
             for s, d in pairs]
    resid.sort()
    print("整体仿射拟合残差: 中位 %.5f  p90 %.5f  最大 %.5f 世界单位（≈×803.7 px）"
          % (resid[len(resid) // 2], resid[int(len(resid) * 0.9)], resid[-1]))
    print("  仿射矩阵 = %s" % [[round(x, 4) for x in r] for r in rows])

    # 步前输入（骨位置 / 骨长）与 Unity dump 的对照 —— 用来区分"姿态输入差"与"弹簧差"
    ie = []
    for f in range(len(ufr)):
        for i in range(n):
            u = ufr[f][i]
            mine_b = apply_affine(rows, inbone[f][i])
            ie.append(math.sqrt(sum((mine_b[k] - u[6 + k]) ** 2 for k in range(3))))
    ie.sort()
    print("步前骨头位置差（仿射后 vs Unity dump 的 inBone）: 中位 %.5f p90 %.5f 最大 %.5f"
          % (ie[len(ie) // 2], ie[int(len(ie) * 0.9)], ie[-1]))
    nn = []
    for f in range(len(ufr)):
        for i in range(n):
            nn.append(abs(inn[f][i] - ufr[f][i][12]))
    nn.sort()
    print("步前骨长 n 差: 中位 %.5f p90 %.5f 最大 %.5f"
          % (nn[len(nn) // 2], nn[int(len(nn) * 0.9)], nn[-1]))

    print()
    print("%-7s %-9s %10s %10s %10s" % ("frame", "t", "中位误差", "最大误差", "最差粒子"))
    for f in range(0, len(ufr), a.every):
        errs = [math.sqrt(sum((apply_affine(rows, mine[f][i])[k]
                               - ufr[f][i][k]) ** 2 for k in range(3)))
                for i in range(n)]
        med = sorted(errs)[n // 2]
        mx = max(errs)
        print("%-7d %-9.3f %10.5f %10.5f %10d"
              % (f, f * dt, med, mx, errs.index(mx)))

    # 最后一帧逐粒子
    f = len(ufr) - 1
    print()
    print("末帧 f=%d t=%.3f 逐粒子（转换器→仿射后 vs Unity）:" % (f, f * dt))
    for i in range(n):
        m = apply_affine(rows, mine[f][i])
        u = ufr[f][i]
        e = math.sqrt(sum((m[k] - u[k]) ** 2 for k in range(3)))
        print("   #%d  mine=(%8.4f,%8.4f,%8.4f)  unity=(%8.4f,%8.4f,%8.4f)  err=%.5f (%.1fpx)"
              % (i, m[0], m[1], m[2], u[0], u[1], u[2], e, e * 803.7))
    return 0


if __name__ == "__main__":
    sys.exit(main())
