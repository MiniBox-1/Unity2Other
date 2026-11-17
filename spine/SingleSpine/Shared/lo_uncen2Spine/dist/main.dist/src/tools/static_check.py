# -*- coding: utf-8 -*-
"""静态检查器：确认"动画/场景里引用的资源"都出现在导出产物里。

回答四个问题：
  1. 场景子树里有哪些 Renderer（蒙皮/静态/sprite），其中哪些**没有**出现在导出的
     Spine 文件里——尤其是**会被动画改变**的那些（最隐蔽：静止姿态看不出，
     播放时才少东西，例如"动画中才放大出现的光晕"）；
  2. 动画曲线里的 path 是否都能对应到场景节点（Unity 会把超长 path 换行续写，
     旧解析会漏，这里能立刻发现）；
  3. 导出产物里有没有场景里根本不存在的额外部件；
  4. 场景里有、但结构上导不出的部件（sprite 引用为空 / 贴图或 Mesh 找不到 /
     渲染器被禁用），逐条给原因。

用法:
  python tools/static_check.py <prefab> [--scene <save.unity>] [--clip lobby]
      [--spine-dir <导出目录>] [--dt 0.05] [--top 20] [--json 报告.json]

退出码：发现"动画中引用但未导出"、"导出里有场景里没有"或"曲线 path 对不上节点"
时为 1，可直接用于批量检查。
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

from ngui2spine.convert_2dmodel import _asset_path          # noqa: E402
from ngui2spine.static_prefab_spine import (                # noqa: E402
    _choose_clip, _part_points, _sample_world, _sample_world_multi,
    active_flip_times, assignments_for_entry, enumerate_clips, load_character,
    make_samplers, node_visible, part_visible, rest_by_anim_path)
from ngui2spine.unity_2dmodel import rel_path_in             # noqa: E402
from ngui2spine.unity_anim2d import AnimSampler             # noqa: E402

ASSETS = _resolve(r"D:\VB\Search\NormalLocal\lastOrign\Assets")


def _renderer_reason(mdl, r, assets):
    """渲染器结构上导不出的原因；能导出返回 None。"""
    if not r.get("enabled", True):
        return "渲染器被禁用(m_Enabled=0)"
    # m_Bones 非空但全是空引用：Unity 求蒙皮矩阵拿到空骨骼 → 顶点塌成一点，
    # 一个像素都不画（渲染器自己仍 `isVisible`、bounds 照报，容易被误判成
    # "静态可见却没导出"）。转换器已按同一判据排除，这里同步口径。
    # 2026-09-18：constantias2_{normal,skin1S} 的 CS_parts_hair_3(order=-3)、
    # cerberus_skin3 的 Part_Eye_Close/Smile_{L,R}_26(order=26)。
    if r["kind"] == "skinned" and r.get("bones") and not any(r["bones"]):
        return "SkinnedMeshRenderer 的 m_Bones 全是空引用（Unity 蒙皮塌陷、不渲染）"
    if r["kind"] == "sprite":
        sg = r.get("spriteGuid")
        if not sg:
            return "SpriteRenderer 没有 sprite 引用(m_Sprite=0)"
        sp = _asset_path(assets, sg)
        if not sp or not os.path.isfile(sp):
            return "Sprite 资源找不到(guid=%s)" % sg
        # ★ 贴图命中"编辑器辅助图"屏蔽规则（BoneJoint/IKControl/splineControl/icon-* …）的
        #   渲染器**是转换器有意不导出的**（这是 puppetz 的骨骼/控制体辅助图，不是画面内容）。
        #   2026-10-10：`2DModel_BR_Phoenix_NS1` 的 hiddenBone_3/4/5/6 用 `BoneJoint_8.png`，
        #   动画确实 K 了它们的 transform，于是被判成"动画引用了但没导出" → 误报。
        #   这里按贴图名判定，把它们归到 `unexportable` 并说明原因。
        try:
            from unity2spine.convert.static_prefab_spine import (
                skip_texture_patterns)
            _pats = skip_texture_patterns(None)
        except Exception:                                       # noqa: BLE001
            _pats = ()
        _tn = os.path.basename(sp).lower()
        for _pat in _pats:
            if _pat.lower() in _tn:
                return ("贴图被有意屏蔽（编辑器辅助图 %s，命中规则 %r）"
                        % (os.path.basename(sp), _pat))
        return None
    mg = r.get("meshGuid")
    if not mg:
        return "没有 Mesh 引用"
    mp = _asset_path(assets, mg)
    if not mp or not os.path.isfile(mp):
        return "Mesh 资源找不到(guid=%s)" % mg
    return None


def build_report(prefab, assets=ASSETS, scene=None, clip_hint=None, dt=0.05,
                 spine_dir=None, pose_path=None):
    """返回检查结果 dict（不打印），供 CLI 或批量脚本使用。"""
    mdl, parts = load_character(prefab, assets, scene)
    if not parts:
        raise SystemExit("没有解析到部件: " + prefab)
    clip_name, clip = _choose_clip(mdl, assets, clip_hint)
    if clip is None:
        raise SystemExit("没有可用 AnimatorClip: " + prefab)
    sampler = AnimSampler(clip, rest=rest_by_anim_path(mdl))

    # ---- 覆盖所有 Animator 的所有 clip ----
    rest = rest_by_anim_path(mdl)
    entries = enumerate_clips(mdl, assets)
    samplers = make_samplers(mdl, entries)
    assign_of = {e["name"]: assignments_for_entry(mdl, samplers, entries, e)
                 for e in entries} if entries else {}

    def timeline(e, step):
        dur = e["duration"]
        tl, t = [], 0.0
        while t <= dur + 1e-6:
            tl.append(round(t, 6))
            t += step
        if not tl or tl[-1] != round(dur, 6):
            tl.append(round(dur, 6))
        return tl

    # 每个 clip 用较粗的步长扫一遍（检查用，不必和导出同密度）
    step = max(dt, 0.1)

    def probe_times(e):
        ts = set(timeline(e, step))
        # SetActive 的关键帧时刻也要探测：可见窗口可能短于扫描步长
        cl = e["clip"] or {}
        tans_all = cl.get("active_tan") or {}
        for path, keys in (cl.get("active") or {}).items():
            for kt, _v in keys:
                ts.add(round(kt, 6))
            # 插值曲线（slope=0）的可见窗从"离开 0"那一刻开始，不在关键帧上
            tans = tans_all.get(path)
            if tans and len(tans) == len(keys):
                ts.update(active_flip_times(keys, tans))
        return sorted(ts)

    times_of = {e["name"]: probe_times(e) for e in entries}
    worlds = {}
    for e in entries:
        for tm in times_of[e["name"]]:
            worlds[(e["name"], tm)] = _sample_world_multi(
                mdl, assign_of[e["name"]], tm)

    # 逐部件统计"跨所有 clip"的尺寸/位移：任何一条动画里动过，就算"动画会改变"
    info_by_path = {}
    for p in parts:
        sizes, centres, in_clip = [], [], set()
        active_any = False
        for e in entries:
            for tm in times_of[e["name"]]:
                if part_visible(mdl, e["clip"], tm, p.tfid):
                    active_any = True
                pts = _part_points(p, worlds[(e["name"], tm)])
                if not pts:
                    sizes.append(0.0)
                    centres.append((0.0, 0.0))
                    continue
                xs = [q[0] for q in pts]
                ys = [q[1] for q in pts]
                sz = max(max(xs) - min(xs), max(ys) - min(ys))
                sizes.append(sz)
                centres.append(((min(xs) + max(xs)) / 2.0,
                                (min(ys) + max(ys)) / 2.0))
                if sz > 1e-4:
                    in_clip.add(e["name"])
        size0 = sizes[0] if sizes else 0.0
        cx0, cy0 = centres[0] if centres else (0.0, 0.0)
        move = max((math.dist(c, (cx0, cy0)) for c in centres), default=0.0)
        scale_change = (max(sizes) - min(sizes)) if sizes else 0.0
        info_by_path[p.full_path] = {
            "max_size": max(sizes) if sizes else 0.0,
            "size0": size0,
            "move": move, "scale_change": scale_change,
            "animated": move > 1e-3 or scale_change > 1e-3,
            "visible_at_all": (max(sizes) if sizes else 0.0) > 1e-5,
            "active_any": active_any,
            "visible_clips": sorted(in_clip),
        }

    exported = {}
    can_compare = bool(spine_dir)
    if spine_dir:
        info_path = os.path.join(spine_dir, "_static_info.json")
        if not os.path.isfile(info_path):
            raise SystemExit("导出目录缺少 _static_info.json: " + spine_dir)
        info = json.load(open(info_path, encoding="utf-8-sig"))
        if not info.get("partsMeta"):
            can_compare = False
            print("[warn] %s 是旧格式（没有 partsMeta），只能做曲线 path 检查；"
                  "请用当前版本重新导出后再比对部件。" % info_path)
        for pm in info.get("partsMeta") or []:
            exported[pm["path"]] = pm

    # ---- 曲线 path 检查：每条 clip 的 path 都相对它自己的 Animator 宿主 ----
    path_by_go = {t["go"]: t.get("path", "") for t in mdl.transforms.values()}

    def rel_set(host_go):
        """该 Animator 宿主下的全部相对路径（按宿主**全路径**分段截断）。"""
        out = set()
        for td in mdl.transforms.values():
            rel = rel_path_in(path_by_go.get(host_go, ""), td.get("path", ""))
            if rel is not None:
                out.add(rel)
        return out

    valid_by_go = {e["go"]: rel_set(e["go"]) for e in entries}
    other_valid_by_go = {}
    for e in entries:
        s = set()
        for go, vs in valid_by_go.items():
            if go != e["go"]:
                s |= vs
        other_valid_by_go[e["go"]] = s

    curve_paths = 0
    unknown_paths = []
    clip_report = []
    for e in entries:
        valid = valid_by_go[e["go"]]
        n_curves = len(e["clip"]["curves"])
        curve_paths += n_curves
        bad = [c.path for c in e["clip"]["curves"] if c.path not in valid]
        # 不在本角色子树里的曲线：若末段与某个导出部件同名 → 视为异常；
        # 否则多半是粒子/组件曲线（Unity 对组件用 "path_xxxx" 这类哈希路径），
        # 我们本来就不导出这些子树，只作提示。
        # 例外：同一个 Controller 被两个 Animator 播放时，另一份拷贝里指向
        # **对方子树**的曲线在本宿主下解析不到，Unity 里同样是空转（只打
        # warning），那不是导出缺陷——单独统计，不算问题。
        leaf_names = {p.split("/")[-1] for p in exported} or \
            {p["path"].split("/")[-1] for p in info.get("partsMeta") or []}
        other_bad = [p for p in bad if p in other_valid_by_go[e["go"]]]
        real_bad = [p for p in bad if p not in other_valid_by_go[e["go"]]
                    and p.split("/")[-1] in leaf_names]
        info_bad = [p for p in bad if p not in real_bad
                    and p not in other_bad]
        clip_report.append({"animator": e["animator"], "state": e["state"],
                            "name": e["name"], "duration": e["duration"],
                            "curves": n_curves,
                            "unknownCurves": len(real_bad),
                            "otherAnimatorCurves": len(other_bad),
                            "nonRenderCurves": info_bad,
                            "isMain": bool(e["is_main"])})
        for p in real_bad:
            unknown_paths.append({"clip": e["name"],
                                  "animator": e["animator"], "path": p})

    # ---- 用 Unity 帧真值交叉验证"可见性"（真值可见而我们算成不可见 = 采样 bug）----
    truth_size = {}
    if pose_path is None:
        cand = os.path.join(ASSETS, "Data", "PoseFrames",
                            os.path.splitext(os.path.basename(prefab))[0]
                            + ".json")
        pose_path = cand if os.path.isfile(cand) else None
    if pose_path and os.path.isfile(pose_path):
        from ngui2spine.unity_mesh import mat4_vec
        pose = json.load(open(pose_path, encoding="utf-8-sig"))
        for fr in pose.get("frames") or []:
            for e in fr.get("sprites") or []:
                wc = e.get("worldCorners") or []
                if len(wc) < 4:
                    continue
                xs = [c[0] for c in wc]
                ys = [c[1] for c in wc]
                sz = max(max(xs) - min(xs), max(ys) - min(ys))
                p = e.get("path")
                truth_size[p] = max(truth_size.get(p, 0.0), sz)
            for e in fr.get("skinned") or []:
                l2w = e.get("localToWorld")
                pos = e.get("positions") or []
                if not l2w or not pos:
                    continue
                flat = [v for row in l2w for v in row]
                pts = [mat4_vec(flat, v) for v in pos]
                xs = [q[0] for q in pts]
                ys = [q[1] for q in pts]
                sz = max(max(xs) - min(xs), max(ys) - min(ys))
                p = e.get("path")
                truth_size[p] = max(truth_size.get(p, 0.0), sz)

    visibility_conflicts = []
    for path, probe in info_by_path.items():
        tv = truth_size.get(path)
        if tv is None:
            continue
        ours_visible = probe["max_size"] > 1e-3
        truth_visible = tv > 1e-3
        probe["truth_max_size"] = round(tv, 4)
        if truth_visible and not ours_visible:
            visibility_conflicts.append({
                "path": path, "truth_max_size": round(tv, 4),
                "our_max_size": round(probe["max_size"], 4),
                "reason": "Unity 真值里可见，静态管线算成不可见（采样/退化判断有误）"})

    keep_gos = {t["go"] for t in mdl.transforms.values()}
    scene_renderers = []
    for r in mdl.renderers:
        if r.get("go") not in keep_gos:
            continue
        tf = mdl.transforms.get(r.get("tfid")) or {}
        scene_renderers.append({"kind": r["kind"], "path": tf.get("path", ""),
                                "reason": _renderer_reason(mdl, r, assets)})

    missing_animated, missing_static = [], []
    unexportable, extra, invisible = [], [], []
    # 转换器自己记的"有意排除"清单（`_static_info.json` 的 `excludedParts`）：
    # 里面带**排除原因**（贴图被屏蔽 / m_Bones 全空 / 始终 SetActive=0 …）。
    # 2026-10-10：`PECS_ElvenForestmaker_NS1_DL_N` 的 parts_Eyebrow_Normal / parts_Milk5
    # 其实是"始终 SetActive=0"被有意排除，但本工具的 active_any 判据比转换器的
    # visible_anywhere 松，于是误报成"动画引用了但没导出"。这里直接采信转换器的记录。
    excl_reason = {}
    try:
        _ip = os.path.join(spine_dir, "_static_info.json")
        if os.path.isfile(_ip):
            _info = json.load(open(_ip, encoding="utf-8-sig"))
            for _e in (_info.get("excludedParts") or []):
                if _e.get("path"):
                    excl_reason[_e["path"]] = _e.get("reason") or "转换器有意排除"
    except (ValueError, OSError):
        pass
    scene_paths = set()
    for r in scene_renderers:
        path = r["path"]
        scene_paths.add(path)
        if path in exported:
            continue
        if not can_compare:
            continue
        entry = {"path": path, "kind": r["kind"], "reason": r["reason"]}
        if not entry["reason"] and path in excl_reason:
            entry["reason"] = "转换器有意排除：%s" % excl_reason[path]
            unexportable.append(entry)
            continue
        if r["reason"]:
            unexportable.append(entry)
            continue
        probe = info_by_path.get(path)
        if probe is None:
            entry["reason"] = entry["reason"] or "离线解析阶段被跳过"
            unexportable.append(entry)
            continue
        entry.update({"max_size": round(probe["max_size"], 4),
                      "size_at_t0": round(probe["size0"], 4),
                      "move": round(probe["move"], 4),
                      "animated": probe["animated"],
                      "truth_max_size": probe.get("truth_max_size")})
        if not probe.get("active_any", True):
            entry["reason"] = ("Unity 里始终 SetActive=0"
                               "（表情备选件，导出时已排除）")
            unexportable.append(entry)
        elif not probe["visible_at_all"]:
            invisible.append(entry)
        elif probe["animated"]:
            missing_animated.append(entry)
        else:
            missing_static.append(entry)
    for path in exported:
        if path not in scene_paths:
            extra.append({"path": path, "name": exported[path].get("name")})

    return {"prefab": prefab, "scene": scene, "clip": clip_name,
            "poseTruth": pose_path,
            "canCompareParts": can_compare,
            "sceneRenderers": len(scene_renderers),
            "exportedParts": len(exported),
            "animators": sorted({e["animator"] for e in entries}),
            "clips": clip_report,
            "curvePaths": curve_paths,
            "unknownCurvePaths": unknown_paths,
            "visibilityConflicts": visibility_conflicts,
            "missingAnimated": missing_animated,
            "missingStatic": missing_static,
            "unexportable": unexportable,
            "invisibleAllTime": invisible,
            "extraInExport": extra}


def print_report(rep, top=20):
    def show(title, rows, note=""):
        print("\n== %s（%d）%s" % (title, len(rows), note))
        for e in rows[:top]:
            extra_txt = ""
            if "max_size" in e:
                extra_txt = "  最大尺寸 %s / t=0 尺寸 %s / 位移 %s" % (
                    e["max_size"], e.get("size_at_t0"), e.get("move"))
                if e.get("truth_max_size") is not None:
                    extra_txt += " / Unity 真值最大 %s" % e["truth_max_size"]
            print("   - %s%s%s" % (
                e["path"].split("ch_root/")[-1] if "ch_root/" in e["path"]
                else e["path"],
                ("  [%s]" % e["reason"]) if e.get("reason") else "",
                extra_txt))
        if len(rows) > top:
            print("   ... 其余 %d 条见 JSON 报告" % (len(rows) - top))

    print("=" * 78)
    print("静态检查：%s / setup clip=%s / 场景渲染器 %d / 导出部件 %d"
          % (os.path.basename(rep["prefab"]), rep["clip"],
             rep["sceneRenderers"], rep["exportedParts"]))
    print("Animator：%s" % "，".join(rep.get("animators") or []))
    print("Clip（全部检查）：")
    for c in rep.get("clips") or []:
        extra = ""
        if c.get("nonRenderCurves"):
            extra = "  （组件/粒子曲线 %d 条，已忽略）" % len(c["nonRenderCurves"])
        if c.get("otherAnimatorCurves"):
            extra += ("  （指向另一个 Animator 子树 %d 条，"
                      "Unity 里同样是空转）" % c["otherAnimatorCurves"])
        print("   %-12s animator=%-16s %6.2fs 曲线 %3d 未匹配 %d%s%s"
              % (c["name"], c["animator"], c["duration"], c["curves"],
                 c["unknownCurves"], extra,
                 "" if c["isMain"] else "  [副 Animator]"))
    print("=" * 78)
    show("① 动画会改变、但导出里没有（必须修）", rep["missingAnimated"])
    show("② 静态可见、但导出里没有（建议修）", rep["missingStatic"])
    show("③ 场景里有但本来导不出（原因见括号）", rep["unexportable"])
    show("④ 整段动画尺寸为 0（Unity 里也不可见，可忽略）",
         rep["invisibleAllTime"])
    show("⑤ 导出里有、场景里没有（异常）", rep["extraInExport"])
    show("⑥ 与 Unity 帧真值不一致（真值可见、我们算成不可见）",
         rep.get("visibilityConflicts") or [])
    print("\n== 曲线 path 解析（所有 clip）==")
    if rep["unknownCurvePaths"]:
        print("   对不上场景节点的 path %d 条：" % len(rep["unknownCurvePaths"]))
        for u in rep["unknownCurvePaths"][:top]:
            print("     [%s/%s] %s" % (u["animator"], u["clip"], u["path"]))
    else:
        print("   %d 条曲线 path（%d 条动画）全部能对应场景节点"
              % (rep["curvePaths"], len(rep["clips"])))
    problems = bool(rep["missingAnimated"] or rep["extraInExport"]
                    or rep["unknownCurvePaths"]
                    or rep.get("visibilityConflicts"))
    print("\n结论：%s" % ("发现需要处理的问题（见①⑤与曲线 path）"
                          if problems else "未发现“动画中引用但未导出”的资源"))
    return 1 if problems else 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("prefab")
    ap.add_argument("--assets", default=ASSETS)
    ap.add_argument("--scene", default=None)
    ap.add_argument("--clip", default=None)
    ap.add_argument("--spine-dir", default=None,
                    help="导出目录（读 _static_info.json 的部件清单）")
    ap.add_argument("--dt", type=float, default=0.05)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--json", default=None, help="把报告写成 JSON")
    ap.add_argument("--pose", default=None,
                    help="Unity 帧真值 JSON（默认自动找 PoseFrames/<角色>.json）")
    a = ap.parse_args(argv)
    rep = build_report(a.prefab, a.assets, a.scene, a.clip, a.dt, a.spine_dir,
                       a.pose)
    code = print_report(rep, a.top)
    if a.json:
        parent = os.path.dirname(os.path.abspath(a.json))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(a.json, "w", encoding="utf-8") as fp:
            json.dump(rep, fp, ensure_ascii=False, indent=1)
        print("报告已写入:", a.json)
    return code


if __name__ == "__main__":
    sys.exit(main())
