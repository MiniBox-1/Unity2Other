# -*- coding: utf-8 -*-
r"""问转换器自己：尾巴那条骨头链到底有没有被"曲线驱动"？

Alice 的尾巴变形骨是 `Global_CTRL/Controllers/CTRL_Spline/bone_1..bone_30/...`，
而 clip 里只有 `Bone_Pelvis/Bone_Tail_0`、`CTRL_Spline_Tail/spline_Ctrl_1..7` 的曲线
—— 也就是说运行时靠 Puppet2D 的样条解算才动。纯 clip 姿态下它应该是**静止**的。

本脚本用转换器自己的 API 看：这些骨头有没有被分到采样器、采样出来的世界坐标
在 t=0 和 t=3 之间变不变。
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


import io
import os
import sys


from unity2spine.convert.convert_2dmodel import build_character_model  # noqa: E402
from unity2spine.convert.static_prefab_spine import (  # noqa: E402
    build_anim_assignments, _sample_world_multi)

PREFAB = _resolve(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Assets"
                  r"\Prefabs\2DModel_3P_Alice_NS1.uAnim.prefab")
ASSETS = _resolve(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Assets")


def main():
    mdl, parts = build_character_model(PREFAB, ASSETS)
    assignments, clips = build_anim_assignments(mdl, ASSETS)
    print("转换器看到的动画: %s" % [(c[1], round(float(c[2].get("duration") or 0), 3))
                                   for c in clips])
    print()
    want = []
    for tfid, td in mdl.transforms.items():
        p = td.get("path", "")
        if "/CTRL_Spline/" in p and "/bone_" in p.split("/CTRL_Spline/")[-1]:
            want.append(tfid)
        elif p.endswith("Bone_Tail_End") or p.endswith("Bone_Tail_0"):
            want.append(tfid)
    print("尾巴相关 transform: %d 个" % len(want))
    w0 = _sample_world_multi(mdl, assignments, 0.0)
    w3 = _sample_world_multi(mdl, assignments, 3.0)
    moved = 0
    shown = 0
    for tfid in want:
        td = mdl.transforms[tfid]
        a = assignments.get(tfid)
        p0 = w0.get(tfid)
        p3 = w3.get(tfid)
        d = 0.0
        if p0 and p3:
            d = max(abs(p0[3] - p3[3]), abs(p0[7] - p3[7]))
        if d > 1e-4:
            moved += 1
        if d > 1e-4 or shown < 6:
            print("   %-58s 采样器=%-5s t0=(%.4f,%.4f) t3=(%.4f,%.4f) Δ=%.5f"
                  % (td.get("path", "")[-58:], "有" if a else "无",
                     p0[3] if p0 else 0, p0[7] if p0 else 0,
                     p3[3] if p3 else 0, p3[7] if p3 else 0, d))
            shown += 1
    print()
    print("==> 尾巴相关 transform 里，t=0→t=3 世界坐标变了的：%d / %d" % (moved, len(want)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
