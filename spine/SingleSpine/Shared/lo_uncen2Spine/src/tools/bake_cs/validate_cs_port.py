# -*- coding: utf-8 -*-
r"""验证"移植进转换器的 CS 运行时"：把转换器自己算出来的**脚本位移**和
Unity 真实的 **B − A** 对拍。

为什么比"绝对坐标"干净：转换器的坐标相对 Unity 差一个整体缩放/平移
（见 Mobile-old_CS烘焙_方法与进展.md §4），差分之后这些全消掉，
剩下的就纯粹是"脚本解算得对不对"。

用法:
    python validate_cs_port.py --prefab <prefab> --assets <Assets>
        --dump-dir <partdump 目录> --state breast --part parts_Tail_F [--max 6]
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


from unity2spine.convert.convert_2dmodel import _world_matrices, _skin_mesh  # noqa: E402
from unity2spine.convert.static_prefab_spine import (  # noqa: E402
    load_character, enumerate_clips, make_samplers, assignments_for_entry, trs_mat,
    euler_to_quat)
from unity2spine.unity.unity_mesh import mat4_vec  # noqa: E402
from unity2spine.convert.cs_runtime import (  # noqa: E402
    parse_cs_components, build_runtime, run_global_control,
    setup_dynamics, step_dynamics)


def sample_local_world(mdl, assign, t):
    """_sample_world_multi 的"同时给出 local_values"版本（CS 运行时需要 local）。"""
    local_values = {}
    for tfid, td in mdl.transforms.items():
        a = assign.get(tfid)
        if a is None:
            q = td["quat"]
            local_values[tfid] = trs_mat(td["pos"], q, td["scale"])
            continue
        dur = a["duration"]
        tt = t
        if dur > 1e-6:
            tt = (t % dur) if a.get("loop", True) else min(t, dur)
        sp = a["sampler"].sample(a.get("anim_path", td.get("anim_path")), tt)
        q = sp["quat"] or euler_to_quat(sp["euler"])
        local_values[tfid] = trs_mat(sp["pos"], q, sp["scale"])
    return local_values, _world_matrices(mdl, local_values)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefab", required=True)
    ap.add_argument("--assets", required=True)
    ap.add_argument("--dump-dir", required=True)
    ap.add_argument("--state", default="breast")
    ap.add_argument("--part", default="parts_Tail_F")
    ap.add_argument("--max", type=int, default=6)
    ap.add_argument("--first", type=int, default=0,
                    help="只逐帧打印前 N 帧（诊断用）")
    a = ap.parse_args()

    mdl, parts = load_character(a.prefab, a.assets, None, animated_only=True)
    for p in parts:
        p.full_path = mdl.transforms[p.tfid]["path"]
    part = next(p for p in parts if p.full_path.endswith(a.part))
    comps = parse_cs_components(a.prefab, a.assets)
    print("CS 组件: %s" % ", ".join("%s×%d" % (k, len(v))
                                   for k, v in sorted(comps.items()) if v))

    entries = enumerate_clips(mdl, a.assets)
    if not entries:
        raise SystemExit("enumerate_clips 返回空——char_animators=%r"
                         % (getattr(mdl, "char_animators", None),))
    ent = next((e for e in entries if e["state"] == a.state), None)
    if ent is None:
        print("可用 state: %s" % ", ".join(e["state"] for e in entries))
        raise SystemExit("没有 state=%s" % a.state)
    samplers = make_samplers(mdl, entries)
    assign = assignments_for_entry(mdl, samplers, entries, ent)

    dA = json.load(io.open(os.path.join(a.dump_dir, a.state + "__A.json"),
                           encoding="utf-8-sig"))
    dB = json.load(io.open(os.path.join(a.dump_dir, a.state + "__B.json"),
                           encoding="utf-8-sig"))
    pi = next(i for i, p in enumerate(dB["parts"])
              if p["path"].replace("\\", "/").endswith(a.part))
    n = dB["parts"][pi]["n"]
    lossy = abs(dB["parts"][pi]["lossyScale"][0])
    ls3 = [abs(v) for v in dB["parts"][pi]["lossyScale"]]

    print("部件 %s：顶点 %d  lossyScale %.5f  clip=%s 时长 %.3f"
          % (a.part, n, lossy, dB.get("state", a.state), dB["length"]))
    print()
    print("%8s | %16s | %18s | %s"
          % ("t", "Unity |B-A| 中位", "转换器 CS 位移 中位", "两者差 中位/最大"))
    print("-" * 78)
    # DynamicBone 是有状态的弹簧，必须**逐帧跑完整条 clip**，再在采样时刻取结果
    nf = len(dB["frames"])
    # ★ dt 必须用**精确的 1/fps**，不能用导出 JSON 里 6 位小数的时刻差：
    #   0.016667 比 1/60=0.01666667 大 3e-7，DynamicBone 的 m_Time 累加器会慢慢漂，
    #   大约每 50 帧就多走一个物理子步 → 整个弹簧错拍（实测残差 0.4~5.7px 就是这个）。
    dt = 1.0 / float(dB.get("fps") or 60.0)
    step = max(1, nf // (a.max + 1))
    want = set(range(0, nf, step))
    if a.first:
        want = set(range(min(a.first, nf)))
    times = [dB["frames"][i]["t"] for i in sorted(want)]

    # 先把第一帧建好（setup 一次）
    # ★ 关键：DynamicBone 在 Unity 里是 Start() 里 SetupParticles 的，那一刻骨头是
    #   **预制体姿态**（Animator 还没求值），所以粒子要按 rest 姿态建，不是 clip t=0。
    lv_rest = {}
    for tfid, td in mdl.transforms.items():
        lv_rest[tfid] = trs_mat(td["pos"], td["quat"], td["scale"])
    rt, drv = build_runtime(mdl, comps, lv_rest, _world_matrices(mdl, lv_rest))
    setup_dynamics(rt, drv)
    for b in drv["bones"]:
        if b.valid():
            print("   [调试] DB root=%s 粒子=%d 骨长合计=%.4f object_scale=%.5f "
                  "upd=%.1f w=%.2f d=%.3f e=%.3f s=%.3f"
                  % (b.root, len(b.particles), b.bone_total, b.object_scale,
                     b.update_rate, b.weight, b.damping, b.elasticity, b.stiffness))
            pl = sorted(max(abs(c) for c in p.pos) for p in b.particles)
            print("          setup 后 |pos| 中位/最大 = %.5f / %.5f"
                  % (pl[len(pl) // 2], pl[-1]))
    print("   [调试] spline=%d(valid %d) ik=%d(valid %d) dynbone=%d(valid %d) gc=%s"
          % (len(drv["spline"]), sum(1 for s in drv["spline"] if s.valid()),
             len(drv["ik"]), sum(1 for h in drv["ik"] if h.valid()),
             len(drv["bones"]), sum(1 for b in drv["bones"] if b.valid()),
             drv.get("gc")))
    base_cache = {}
    cs_cache = {}
    for f in range(nf):
        t = dB["frames"][f]["t"]
        lv, world = sample_local_world(mdl, assign, t)
        rt.local = lv
        rt.world = world
        pm = dB["frames"][f]["parts"][pi]
        # 参考姿态（纯 clip）只在需要的帧算
        if f in want:
            base_cache[f] = _skin_mesh(part, part.mesh, world)
        run_global_control(rt, drv)
        step_dynamics(rt, drv, dt)
        if f < 3:
            for b in drv["bones"]:
                if b.valid():
                    pl = sorted(max(abs(c) for c in p.pos) for p in b.particles)
                    print("   [调试] f=%d 第0步后 |pos| 中位/最大 = %.5f / %.5f"
                          % (f, pl[len(pl) // 2], pl[-1]))
        if f in want:
            cs_cache[f] = _skin_mesh(part, part.mesh, rt.world)

    worst = 0.0
    for f in sorted(want):
        t = dB["frames"][f]["t"]
        base = base_cache[f]
        cs = cs_cache[f]
        # ★ 逐轴换算：转换器坐标 = Unity 坐标 / lossyScale（**逐轴**，可能非均匀）。
        #   之前用 lossyScale[0] 这一个标量乘三个分量，换算本身就错了。
        dc = [tuple((cs[i][k] - base[i][k]) * ls3[k] for k in range(3))
              for i in range(len(base))]
        pa = dA["frames"][f]["parts"][pi]
        pb = dB["frames"][f]["parts"][pi]
        ma = pa["l2w"]
        mb = pb["l2w"]
        du = []
        for i in range(n):
            wa = mat4_vec(ma, (pa["verts"][3 * i], pa["verts"][3 * i + 1],
                               pa["verts"][3 * i + 2]))
            wb = mat4_vec(mb, (pb["verts"][3 * i], pb["verts"][3 * i + 1],
                               pb["verts"][3 * i + 2]))
            du.append(tuple(wb[k] - wa[k] for k in range(3)))
        eu = sorted(math.sqrt(sum(c * c for c in du[i])) for i in range(n))
        ec = sorted(math.sqrt(sum(c * c for c in dc[i])) for i in range(n))
        ed = sorted(math.sqrt(sum((dc[i][k] - du[i][k]) ** 2 for k in range(3)))
                    for i in range(n))
        worst = max(worst, ed[-1])
        print("%8.3f | %16.5f | %18.5f | %.5f / %.5f"
              % (t, eu[n // 2], ec[n // 2], ed[n // 2], ed[-1]))
    print()
    print("单位=世界单位（Alice 1 单位≈803.7 px）。最大偏差 %.5f" % worst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
