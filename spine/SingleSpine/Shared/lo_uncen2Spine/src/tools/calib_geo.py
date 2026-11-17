# -*- coding: utf-8 -*-
"""静态管线几何校准：把静态采样出来的骨骼/部件顶点与 Unity 动态帧真值对比。

数据来源（仅用于校准，不参与成品导出）：
  info/Data/PoseFrames/<角色>.json   —— 每帧 Transform 局部值 + BakeMesh 顶点
                                         + Sprite 世界四角 + sortingOrder/renderQueue

检查内容：
  1. 局部 TRS：静态采样值 vs Unity 每帧真值（找出没被采样到的曲线/路径问题）；
  2. 部件顶点：静态管线的世界顶点 vs Unity 每帧真值（找出“运动中部件分离”）。

用法:
  python tools/calib_geo.py --prefab <prefab> [--scene save.unity] [--clip lobby]
      [--dt 0.05] [--pose <PoseFrames.json>] [--times 0,1,2,4,8,12,16]
      [--top 12]
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
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from ngui2spine.convert_2dmodel import build_character_model  # noqa: E402
from ngui2spine.static_prefab_spine import (  # noqa: E402
    _choose_clip, _part_points, _sample_world, assignments_for_entry,
    enumerate_clips, load_character, make_samplers)

ASSETS = _resolve(r"D:\VB\Search\NormalLocal\lastOrign\Assets")
# Unity 侧**动态导出**的统一根（2026-09-18 起）：D:\VB\Unity2Spine\info
INFO = _resolve(r"D:\VB\Unity2Spine\info")
DATA = os.path.join(INFO, "Data")


def load_parts(prefab, scene=None, assets=ASSETS):
    """与转换器共用同一套“角色子树 + Animator 选择 + anim_path 归一”逻辑。"""
    return load_character(prefab, assets, scene)


def secondary_paths(mdl, clip_hint=None, assets=ASSETS):
    """被"非驱动 Animator"（如 aeda 的球光 star_deco）影响的部件路径集合。

    Unity 的 PoseFrames 真值只推进了主控制器，这些部件在真值里停在 rest，
    因此逐顶点比对时要排除，否则会误报（我们导出里它们是会动的）。
    """
    entries = enumerate_clips(mdl, assets)
    if len(entries) < 2:
        return set()
    samplers = make_samplers(mdl, entries)
    main = next((e for e in entries if e["is_main"]), None)
    if main is None:
        return set()
    assign = assignments_for_entry(mdl, samplers, entries, main)
    paths = set()
    for tfid, a in assign.items():
        if a.get("root") != main["go"]:
            paths.add(mdl.transforms[tfid]["path"])
    return paths


def _is_secondary(part_path, sec):
    return any(part_path == p or part_path.startswith(p + "/") for p in sec)


def layer_paths(mdl, assets=ASSETS):
    """被主 Animator 的**第 2 层及以上**驱动、因此不能参与逐顶点比对的**部件路径**。

    为什么要单独排：`PoseFrames` 真值是"只推进一条 clip"（`SampleAnimationClip`），
    而转换器是按**各层的默认状态**把上层的 clip 叠上去的
    （`static_prefab_spine.compose_layers`）。两边口径不同 ⇒ 这些部件在逐顶点
    比对里必然出现假误差（`alice_skin1_fix` 的 `parts_curtain` 0.262、
    `alice_skin1_dl_idle` / `daika` 的同类件都是这条）。

    返回的是**渲染器所在节点的全路径**（不是被动画的骨骼路径）：蒙皮件的形变
    跟着它的骨骼走，所以"骨骼被上层动画"的格子也要按部件算进来
    （`parts_curtain` 自己身上没有曲线，动的是 `Bone_curtain_*`）。
    """
    from ngui2spine.convert_2dmodel import _asset_path
    from ngui2spine.unity_2dmodel import parse_animator_layers
    from ngui2spine.unity_anim2d import parse_clip
    cp = _asset_path(assets, getattr(mdl, "animator_controller_guid", None) or "")
    if not cp or not os.path.isfile(cp):
        return set()
    host = (getattr(mdl, "anim_root_path", "") or "").rstrip("/")
    nodes = set()
    for li, L in enumerate(parse_animator_layers(cp)):
        if li == 0:                       # 0 层就是 Base Layer，真值推进的就是它
            continue
        g = L.get("defaultClipGuid")
        p = _asset_path(assets, g) if g else None
        if not p or not os.path.isfile(p):
            continue
        for c in (parse_clip(p).get("curves") or []):
            rel = (getattr(c, "path", "") or "").strip("/")
            if not rel:
                continue
            nodes.add(host + "/" + rel if host else rel)
    if not nodes:
        return set()
    # tfid -> 节点全路径（`bones` 里存的是 **transform id**，不是 GameObject id）
    path_of_tf = {tfid: (t.get("path") or "")
                  for tfid, t in mdl.transforms.items()}
    out = set(nodes)
    for r in (getattr(mdl, "renderers", None) or []):
        cand = [path_of_tf.get(r.get("tfid"), "")]
        for b in (r.get("bones") or []):
            cand.append(path_of_tf.get(b, ""))
        hit = False
        for cpth in cand:
            if not cpth:
                continue
            for nd in nodes:
                if cpth == nd or cpth.startswith(nd + "/"):
                    hit = True
                    break
            if hit:
                break
        if hit and cand[0]:
            out.add(cand[0])
    return out


def quat_angle_deg(q1, q2):
    d = abs(sum(a * b for a, b in zip(q1, q2)))
    d = min(1.0, d)
    return math.degrees(2 * math.acos(d))


def compare_transforms(mdl, sampler, pose, times, top=12):
    """静态采样 local TRS vs Unity 每帧真值。"""
    frames = pose["frames"]
    tmap = {round(f["time"], 4): f for f in frames}
    worst = []
    for t in times:
        fr = tmap.get(round(t, 4))
        if fr is None:
            continue
        truth = {}
        for tr in fr.get("transforms") or []:
            truth[tr["path"]] = tr
        for tfid, td in mdl.transforms.items():
            path = td["path"]
            tr = truth.get(path)
            if not tr:
                continue
            sp = sampler.sample(td.get("anim_path", path), t)
            q = sp["quat"]
            if q is None:
                from ngui2spine.unity_anim2d import euler_to_quat
                q = euler_to_quat(sp["euler"])
            tp = tr.get("localPos") or [0, 0, 0]
            ts = tr.get("localScale") or [1, 1, 1]
            tq = tr.get("localRot")
            if tq is None:
                from ngui2spine.unity_anim2d import euler_to_quat
                tq = euler_to_quat(tr.get("localEuler") or [0, 0, 0])
            dp = math.dist(sp["pos"], tp)
            ds = math.dist(sp["scale"], ts)
            da = quat_angle_deg(q, tq)
            err = dp + ds * 0.5 + da / 90.0
            if err > 1e-4:
                worst.append((err, t, path, dp, ds, da,
                              sp["pos"], tp, sp["scale"], ts, q, tq))
    worst.sort(reverse=True, key=lambda x: x[0])
    print("== 局部 TRS 差异（最多列 %d 条）==" % top)
    if not worst:
        print("   完全一致")
    for e, t, path, dp, ds, da, pos, tpos, sc, tsc, q, tq in worst[:top]:
        print("  t=%-5g %-70s dPos=%.4f dScale=%.4f dRot=%.2f°" %
              (t, path[-70:], dp, ds, da))
        print("         ours  pos=%s scale=%s" %
              ([round(v, 4) for v in pos], [round(v, 4) for v in sc]))
        print("         unity pos=%s scale=%s" %
              ([round(v, 4) for v in tpos], [round(v, 4) for v in tsc]))
        if da > 1.0:
            print("         ours  quat=%s" % [round(v, 4) for v in q])
            print("         unity quat=%s" % [round(v, 4) for v in tq])
    return worst


def _truth_part_points(entry, kind):
    if kind == "sprite":
        wc = entry.get("worldCorners") or []
        return [(c[0], c[1]) for c in wc]
    pos = entry.get("positions") or []
    l2w = entry.get("localToWorld")
    if not pos or not l2w:
        return []
    flat = [v for row in l2w for v in row]
    from ngui2spine.unity_mesh import mat4_vec
    out = []
    for v in pos:
        w = mat4_vec(flat, (v[0], v[1], v[2]))
        out.append((w[0], w[1]))
    return out


def _aabb(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _part_err(ours, truth, kind):
    """返回 (平均误差, 最大误差)。

    **sprite 只能比 AABB**：真值的 `worldCorners` 是 `Renderer.bounds`（世界空间
    **轴对齐**包围盒），而我们的是 sprite 旋转后的四边形 —— 逐点比会把"旋转角度"
    当成几何误差（bheur 的 `Part_Balgure` 就是这么假报 0.091 的）。
    """
    if kind == "sprite":
        a, b = _aabb(ours), _aabb(truth)
        d = [abs(x - y) for x, y in zip(a, b)]
        return sum(d) / len(d), max(d)
    d = [math.dist((p[0], p[1]), q) for p, q in zip(ours, truth)]
    return sum(d) / len(d), max(d)


def compare_parts(mdl, parts, sampler, pose, times, top=15, skip_paths=None):
    """部件顶点（世界 XY）静态 vs 真值。"""
    frames = pose["frames"]
    tmap = {round(f["time"], 4): f for f in frames}
    per_part = {}
    for t in times:
        fr = tmap.get(round(t, 4))
        if fr is None:
            continue
        entries = {}
        for key, kind in (("skinned", "skinned"), ("sprites", "sprite")):
            for e in fr.get(key) or []:
                entries[e.get("path")] = (e, kind)
        world = _sample_world(mdl, sampler, t)
        for p in parts:
            if skip_paths and _is_secondary(p.full_path, skip_paths):
                continue
            hit = entries.get(p.full_path)
            if not hit:
                continue
            e, kind = hit
            ours = _part_points(p, world)
            truth = _truth_part_points(e, kind)
            if not ours or len(ours) != len(truth):
                per_part.setdefault(p.full_path, []).append(
                    (t, float("nan"), 0))
                continue
            avg, mx = _part_err(ours, truth, kind)
            per_part.setdefault(p.full_path, []).append((t, avg, mx))
    rows = []
    for path, vals in per_part.items():
        ds = [v[1] for v in vals if not math.isnan(v[1])]
        mx = [v[2] for v in vals if not math.isnan(v[1])]
        if not ds:
            rows.append((float("inf"), path, float("nan"), float("nan"), vals))
            continue
        rows.append((sum(ds) / len(ds), path, max(ds), max(mx), vals))
    rows.sort(reverse=True, key=lambda x: (x[0] if not math.isnan(x[0]) else 1e9))
    print("== 部件顶点误差（世界单位，按平均误差排序，最多 %d 条）==" % top)
    print("  %-58s %8s %8s  每帧平均" % ("部件", "平均", "最大"))
    for avg, path, m, mx, vals in rows[:top]:
        detail = " ".join("%g:%.3f" % (t, a) for t, a, _x in vals[:12]
                          if not math.isnan(a))
        print("  %-58s %8.3f %8.3f  %s" % (path.split("ch_root/")[-1][-58:],
                                           avg, m, detail))
    skipped = [r for r in rows if math.isnan(r[0]) or math.isinf(r[0])]
    if skipped:
        print("  顶点数不一致/无真值的部件：")
        for _a, path, _m, _mx, vals in skipped[:10]:
            print("    %s" % path.split("ch_root/")[-1][-80:])
    return rows


def compare_scene_t0(mdl, parts, sampler, scenet0_path, top=15):
    """用 SceneT0（t=0 真值，含 renderer 的 localToWorld）对比部件几何。

    SceneT0 与当前场景状态可能整体位移/缩放不同（例如角色被搬到了别处），
    因此先按“根部世界矩阵的差”把我们的结果对齐到真值坐标系再比较。
    """
    import numpy as np
    from ngui2spine.unity_mesh import mat4_vec, mat4_invert, mat4_mul
    d = json.load(open(scenet0_path, encoding="utf-8-sig"))
    renderers = d.get("renderers") or []
    if not renderers:
        print("== SceneT0 没有 renderer 数据，跳过 ==")
        return []
    root = d.get("root") or ""
    ours_root = None
    for tfid, td in mdl.transforms.items():
        if td["path"] == root:
            ours_root = tfid
            break
    world = _sample_world(mdl, sampler, 0.0)
    delta = None
    for tr in d.get("transforms") or []:
        if tr.get("path") == root and tr.get("worldMatrix"):
            flat = [v for row in tr["worldMatrix"] for v in row]
            if ours_root is not None:
                delta = mat4_mul(flat, mat4_invert(world[ours_root]))
            break

    def apply(m, p):
        if m is None:
            return (p[0], p[1])
        q = mat4_vec(m, (p[0], p[1], 0.0))
        return (q[0], q[1])

    rows = []
    for p in parts:
        r = next((x for x in renderers if x.get("path") == p.full_path), None)
        if r is None:
            continue
        l2w = r.get("localToWorld")
        if not l2w:
            continue
        flat = [v for row in l2w for v in row]
        if r.get("kind") == "sprite":
            sp = p.sprite or {}
            rect = list(r.get("rect") or [])
            pivot = list(r.get("pivot") or [])
            ppu = float(r.get("pixelsPerUnit") or 100)
            if len(rect) < 4 or len(pivot) < 2 or rect[2] <= 0:
                sp = p.sprite or {}
                rect = list(sp.get("rect") or [0, 0, 0, 0])
                pivot = [ (sp.get("pivot") or [0.5, 0.5])[0] * rect[2],
                          (sp.get("pivot") or [0.5, 0.5])[1] * rect[3] ]
                ppu = float(sp.get("pixelsToUnits") or 100)
            lx, by = -pivot[0] / ppu, -pivot[1] / ppu
            local = [(lx, by, 0), (lx + rect[2] / ppu, by, 0),
                     (lx + rect[2] / ppu, by + rect[3] / ppu, 0),
                     (lx, by + rect[3] / ppu, 0)]
        else:
            baked = r.get("baked") or {}
            local = baked.get("positions") or r.get("positions") or []
            if not local and p.mesh:
                local = [tuple(v) for v in p.mesh.get("positions", [])]
        truth = [apply(flat, v) for v in local]
        ours_raw = _part_points(p, world)
        ours = [apply(delta, (q[0], q[1])) for q in ours_raw]
        if not ours or len(ours) != len(truth):
            rows.append((float("inf"), p.full_path, float("nan"), float("nan")))
            continue
        dd = [math.dist(a, b) for a, b in zip(ours, truth)]
        rows.append((sum(dd) / len(dd), p.full_path, max(dd), len(dd)))
    rows.sort(key=lambda x: x[0], reverse=True)
    print("== SceneT0 t=0 部件几何误差（世界单位，最多 %d 条）==" % top)
    print("  %-58s %8s %8s" % ("部件", "平均", "最大"))
    for avg, path, mx, n in rows[:top]:
        print("  %-58s %8.4f %8.4f" % (path.split("/")[-1][-58:] + "  (" +
                                       path.split("/")[-2][-24:] + ")", avg, mx))
    return rows


def compare_spine_dir(spine_dir, pose, times, top=15, tol_time=0.02,
                      skip_paths=None):
    """端到端校验：直接读导出的 Spine JSON（setup + deform），
    还原到 Unity 世界坐标后与 PoseFrames 真值比较。

    与 compare_parts 的区别：这里验证的是**成品文件本身**
    （含参考帧选择、deform 关键帧插值），而不是内部重算的几何。
    """
    from ngui2spine.unity_mesh import mat4_vec
    jsons = [f for f in sorted(os.listdir(spine_dir))
             if f.endswith(".json") and not f.startswith(("_", "."))]
    data = None
    for f in jsons:
        cand = json.load(open(os.path.join(spine_dir, f), encoding="utf-8-sig"))
        if isinstance(cand, dict) and "skins" in cand:
            data = cand
            break
    if data is None:
        print("== 目录里没有 Spine JSON ==")
        return []
    info_path = os.path.join(spine_dir, "_static_info.json")
    info = json.load(open(info_path, encoding="utf-8-sig")) \
        if os.path.isfile(info_path) else {}
    ox, oy = (info.get("origin") or [0.0, 0.0])
    unit_k = float(info.get("unitScale") or 1.0)
    flip = -1.0 if info.get("flipX") else 1.0
    # 多 drawable 的部件在 partsMeta 里会出现多次（同一 path、不同 layerId），
    # 几何完全一样，取层级最低的那份（名字不带 `#`，最稳定）即可。
    name_of_path = {}
    for p in info.get("partsMeta") or []:
        key = (int(p.get("layerId") or 0), p["name"])
        cur = name_of_path.get(p["path"])
        if cur is None or key < cur[0]:
            name_of_path[p["path"]] = (key, p["name"])
    name_of_path = {k: v[1] for k, v in name_of_path.items()}
    attachments = (data.get("skins") or [{}])[0].get("attachments") or {}
    anims = data.get("animations") or {}
    # 用 _static_info 里记的 setup clip，而不是"JSON 里第一条动画"：
    # 多 Animator 角色（daika 的 Chair_Only、alice 的 curtain）排序一变，
    # 第一条动画就可能不是真值对应的那条，会算出假误差。
    setup_clip = info.get("setupClip")
    clip = anims.get(setup_clip) if setup_clip else None
    if clip is None:
        clip = next(iter(anims.values()), {})
    # 再核对时长：和真值差太多说明"我们选的主 clip ≠ Unity 的主 clip"，
    # 这种比对没有意义，直接说清楚而不是给一个假误差。
    ours_dur = 0.0
    for slot in (clip.get("slots") or {}).values():
        for k in slot.get("attachment") or []:
            ours_dur = max(ours_dur, float(k["time"]))
    # deform 结构是 skin -> {部件: {附件: [关键帧]}}，要三层都走一遍
    for skin_block in (clip.get("deform") or {}).values():
        for per_att in skin_block.values():
            for frames in per_att.values():
                for k in frames or []:
                    ours_dur = max(ours_dur, float(k.get("time") or 0.0))
    truth_dur = float(pose.get("duration") or 0.0)
    if ours_dur > 0 and truth_dur > 0 and abs(ours_dur - truth_dur) > 0.35:
        print("== 跳过端到端比对：我们的 setup clip 是 %r（%.2fs），真值是 %r（%.2fs）=="
              % (setup_clip or "(第一条)", ours_dur,
                 pose.get("clip") or "?", truth_dur))
        print("   （两边不是同一条动画，比出来的数字没有意义；"
              "需要时在 Unity 侧按同一条 clip 导真值）")
        return []
    deform = (clip.get("deform") or {}).get("default") or {}

    def verts_at(slot, att_name, t):
        att = (attachments.get(slot) or {}).get(att_name)
        if not att:
            return None
        setup = att.get("vertices") or []
        frames = (deform.get(slot) or {}).get(att_name)
        off = [0.0] * len(setup)
        if frames:
            if t <= frames[0]["time"]:
                off = frames[0].get("vertices") or off
            elif t >= frames[-1]["time"]:
                off = frames[-1].get("vertices") or off
            else:
                for i in range(1, len(frames)):
                    if t <= frames[i]["time"]:
                        a, b = frames[i - 1], frames[i]
                        va, vb = a.get("vertices") or [], b.get("vertices") or []
                        k = (t - a["time"]) / max(1e-9, b["time"] - a["time"])
                        off = [x + (y - x) * k for x, y in zip(va, vb)] \
                            if len(va) == len(vb) == len(setup) else (vb or off)
                        break
        pts = []
        for i in range(0, len(setup) - 1, 2):
            dx = off[i] if i < len(off) else 0.0
            dy = off[i + 1] if i + 1 < len(off) else 0.0
            x = setup[i] + dx
            y = setup[i + 1] + dy
            pts.append((flip * x / unit_k + ox, y / unit_k + oy))
        return pts

    frames = {round(f["time"], 4): f for f in pose["frames"]}
    skipped_truth = []
    inactive_truth = 0
    samples = []          # (ours, truth, path, t)
    for t in times:
        fr = None
        for k, v in frames.items():
            if abs(k - t) <= tol_time:
                fr = v
                break
        if fr is None:
            continue
        truth = {}
        for key, kind in (("skinned", "skinned"), ("sprites", "sprite")):
            for e in fr.get(key) or []:
                # Unity 没激活的渲染器（`activeInHierarchy=false`）它根本没画，
                # BakeMesh 给的是未蒙皮的姿势 → 拿它比对会得到"恒定偏移"的假误差
                # （cheona/darkelf/constantias2 的单部件偏差都是这么来的）。
                if not e.get("activeInHierarchy", True):
                    inactive_truth += 1
                    continue
                truth[e["path"]] = (e, kind)
        for path, (e, kind) in truth.items():
            if skip_paths and _is_secondary(path, skip_paths):
                continue
            slot = name_of_path.get(path)
            if not slot:
                continue
            att_name = next(iter((attachments.get(slot) or {}) or {}), None)
            if not att_name:
                continue
            ours = verts_at(slot, att_name, t)
            if not ours:
                continue
            if kind == "sprite":
                tp = [(c[0], c[1]) for c in (e.get("worldCorners") or [])]
            else:
                l2w = e.get("localToWorld")
                if not l2w:
                    continue
                flat = [v for row in l2w for v in row]
                tp = [mat4_vec(flat, v)[:2] for v in (e.get("positions") or [])]
            if len(ours) != len(tp):
                # sprite 本来就不该逐点比（下游 _part_err 用 AABB）：
                # 走 Unity Tight 网格后我们的顶点数 != 真值的 4 角，
                # 这里不能当成"缺数据"丢掉，否则会报 inf/nan。
                if kind != "sprite":
                    samples.append((None, None, path, t, kind))
                    continue
            # Unity 的 BakeMesh 在个别极端姿态下会吐出 1e20 级别的坐标
            # （例如 banshee 的 parts_Hand_R 在 t≈1 时），那是真值本身
            # 数值爆炸，不是导出问题——直接跳过，否则会误报成误差爆炸。
            if tp and max(max(abs(c) for c in q) for q in tp) > 1e6:
                skipped_truth.append((path.split("/")[-1], t))
                continue
            samples.append((ours, tp, path, t, kind))

    # 真值帧是**世界坐标**，导出产物只带自己的原点。角色不在 `save.unity`
    # 里时（走 prefab 回退）两者会差一个**常量平移**——例如 blacklilith 在
    # 场景里摆在 x≈5，prefab 里在 x≈0，逐顶点就会恒定差 5.0。
    # 整角色被平移不是“运动中部件分离”，所以先按各部件质心差的中位数估一个
    # 全局平移并扣掉，同时把平移量单独报出来（读者能立刻分辨是不是摆位问题）。
    dxs, dys = [], []
    for ours, tp, _p, _t, _k in samples:
        if not ours or not tp:
            continue
        n = min(len(ours), len(tp))
        dxs.append(sum(q[0] for q in ours[:n]) / n
                   - sum(q[0] for q in tp[:n]) / n)
        dys.append(sum(q[1] for q in ours[:n]) / n
                   - sum(q[1] for q in tp[:n]) / n)

    def _med(v):
        if not v:
            return 0.0
        s = sorted(v)
        return s[len(s) // 2]

    gx, gy = _med(dxs), _med(dys)
    rows = []
    for ours, tp, path, t, kind in samples:
        if ours is None:
            rows.append((float("inf"), path, float("nan"), t))
            continue
        shifted = [(a[0] - gx, a[1] - gy) for a in ours]
        avg, mx = _part_err(shifted, tp, kind)
        rows.append((avg, path, mx, t))
    rows.sort(key=lambda x: (x[0] if not math.isnan(x[0]) else 1e9),
              reverse=True)
    print("== 导出文件端到端误差（读 JSON 的 setup+deform 还原，最多 %d 条）=="
          % top)
    print("  %-56s %8s %8s %6s" % ("部件", "平均", "最大", "t"))
    for avg, path, mx, t in rows[:top]:
        print("  %-56s %8.5f %8.5f %6g" % (path.split("/")[-1][-56:], avg, mx, t))
    if abs(gx) > 1e-4 or abs(gy) > 1e-4:
        print("  （已扣除全局平移 (%.4f, %.4f) 世界单位：导出原点与真值场景摆位不同，"
              "不是部件分离）" % (gx, gy))
    if rows:
        worst = max(r[2] for r in rows if not math.isnan(r[2]))
        print("  最大顶点误差 %.5f 世界单位（样本 %d）" % (worst, len(rows)))
    else:
        # 0 样本时以前什么都不打印，批次脚本的正则抓不到结果行，
        # 只把表头当成 error，看起来像“工具解析异常”。这里给出明确原因。
        print("  !! 没有可比对样本：真值里的部件路径在导出 slot 里一个都找不到。"
              "先检查主 Animator 是否选成了辅助 Animator（角色子树被整段排除），"
              "或该部件是否被判定为“始终禁用”而没导出。")
    if skipped_truth:
        print("  （跳过 %d 个真值异常样本，例如 %s 在 t=%g）"
              % (len(skipped_truth), skipped_truth[0][0], skipped_truth[0][1]))
    if inactive_truth:
        print("  （跳过 %d 个 Unity 未激活的真值样本：那些渲染器 Unity 没画，"
              "BakeMesh 值是未蒙皮姿势）" % inactive_truth)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefab", required=True)
    ap.add_argument("--assets", default=ASSETS)
    ap.add_argument("--scene", default=None)
    ap.add_argument("--clip", default=None)
    ap.add_argument("--pose", default=None)
    ap.add_argument("--dt", type=float, default=0.05)
    ap.add_argument("--times", default="0,0.5,1,2,4,6,8,10,12,14,16")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--skip-transforms", action="store_true")
    ap.add_argument("--scenet0", default=None,
                    help="SceneT0 真值（PoseFrames 无 renderer 数据时用）")
    ap.add_argument("--only-scenet0", action="store_true")
    ap.add_argument("--spine-dir", default=None,
                    help="端到端校验导出的 Spine 目录（读 JSON 的 setup+deform）")
    ap.add_argument("--only-spine-dir", action="store_true")
    a = ap.parse_args()

    name = os.path.splitext(os.path.basename(a.prefab))[0]
    # 2026-09-18 起 Unity 侧的校准数据统一在 info\Data（旧的 info\Data 已搬走）
    data_dir = DATA if os.path.isdir(DATA) else os.path.join(a.assets, "Data")
    pose_path = a.pose or os.path.join(data_dir, "PoseFrames", name + ".json")
    pose = json.load(open(pose_path, encoding="utf-8-sig"))
    mdl, parts = load_parts(a.prefab, a.scene, a.assets)
    clip_name, clip = _choose_clip(mdl, a.assets, a.clip)
    rest = {}
    for tfid, td in mdl.transforms.items():
        q = td["quat"]
        rest[td["anim_path"]] = {
            "px": td["pos"][0], "py": td["pos"][1], "pz": td["pos"][2],
            "qx": q[0], "qy": q[1], "qz": q[2], "qw": q[3],
            "sx": td["scale"][0], "sy": td["scale"][1], "sz": td["scale"][2]}
    from ngui2spine.unity_anim2d import AnimSampler
    sampler = AnimSampler(clip, rest=rest)
    times = [float(t) for t in a.times.split(",") if t.strip()]
    sec = secondary_paths(mdl, a.clip, a.assets)
    lay = layer_paths(mdl, a.assets)
    if lay:
        n_before = len(sec)
        sec = sec | lay
        print("说明：%d 个节点由**主 Animator 的第 2 层及以上**驱动"
              "（真值只推进 Base Layer 的 clip），已在比对中排除"
              % (len(sec) - n_before))
    if sec:
        print("说明：共 %d 个部件/节点不参与逐顶点比对"
              "（副 Animator + 上层 Animator 层，Unity 真值未推进）" % len(sec))
    print("clip=%s  部件=%d  transform=%d  真值帧=%d"
          % (clip_name, len(parts), len(mdl.transforms), len(pose["frames"])))
    if a.only_spine_dir:
        compare_spine_dir(a.spine_dir, pose, times, a.top, skip_paths=sec)
        return
    if not a.skip_transforms:
        compare_transforms(mdl, sampler, pose, times, a.top)
    if a.only_scenet0:
        compare_scene_t0(mdl, parts, sampler, a.scenet0, a.top)
        return
    has_geom = any((f.get("skinned") or f.get("sprites"))
                   for f in pose["frames"][:3])
    if has_geom:
        compare_parts(mdl, parts, sampler, pose, times, a.top, skip_paths=sec)
    if a.scenet0:
        compare_scene_t0(mdl, parts, sampler, a.scenet0, a.top)
    if a.spine_dir:
        compare_spine_dir(a.spine_dir, pose, times, a.top, skip_paths=sec)


if __name__ == "__main__":
    main()
