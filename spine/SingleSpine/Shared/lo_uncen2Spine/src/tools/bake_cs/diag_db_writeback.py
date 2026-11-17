# -*- coding: utf-8 -*-
r"""DynamicBone 写回那一步的逐骨探针。

用法:
    python diag_db_writeback.py --prefab <prefab> --assets <Assets> --state breast
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
import math
import os
import sys


from unity2spine.convert.convert_2dmodel import _world_matrices, _skin_mesh  # noqa: E402
from unity2spine.convert.static_prefab_spine import (  # noqa: E402
    load_character, enumerate_clips, make_samplers, assignments_for_entry)
from unity2spine.unity.unity_mesh import mat4_mul, mat4_invert  # noqa: E402
from unity2spine.convert.cs_runtime import (  # noqa: E402
    parse_cs_components, build_runtime, setup_dynamics, step_dynamics,
    run_global_control, mat4_scale, mat4_pos)
from validate_cs_port import sample_local_world  # noqa: E402


def det3(m):
    return (m[0] * (m[5] * m[10] - m[6] * m[9])
            - m[1] * (m[4] * m[10] - m[6] * m[8])
            + m[2] * (m[4] * m[9] - m[5] * m[8]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefab", required=True)
    ap.add_argument("--assets", required=True)
    ap.add_argument("--state", default="breast")
    ap.add_argument("--part", default="parts_Breast_L")
    a = ap.parse_args()

    mdl, parts = load_character(a.prefab, a.assets, None, animated_only=True)
    for p in parts:
        p.full_path = mdl.transforms[p.tfid]["path"]
    part = next(p for p in parts if p.full_path.endswith(a.part))
    comps = parse_cs_components(a.prefab, a.assets)
    entries = enumerate_clips(mdl, a.assets)
    ent = next(e for e in entries if e["state"] == a.state)
    samplers = make_samplers(mdl, entries)
    assign = assignments_for_entry(mdl, samplers, entries, ent)

    lv, world = sample_local_world(mdl, assign, 0.0)
    rt, drv = build_runtime(mdl, comps, lv, world)
    setup_dynamics(rt, drv)
    run_global_control(rt, drv)

    bones = [b for b in part.bones]
    print("部件 %s 的 %d 根骨头：" % (a.part, len(bones)))
    for tag in ("step 前",):
        for t in bones:
            m = rt.world[t]
            print("  [%s] %-22s pos=(%.4f,%.4f,%.4f) scale=(%.6f,%.6f,%.6f) det=%.3e"
                  % (tag, mdl.transforms[t]["path"].split("/")[-1],
                     m[3], m[7], m[11], *mat4_scale(m), det3(m)))
    print("  step 前 顶点 max|v| = %.4f"
          % max(math.sqrt(sum(c * c for c in v))
                for v in _skin_mesh(part, part.mesh, rt.world)))

    step_dynamics(rt, drv, 1.0 / 60.0)
    print()
    for t in bones:
        m = rt.world[t]
        print("  [step 后] %-22s pos=(%.4f,%.4f,%.4f) scale=(%.6f,%.6f,%.6f) det=%.3e"
              % (mdl.transforms[t]["path"].split("/")[-1],
                 m[3], m[7], m[11], *mat4_scale(m), det3(m)))
        loc = rt.local[t]
        print("       local: pos=(%.5f,%.5f,%.5f) scale=(%.6f,%.6f,%.6f) det=%.3e"
              % (loc[3], loc[7], loc[11], *mat4_scale(loc), det3(loc)))
    print("  step 后 顶点 max|v| = %.4f"
          % max(math.sqrt(sum(c * c for c in v))
                for v in _skin_mesh(part, part.mesh, rt.world)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
