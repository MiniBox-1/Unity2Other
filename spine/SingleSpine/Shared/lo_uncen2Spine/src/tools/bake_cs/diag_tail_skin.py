# -*- coding: utf-8 -*-
r"""尾巴那 14.6px 常量的最后一步：**蒙皮层**逐顶点对账。

骨头世界坐标两边一致（Bone_Tail_22 = (-0.674861, 0.092642) 完全相同），
所以偏移只可能来自：骨骼表顺序 / bindpose / 权重索引 三者之一。
本脚本把转换器算出的每顶点世界坐标（_skin_mesh）和 Unity BakeMesh 的逐顶点
世界坐标摆在一起，并把该顶点用到的 (骨骼索引, 权重) 打出来。

用法:
    python diag_tail_skin.py --prefab <prefab> --assets <Assets> \
        --dump <Start__A.json> --part parts_Tail_F [--top 8]
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


from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    build_character_model, _world_matrices, _skin_mesh)
from unity2spine.unity.unity_anim2d import trs_mat  # noqa: E402
from unity2spine.convert.static_prefab_spine import (  # noqa: E402
    build_anim_assignments, _sample_world_multi)


def mm(m, v):
    return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2] + m[3],
            m[4] * v[0] + m[5] * v[1] + m[6] * v[2] + m[7],
            m[8] * v[0] + m[9] * v[1] + m[10] * v[2] + m[11])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefab", required=True)
    ap.add_argument("--assets", required=True)
    ap.add_argument("--dump", required=True)
    ap.add_argument("--part", default="parts_Tail_F")
    ap.add_argument("--top", type=int, default=6)
    ap.add_argument("--t", type=float, default=0.0, help="对比时刻")
    a = ap.parse_args()

    mdl, parts = build_character_model(a.prefab, a.assets)
    # 用**转换器自己采样出来的姿态**（和 Unity 侧同一时刻），不要用 rest
    assignments, _clips = build_anim_assignments(mdl, a.assets)
    world = _sample_world_multi(mdl, assignments, a.t)
    for p in parts:
        p.full_path = mdl.transforms[p.tfid]["path"] if p.tfid in mdl.transforms else ""
    part = next(p for p in parts if p.full_path.endswith(a.part))
    mesh = part.mesh
    print("部件 %s  kind=%s  顶点=%d  骨骼表=%d  bindposes=%d"
          % (a.part, part.kind, len(mesh["positions"]), len(part.bones),
             len(mesh.get("bindposes") or [])))
    conv = _skin_mesh(part, mesh, world)

    d = json.load(io.open(a.dump, encoding="utf-8-sig"))
    pi = next(i for i, p in enumerate(d["parts"])
              if p["path"].replace("\\", "/").endswith(a.part))
    fr = min(d["frames"], key=lambda x: abs(x["t"] - a.t))
    print("对比时刻 t=%.4f（导出工具里取到 t=%.4f）" % (a.t, fr["t"]))
    pd = fr["parts"][pi]
    m = pd["l2w"]
    vs = pd["verts"]
    n = len(conv)
    print()
    print("%5s %-28s %-28s %10s   (骨骼索引,权重)" % ("#", "转换器世界", "Unity BakeMesh 世界", "差px"))
    errs = []
    for i in range(n):
        u = mm(m, (vs[3 * i], vs[3 * i + 1], vs[3 * i + 2]))
        c = conv[i]
        e = math.hypot(c[0] - u[0], c[1] - u[1])
        errs.append((e, i, c, u))
    for (e, i, c, u) in sorted(errs, reverse=True)[:a.top]:
        blist = mesh.get("boneIndexRaw") or []
        wlist = mesh["weights"][i] if i < len(mesh["weights"]) else None
        bi = blist[i] if i < len(blist) else None
        print("%5d (%9.4f,%9.4f,%9.4f)  (%9.4f,%9.4f,%9.4f) %10.2f   %s %s"
              % (i, c[0], c[1], c[2], u[0], u[1], u[2], e, bi, wlist))
    med = sorted(x[0] for x in errs)[len(errs) // 2]
    print()
    print("逐顶点差: 中位 %.4f 世界单位 (≈%.1f px) / 最大 %.4f (≈%.1f px)"
          % (med, med * 803.7, max(x[0] for x in errs), max(x[0] for x in errs) * 803.7))
    print("→ 若中位≈0 而只有个别顶点大：个别顶点的权重/索引有问题；"
          "若整体≈同一个常量：骨骼表顺序或 bindpose 整体错位")
    return 0


if __name__ == "__main__":
    sys.exit(main())
