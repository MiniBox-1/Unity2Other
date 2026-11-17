# -*- coding: utf-8 -*-
r"""**分骨骼**原型：把"单根骨 + 逐帧逐顶点 deform"换成"真正的 Spine 骨骼 + 加权 mesh"，
只为回答一个问题 —— **体积能不能小**。

和主转换器的关系：完全独立，不改主转换器；复用它的解析/采样/精灵网格代码，
贴图集也**直接复用现有产物**（因为 uvs 一样、region 还是 `tex0/tex1`）。

模型：
  · 每个"被部件用到过的 Unity transform（+ 其祖先）" → 一根 Spine 骨（局部 TRS 逐帧写键）；
  · SkinnedMeshRenderer 部件 → **加权 mesh**（`bones` + 每顶点 4 权重，顶点用 setup 世界坐标）；
  · SpriteRenderer / static 部件 → 挂在"它自己的 transform 骨"上的**无权 mesh**（顶点在骨局部）。

用法：
  python src/tools\bone_probe.py <prefab> <out_dir> [--assets A] [--scene S] [--anims lobby,Tep_1]
"""
# --- lo_uncen2Spine: 位置解析（自动插入，见 src/tools\deabs_paths.py）--
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
from unity2spine.paths import app_root as _app_root  # noqa: E402
# ---------------------------------------------------------------------

import argparse
import json
import math
import os
import shutil
import sys

HERE = _app_root()  # 项目根
sys.path.insert(0, HERE)

from ngui2spine.convert_2dmodel import _asset_path, build_character_model  # noqa: E402
from ngui2spine.static_prefab_spine import (                                # noqa: E402
    _part_points, _part_tris, _part_uvs, _sample_world_multi, ASSETS_DEFAULT,
    assignments_for_entry, enumerate_clips, load_character, make_samplers,
    probe_times_for)
from ngui2spine.unity_anim2d import euler_to_quat, trs_mat               # noqa: E402
from ngui2spine.unity_mesh import mat4_invert, mat4_vec                  # noqa: E402


def mat_decompose(m):
    """4x4 → (x, y, rotation_deg, scaleX, scaleY)：Spine 骨用的分解。

    取 x/y 轴列向量：`sx = |ex|`、`rot = atan2(ex.y, ex.x)`、`sy = |ey|`；
    左手/镜像（det<0）时把 `sy` 取负 —— 这正是 Spine 表达镜像的方式。
    """
    o = mat4_vec(m, (0.0, 0.0, 0.0))
    ex = [mat4_vec(m, (1.0, 0.0, 0.0))[i] - o[i] for i in range(3)]
    ey = [mat4_vec(m, (0.0, 1.0, 0.0))[i] - o[i] for i in range(3)]
    ox = o
    sx = math.hypot(ex[0], ex[1])
    sy = math.hypot(ey[0], ey[1])
    rot = math.degrees(math.atan2(ex[1], ex[0]))
    if ex[0] * ey[1] - ex[1] * ey[0] < 0:
        sy = -sy
    return ox[0], ox[1], rot, sx, sy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefab")
    ap.add_argument("out")
    ap.add_argument("--assets", default=ASSETS_DEFAULT)
    ap.add_argument("--scene", default=None)
    ap.add_argument("--anims", default="")
    ap.add_argument("--reuse-from", default="",
                    help="从这个已有产物目录复制 atlas/png（uvs 一样，可直接复用）")
    ap.add_argument("--tolerance", type=float, default=0.0,
                    help="骨键抽稀阈值（0=不抽稀，逐帧写）")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    mdl, parts = load_character(a.prefab, a.assets, a.scene)
    base = os.path.splitext(os.path.basename(a.prefab))[0]
    entries = enumerate_clips(mdl, a.assets)
    want = [x for x in (a.anims or "").split(",") if x]
    if want:
        entries = [e for e in entries if e["state"] in want]
    samplers = make_samplers(mdl, entries)
    print("角色 %s：部件 %d，动画 %d 条（%s）"
          % (base, len(parts), len(entries), ",".join(e["state"] for e in entries)))

    # setup 姿态的世界矩阵（下面判"平面性"用）
    e0 = entries[0]
    assign_all = assignments_for_entry(mdl, samplers, entries, e0)
    world_all = _sample_world_multi(mdl, assign_all, 0.0)

    def is_planar(tfid):
        """该 transform 在 setup 姿态下是否**把 XY 平面映到 XY 平面**。

        为什么必须筛：Spine 的骨只有 `(x,y,rotation,scaleX,scaleY)` 五个量，只能表达
        **平面内**的变换。这套 2D 立绘里有不少"渲染器宿主"节点带**离面旋转**
        （banshee 实测：`parts_Body` = 绕 X 轴 90°、`Size_root` = 绕 Y 轴 180°），
        它们的局部矩阵在 XY 上看是退化的（分解出 `scaleY = 0`）⇒ 一旦当成骨，
        **整棵子树会被压成一个点**（渲染出来就是"所有件挤成一团"）。
        Unity 里这些节点无所谓，因为蒙皮件的几何只由 `m_Bones` 决定、跟宿主节点无关。
        """
        m = world_all.get(tfid)
        if m is None:
            return False
        v = [float(x) for x in list(m)]          # 行主序 16 个数
        if len(v) < 16:
            return False
        # X/Y 轴没有 z 分量，且 Z 轴没有 x/y 分量 ⇒ 平面内变换
        return (abs(v[2]) < 1e-4 and abs(v[6]) < 1e-4
                and abs(v[8]) < 1e-4 and abs(v[9]) < 1e-4)

    # ---- 需要哪些骨：被部件用到过的 transform + 其祖先（**只收平面内的**）----
    need = set()

    def add_chain(tfid):
        if not tfid:                       # Unity 的 m_Bones 里有 0 占位（"无骨"）
            return
        cur, hops = tfid, 0
        while cur is not None and hops < 300:
            if cur in need:
                break
            if not is_planar(cur):
                break                      # 离面节点不进骨表（部件会挂到它上面的平面祖先）
            need.add(cur)
            cur = (mdl.transforms.get(cur) or {}).get("father")
            hops += 1

    for p in parts:
        if not (p.mesh or p.kind == "sprite"):
            continue
        # ⚠️ **不要把"渲染器宿主"节点本身当骨**：这批 2D 立绘里 `parts_*` 宿主常带
        # 离面旋转或 `scale = 0`（实测 banshee 的 `parts_Finger_R5` 是 `scaleY = -0`），
        # 一旦进骨表，整棵子树会被压成一个点 —— 而 Unity 里这些节点与蒙皮无关
        # （蒙皮件只看 `m_Bones`）。所以：**只收蒙皮骨骼（m_Bones）及其祖先**；
        # 部件（slot）挂到"离它最近的骨"上（见 `bone_tfid_of`）。
        bones_of = [b for b in (getattr(p, "bones", None) or []) if b]
        if bones_of:
            for b in bones_of:
                add_chain(b)
        else:
            add_chain(p.tfid)          # 无蒙皮骨骼的件（sprite/静态）才用自己那根
    need.discard(0)
    need.discard(None)
    # **父必须先于子**（Spine 解析时按名字找父，父不存在会直接崩）
    order = []
    seen = set()

    def walk(tfid):
        if not tfid or tfid in seen or tfid not in need or tfid not in mdl.transforms:
            return
        fa = (mdl.transforms.get(tfid) or {}).get("father")
        if fa in need:
            walk(fa)
        seen.add(tfid)
        order.append(tfid)

    for t in list(mdl.transforms):
        if t in need:
            walk(t)
    order = [t for t in order if t in mdl.transforms]      # 防御：别把 0/None 带进来

    def bone_name(tfid):
        td = mdl.transforms.get(tfid) or {}
        nm = (td.get("name") or "").replace("/", "_").replace(" ", "_")
        return "%s_%d" % (nm or "node", tfid)

    # ---- setup 姿态（第一条动画的 t=0）与逐帧局部分解 ----
    e0 = entries[0]
    assign0 = assignments_for_entry(mdl, samplers, entries, e0)

    def local_of(tfid, t):
        """该 transform 在时刻 t 的**局部**矩阵（副动画按其自身时长）。"""
        td = mdl.transforms[tfid]
        aa = assign0.get(tfid)
        if aa is None:
            return trs_mat(td["pos"], td["quat"], td["scale"])
        dur = aa["duration"]
        tt = t % dur if dur > 1e-6 else t
        sp = aa["sampler"].sample(aa.get("anim_path", td["anim_path"]), tt)
        q = sp["quat"] or euler_to_quat(sp["euler"])
        return trs_mat(sp["pos"], q, sp["scale"])

    world0 = _sample_world_multi(mdl, assign0, 0.0)
    xs = [q[0] for p in parts if p.mesh or p.kind == "sprite"
          for q in _part_points(p, world0) if q]
    ys = [q[1] for p in parts if p.mesh or p.kind == "sprite"
          for q in _part_points(p, world0) if q]
    ox, oy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    k = 100.0            # 输出单位：1 世界单位 = 100 单位（只为比体积，取整好读）

    bones = []
    for tfid in order:
        td = mdl.transforms[tfid]
        lx, ly, rot, sx, sy = mat_decompose(local_of(tfid, 0.0))
        b = {"name": bone_name(tfid), "x": round((lx) * k, 4),
             "y": round((ly) * k, 4), "rotation": round(rot, 4),
             "scaleX": round(sx, 5), "scaleY": round(sy, 5)}
        fa = td.get("father")
        if fa and fa in need:
            b["parent"] = bone_name(fa)
            # 根骨才减原点（子骨的 x/y 是相对父的）
        else:
            b["x"] = round((lx - ox) * k, 4)
            b["y"] = round((ly - oy) * k, 4)
        bones.append(b)

    # ---- 部件 → slot / attachment ----
    slots, skin = [], {}
    part_of_slot = {}

    def bone_tfid_of(tfid):
        """该部件该挂到哪根骨上：自己是平面骨就用自己，否则往上找最近的平面祖先。

        （离面节点不当骨；顶点用 3D 世界坐标反解到祖先骨局部，效果与 deform 路线一致。）
        """
        cur, hops = tfid, 0
        while cur is not None and hops < 300:
            if cur in need:
                return cur
            cur = (mdl.transforms.get(cur) or {}).get("father")
            hops += 1
        return None

    for p in parts:
        if not (p.mesh or p.kind == "sprite"):
            continue
        if p.kind == "sprite" and not p.sprite:
            continue
        uvs = _part_uvs(p)
        tris = _part_tris(p)
        pts = _part_points(p, world0)
        if not pts or len(pts) != len(uvs) or not tris:
            continue
        nm = p.name
        host = bone_tfid_of(p.tfid)
        if host is None:
            continue
        slot = {"name": nm, "bone": bone_name(host), "attachment": nm}
        slots.append(slot)
        uvs_flat = [round(c, 6) for uv in uvs for c in (uv if isinstance(uv, (list, tuple)) else (uv,))]
        att = {"type": "mesh", "uvs": uvs_flat,
               "triangles": list(tris), "width": 1, "height": 1}
        if p.kind in ("static", "sprite") or not (getattr(p, "bones", None) or []):
            # 无权：顶点在骨局部（把世界点乘回去）
            inv = mat4_invert(world0[host])
            v = []
            for q in pts:
                lq = mat4_vec(inv, (q[0], q[1], q[2]))
                v += [round(lq[0] * k, 4), round(lq[1] * k, 4)]
            att["vertices"] = v
        else:
            # 加权 mesh —— **spine 3.8 的打包格式**（这是这条路之前"一加载就崩"的原因）：
            #
            #   vertices = [boneCount, (骨下标, 该骨局部 x, 该骨局部 y, 权重), …] 每顶点一组
            #
            # 依据（2026-09-21 用官方 3.8 样例核对）：
            #   · `_reference\...\spine38\SkeletonJson.cpp::readVertices`：
            #       verticesLength == uvs.size 时按**无权**读，否则按上面打包格式读；
            #   · 官方样例 `_testdata\Spine\380_spineboy\export\spineboy-pro.json`
            #       （spine 3.8.55）的 head/torso 加权 mesh 就是这么存的：
            #       骨下标是**骨架 bones 的下标**，各影响点 `(x,y)` 是该骨**局部**坐标
            #       （用 `_scratch\check_spine38_weighted.py` 还原到骨架空间，误差 ≤0.06 px）；
            #   · `hull` = 顶点数（官方样例如此）。
            #
            # 旧原型写的是 **spine 4.x 的 `[x,y,w0,w1…]`** 布局 ⇒ 3.8 解析器把 x 当成
            # boneCount，越界读 ⇒ 连"4 顶点 1 骨"的最小 quad 都崩。
            raw_bones = list(p.bones or [])
            bone_idx_export = {tfid: i for i, tfid in enumerate(order)}
            raw = p.mesh.get("boneIndexRaw") or []
            wts = p.mesh.get("weights") or []
            verts = []
            for vi, q in enumerate(pts):
                infl = {}
                # Unity 的对应关系：`weights[vi][k]` 配 **`boneIndexRaw[vi][k]`**，
                # 后者是 `m_Bones` 的下标（实测 parts_breastbelt_03：
                # weights=(0.75,0.25,0,0)+boneIndexRaw=(1,0,0,0) ⇒ 0.75×Bones[1]+0.25×Bones[0]）
                wl = wts[vi] if vi < len(wts) else None
                bl2 = raw[vi] if vi < len(raw) else None
                if wl:
                    for kk, wv in enumerate(wl):
                        bi = (bl2[kk] if isinstance(bl2, (list, tuple)) and kk < len(bl2)
                              else (bl2 if not isinstance(bl2, (list, tuple)) else None))
                        if abs(float(wv)) < 1e-5 or not isinstance(bi, int):
                            continue
                        if 0 <= bi < len(raw_bones):
                            tf = raw_bones[bi]
                            if tf in bone_idx_export:
                                infl[tf] = infl.get(tf, 0.0) + float(wv)
                elif bl2 is not None:
                    for bi in (bl2 if isinstance(bl2, (list, tuple)) else [bl2]):
                        if isinstance(bi, int) and 0 <= bi < len(raw_bones):
                            tf = raw_bones[bi]
                            if tf in bone_idx_export:
                                infl[tf] = 1.0
                            break
                if not infl:                    # 没权重/下标不可用 → 挂到宿主骨
                    infl = {host: 1.0}
                # ⚠️ **绝不能跳过顶点**：`worldVerticesLength` = `len(uvs)/2`，
                # 少写一组就会让 spine 越界读（症状：加载后塌成一团 / 内存暴涨）。
                # 所以每个顶点都必须写出至少一组 (骨, x, y, 权重)。
                tot = sum(abs(w) for w in infl.values()) or 1.0
                verts.append(len(infl))
                for tf in sorted(infl, key=lambda z: bone_idx_export[z]):
                    lq = mat4_vec(mat4_invert(world0[tf]), (q[0], q[1], q[2]))
                    verts += [bone_idx_export[tf],
                              round(lq[0] * k, 4), round(lq[1] * k, 4),
                              round(infl[tf] / tot, 5)]
            att["hull"] = len(pts)
            att["vertices"] = verts
        att["path"] = "tex0"
        skin.setdefault(nm, {})[nm] = att
        part_of_slot[nm] = p

    # ---- 动画：每根骨逐帧写 translate/rotate/scale（可抽稀）----
    animations = {}
    for e in entries:
        assign = assignments_for_entry(mdl, samplers, entries, e)
        times = probe_times_for(e)

        def loc_at(tfid, t, assign=assign):
            td = mdl.transforms[tfid]
            aa = assign.get(tfid)
            if aa is None:
                return trs_mat(td["pos"], td["quat"], td["scale"])
            dur = aa["duration"]
            tt = t % dur if dur > 1e-6 else t
            sp = aa["sampler"].sample(aa.get("anim_path", td["anim_path"]), tt)
            q = sp["quat"] or euler_to_quat(sp["euler"])
            return trs_mat(sp["pos"], q, sp["scale"])

        anim = {}
        for tfid in order:
            tn, rn, sn = [], [], []
            for t in times:
                lx, ly, rot, sx, sy = mat_decompose(loc_at(tfid, t))
                if (mdl.transforms[tfid].get("father")) not in need:
                    lx, ly = lx - ox, ly - oy
                if a.tolerance <= 0:
                    tn.append({"time": round(t, 4), "x": round(lx * k, 4),
                               "y": round(ly * k, 4)})
                    rn.append({"time": round(t, 4), "angle": round(rot, 4)})
                    sn.append({"time": round(t, 4), "x": round(sx, 5),
                               "y": round(sy, 5)})
                else:
                    if (not tn or abs(tn[-1]["x"] - lx * k) > a.tolerance
                            or abs(tn[-1]["y"] - ly * k) > a.tolerance):
                        tn.append({"time": round(t, 4), "x": round(lx * k, 4),
                                   "y": round(ly * k, 4)})
                    if not rn or abs(rn[-1]["angle"] - rot) > a.tolerance:
                        rn.append({"time": round(t, 4), "angle": round(rot, 4)})
                    if (not sn or abs(sn[-1]["x"] - sx) > a.tolerance / 100.0
                            or abs(sn[-1]["y"] - sy) > a.tolerance / 100.0):
                        sn.append({"time": round(t, 4), "x": round(sx, 5),
                                   "y": round(sy, 5)})
            ch = {}
            if tn:
                ch["translate"] = tn
            if rn:
                ch["rotate"] = rn
            if sn:
                ch["scale"] = sn
            if ch:
                anim[bone_name(tfid)] = ch
        animations[e["state"]] = {"bones": anim}
        print("  动画 %-28s 骨键 %d 根 × %d 帧" % (e["state"], len(anim), len(times)))

    skel = {"skeleton": {"hash": "ngui2spine-bones-" + base, "spine": "3.8.99",
                         "x": 0, "y": 0, "width": 0, "height": 0, "fps": 60},
            "bones": bones, "slots": slots,
            "skins": [{"name": "default", "attachments": skin}],
            "animations": animations}
    os.makedirs(a.out, exist_ok=True)
    js = os.path.join(a.out, base + "_static.json")
    with open(js, "w", encoding="utf-8") as fp:
        json.dump(skel, fp, ensure_ascii=False)
    print("写出 %s（%.2f MB）：骨 %d / 槽位 %d / 动画 %d"
          % (js, os.path.getsize(js) / 1e6, len(bones), len(slots), len(animations)))
    if a.reuse_from:
        for f in os.listdir(a.reuse_from):
            if f.endswith((".atlas", ".png")) or f == ".config.json":
                src = os.path.join(a.reuse_from, f)
                dst = os.path.join(a.out, f.replace(base + "_static", base + "_static")
                                   if False else f)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
        print("已复用贴图集：%s" % a.reuse_from)


if __name__ == "__main__":
    main()
