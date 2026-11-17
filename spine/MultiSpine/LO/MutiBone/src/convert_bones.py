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
  python src\convert_bones.py <prefab> <out_dir> [--assets A] [--scene S]
      [--reuse-from 主产物目录] [--anims lobby,Tep_1] [--simplify 0.05]
"""
import argparse
import json
import math
import os
import re
import shutil
import sys

# 多骨骼分支独立于主交付：这里只借用 Unity2Spine 的解析/采样库，不改它。
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
LIB = os.path.join(REPO, "SingleSpine", "Shared", "Unity2Spine")
sys.path.insert(0, LIB)
sys.path.insert(0, os.path.join(LIB, "src"))

from ngui2spine.convert_2dmodel import _asset_path, build_character_model  # noqa: E402
from ngui2spine.static_prefab_spine import (                                # noqa: E402
    _part_points, _part_tris, _part_uvs, _sample_world_multi, ASSETS_DEFAULT,
    assignments_for_entry, enumerate_clips, load_character, make_samplers,
    probe_times_for, hierarchy_ranks, slot_key_with_rank, _key_vals_differ,
    color_timeline, compose_layers, rest_by_anim_path, resolve_clip_paths,
    _main_animator_go, part_visible)
from ngui2spine.unity_2dmodel import parse_animator_layers            # noqa: E402
from ngui2spine.unity_anim2d import parse_clip                       # noqa: E402
from ngui2spine.unity_anim2d import euler_to_quat, trs_mat               # noqa: E402
from ngui2spine.unity_mesh import mat4_vec                              # noqa: E402
from unity2spine.spine.spine38_binary_writer import (                    # noqa: E402
    write_skeleton_binary)
from shared_skin_audit import drop_candidates                           # noqa: E402


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


def _mat_mul(a, b):
    """4x4（行主序、扁平 16 个数）矩阵乘法 a·b。"""
    out = [0.0] * 16
    for r in range(4):
        for c in range(4):
            out[r * 4 + c] = sum(a[r * 4 + kk] * b[kk * 4 + c] for kk in range(4))
    return out


def _planar_inverse_point(matrix, point):
    """Map a world XY point through the inverse of a matrix's planar projection."""
    a, b = float(matrix[0]), float(matrix[1])
    c, d = float(matrix[4]), float(matrix[5])
    tx, ty = float(matrix[3]), float(matrix[7])
    det = a * d - b * c
    if abs(det) < 1e-12:
        return 0.0, 0.0
    dx, dy = float(point[0]) - tx, float(point[1]) - ty
    return ((d * dx - b * dy) / det,
            (-c * dx + a * dy) / det)


def _planar_apply(matrix, x, y):
    """Apply a row-major 4x4 matrix to an XY point."""
    return (float(matrix[0]) * x + float(matrix[1]) * y + float(matrix[3]),
            float(matrix[4]) * x + float(matrix[5]) * y + float(matrix[7]))


def _planar_inverse_vector(matrix, x, y):
    """Apply only the inverse 2x2 linear part of a row-major 4x4 matrix."""
    a, b = float(matrix[0]), float(matrix[1])
    c, d = float(matrix[4]), float(matrix[5])
    det = a * d - b * c
    if abs(det) < 1e-12:
        return 0.0, 0.0
    return ((d * x - b * y) / det,
            (-c * x + a * y) / det)


def _simplify(keys, fields, eps):
    """用 Ramer-Douglas-Peucker 去掉能由首尾键线性插值表示的中间键。

    Spine 3.8 默认对关键帧做线性插值，因此只要中间键到最终保留线段的
    最大误差不超过 ``eps``，就可以安全删除。不能只比较相邻两键：
    那样会在连续、带噪声的曲线上反复保留局部变化，起不到压缩作用。
    """
    if len(keys) < 3:
        return keys

    keep = {0, len(keys) - 1}
    pending = [(0, len(keys) - 1)]
    while pending:
        lo, hi = pending.pop()
        a, c = keys[lo], keys[hi]
        span = c["time"] - a["time"]
        if span <= 0:
            continue
        worst_i, worst_err = -1, 0.0
        for i in range(lo + 1, hi):
            b = keys[i]
            f = (b["time"] - a["time"]) / span
            err = max(abs(b[fld] - (a[fld] + (c[fld] - a[fld]) * f))
                      for fld in fields)
            if err > worst_err:
                worst_i, worst_err = i, err
        if worst_err > eps:
            keep.add(worst_i)
            pending.append((lo, worst_i))
            pending.append((worst_i, hi))
    return [keys[i] for i in sorted(keep)]


def _simplify_deform(frames, eps):
    """RDP-simplify complete per-frame deform arrays without dropping vertices."""
    if eps <= 0 or len(frames) < 3:
        return frames
    keep = {0, len(frames) - 1}
    pending = [(0, len(frames) - 1)]
    while pending:
        lo, hi = pending.pop()
        a, c = frames[lo], frames[hi]
        span = c["time"] - a["time"]
        if span <= 0:
            continue
        worst_i, worst_err = -1, 0.0
        av, cv = a["vertices"], c["vertices"]
        for i in range(lo + 1, hi):
            b = frames[i]["vertices"]
            f = (frames[i]["time"] - a["time"]) / span
            err = max(abs(b[j] - (av[j] + (cv[j] - av[j]) * f))
                      for j in range(min(len(av), len(b), len(cv))))
            if err > worst_err:
                worst_i, worst_err = i, err
        if worst_err > eps:
            keep.add(worst_i)
            pending.append((lo, worst_i))
            pending.append((worst_i, hi))
    return [frames[i] for i in sorted(keep)]


def _animation_times_for(entry):
    """主转换器的采样口径 + Unity 同刻重复键的瞬时切换前后帧。"""
    cl = entry.get("clip") or {}
    dur = float(entry.get("duration") or cl.get("duration") or 0.0)
    times = set(probe_times_for(entry))
    for curve in (cl.get("curves") or []):
        grouped = {}
        for key_time, value in (getattr(curve, "keys", None) or []):
            grouped.setdefault(round(key_time, 6), []).append(value)
        for key_time, values in grouped.items():
            if len(values) < 2:
                continue
            if not any(_key_vals_differ(values[0], value)
                       for value in values[1:]):
                continue
            if 1e-3 <= key_time <= dur - 1e-3:
                times.add(round(key_time - 1e-3, 6))
                times.add(round(key_time + 1e-3, 6))
    return sorted(t for t in times if -1e-9 <= t <= dur + 1e-6)


def _add_visibility_transitions(mdl, entry, parts, times):
    """Refine attachment on/off changes to the first frame that crosses threshold."""
    if not times:
        return times
    clip = entry.get("clip") or {}
    extra = set()
    for part in parts:
        if not (part.mesh or part.kind == "sprite"):
            continue
        previous = part_visible(mdl, clip, times[0], part.tfid)
        for t0, t1 in zip(times, times[1:]):
            current = part_visible(mdl, clip, t1, part.tfid)
            if current != previous:
                lo, hi = t0, t1
                for _ in range(24):
                    mid = (lo + hi) / 2.0
                    if part_visible(mdl, clip, mid, part.tfid) == previous:
                        lo = mid
                    else:
                        hi = mid
                extra.add(round(hi, 6))
            previous = current
    return sorted(set(times) | extra)


def _static_slot_color(meta):
    color = (meta or {}).get("color") or "ffffffff"
    blend = (meta or {}).get("blend") or "normal"
    # 非烘焙、非加色的完全透明静态 slot 在“多骨多 mesh”批次下会被部分运行时
    # 错当成后续 mesh 的共享染色状态（Banshee 胸/躯干整批变透明）。这些件的
    # 实际可见性由纹理 alpha 和 attachment 时间轴决定，静态色保持白色即可。
    if (color.lower().endswith("00")
            and not (meta or {}).get("multiplyBaked")
            and blend == "normal"):
        return "ffffffff"
    return color


def _compose_overlay_layers(mdl, assets, entries):
    """Replicate the main converter's secondary Animator-layer composition."""
    controller = _asset_path(assets, getattr(mdl, "animator_controller_guid", None) or "")
    if not controller or not os.path.isfile(controller):
        return
    try:
        layers = parse_animator_layers(controller)
    except Exception as exc:                     # noqa: BLE001
        print("[warn] AnimatorController 层解析失败：%r" % (exc,))
        return
    if not layers:
        return

    state_to_layer = {}
    layer_states = []
    for layer_index, layer in enumerate(layers):
        states = []
        for name, guid in (layer.get("states") or []):
            path = _asset_path(assets, guid)
            if path and os.path.isfile(path):
                states.append((name, path))
        default_guid = layer.get("defaultClipGuid") or ""
        default_path = _asset_path(assets, default_guid)
        default_name = next(
            (name for name, path in states
             if default_path and os.path.abspath(path) == os.path.abspath(default_path)),
            states[0][0] if states else "")
        for name, _path in states:
            state_to_layer.setdefault(name, layer_index)
        layer_states.append((layer_index, states, default_name))

    def tokens(name):
        return set(part for part in re.split(r"[^a-z0-9]+", (name or "").lower())
                   if part)

    def variant(name):
        lower = (name or "").lower()
        return next((tag for tag in ("2side", "1side", "nochain", "break", "fall")
                     if tag in lower), "")

    rest = rest_by_anim_path(mdl)
    applied = 0
    for entry in entries:
        own_layer = state_to_layer.get(entry["state"])
        if own_layer is None:
            continue
        entry_tokens = tokens(entry["state"])
        overlays = []
        for layer_index, states, default_name in layer_states:
            if layer_index == own_layer:
                continue
            if not states:
                continue
            default_variant = variant(default_name)
            best = None
            best_score = -1
            for name, path in states:
                score = len(entry_tokens & tokens(name))
                if (score > best_score
                        or (score == best_score and best is not None
                            and variant(name) == default_variant
                            and variant(best[0]) != default_variant)):
                    best = (name, path)
                    best_score = score
            layer = layers[layer_index]
            if best is None or best_score <= 0:
                default_path = _asset_path(assets, layer.get("defaultClipGuid") or "")
                if not (default_path and os.path.isfile(default_path)):
                    continue
                best = (default_name, default_path)
            overlays.append((
                layer.get("name") or "layer",
                resolve_clip_paths(mdl, _main_animator_go(mdl), parse_clip(best[1])),
                int(layer.get("blend") or 0)))
        if overlays:
            entry["clip"] = compose_layers(entry["clip"], overlays, rest)
            applied += 1
    if applied:
        print("[anim] 已叠加副 Animator 层：%d 条动画" % applied)


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
    ap.add_argument("--simplify", type=float, default=0.0,
                    help="线性关键帧抽稀误差（输出单位；0=关闭）")
    ap.add_argument("--no-skel", action="store_true",
                    help="只写调试 JSON，不生成标准 Spine 3.8 .skel")
    ap.add_argument("--no-slot-anims", action="store_true",
                    help="不导出 slot attachment 显隐时间轴（排障用）")
    ap.add_argument("--deform-residual", type=float, default=0.0,
                    help="为 2D 骨无法精确表达的部件追加逐顶点 deform "
                         "校正（世界单位；0=关闭）")
    ap.add_argument("--secondary-phase", type=float, default=0.0,
                    help="副 Animator 在动作起点已播放的秒数（playqueue "
                         "常见预跑为 2.0）")
    ap.add_argument("--deduped-default", action="store_true",
                    help="被去重 Animator 播放自身默认动作，而不是跟随主动作")
    ap.add_argument("--keep-degenerate-shared-skins", action="store_true",
                    help="保留骨表短于共享网格 bindpose 且权重越界的坏重复件"
                         "（默认剔除；目前仅命中 Banshee parts_Hand_R_66）")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    mdl, parts = load_character(a.prefab, a.assets, a.scene)
    if not a.keep_degenerate_shared_skins:
        dropped = drop_candidates(a.prefab, a.assets)
        if dropped:
            before = len(parts)
            parts = [p for p in parts if p.name not in dropped]
            print("[skin] 剔除骨表越界的重复件：%s（%d → %d 件）"
                  % (", ".join(sorted(dropped)), before, len(parts)))
    # 与主转换器**同口径**过滤部件：主产物 `_static_info.json` 的 partsMeta 就是
    # "主转换器实际导出的那批"（已含 gizmo 屏蔽、始终禁用、m_Bones 全空引用等规则）。
    # 不做这一步，多骨骼会多导出 21 件（IK 控件 / hiddenBone / 常禁用的左手件）。
    parts_meta = {}
    if a.reuse_from:
        _ip = os.path.join(a.reuse_from, "_static_info.json")
        if os.path.isfile(_ip):
            parts_meta = {
                p["name"]: p for p in
                (json.load(open(_ip, encoding="utf-8")).get("partsMeta") or [])
                if p.get("name")
            }
            keep = set(parts_meta)
            if keep:
                before = len(parts)
                parts = [p for p in parts if p.name in keep]
                print("[parts] 按主产物过滤：%d → %d 件（与主转换器同口径）"
                      % (before, len(parts)))
    # **槽位顺序 = 绘制顺序**：必须和主转换器一致（`(sortingOrder, 同值内 -DFS序)`），
    # 否则头发/身体/表情会盖错（本轮实测：不排序时头发盖住整张脸和身体）。
    _rank = hierarchy_ranks(mdl)
    parts = sorted(parts, key=lambda p: (
        int(getattr(p, "sorting_order", 0) or 0),
        -_rank.get(getattr(p, "tfid", None), 1 << 30)))
    # **region/页名**：多页图集时每件属于不同页（`tex0`/`tex1`/…）。
    # 主产物若带 JSON（`--json` 导出），按 slot 名抄它的 `path`；否则退回 `tex0`。
    page_of = {}
    if a.reuse_from and os.path.isdir(a.reuse_from):
        for f in os.listdir(a.reuse_from):
            if not f.endswith("_static.json"):
                continue
            try:
                rj = json.load(open(os.path.join(a.reuse_from, f), encoding="utf-8"))
                for slot, mp in (rj.get("skins") or [{}])[0].get("attachments", {}).items():
                    for at in mp.values():
                        pth = at.get("path")
                        if pth:
                            page_of[slot] = pth
                            break
            except Exception:                    # noqa: BLE001
                pass
            break
    print("[atlas] 页映射：%d 件" % len(page_of))
    base = os.path.splitext(os.path.basename(a.prefab))[0]
    entries = enumerate_clips(mdl, a.assets)
    _compose_overlay_layers(mdl, a.assets, entries)
    want = [x for x in (a.anims or "").split(",") if x]
    if want:
        entries = [e for e in entries if e["state"] in want]
    exportable_parts = [
        p for p in parts
        if ((p.mesh or p.kind == "sprite")
            and not (p.kind == "sprite" and not p.sprite))
    ]
    if not exportable_parts:
        raise SystemExit(
            "[parts] 没有可导出的部件；检查 --reuse-from 是否来自同一 prefab")
    samplers = make_samplers(mdl, entries)
    print("角色 %s：部件 %d，动画 %d 条（%s）"
          % (base, len(parts), len(entries), ",".join(e["state"] for e in entries)))

    # setup 姿态与主转换器**同口径**：优先 lobby（排除 start/tep/breast），
    # 否则第一条。用 entries[0]（Start 首帧）会在"Start 带缩放/位移铺垫"的角色上
    # 让 setup 与主产物不一致（实测 ConstantiaS2_NS0 因此整体缩到 ~0.55 倍）。
    # 主产物的 setupClip 是**逐角色**的（banshee/alice=Start、C0/BL=lobby、
    # babariana=Lobby）；以它为准，保证 setup 姿态与主产物一致。
    _setup_name = None
    if a.reuse_from:
        _ip2 = os.path.join(a.reuse_from, "_static_info.json")
        if os.path.isfile(_ip2):
            try:
                _setup_name = json.load(open(_ip2, encoding="utf-8")).get("setupClip")
            except Exception:                    # noqa: BLE001
                _setup_name = None

    def _setup_entry(es):
        if _setup_name:
            for e in es:
                if (e.get("state") or "") == _setup_name:
                    return e
        for e in es:
            s = (e.get("state") or "").lower()
            if "lobby" in s and "start" not in s and "tep" not in s and "breast" not in s:
                return e
        for e in es:
            if "start" not in (e.get("state") or "").lower():
                return e
        return es[0]

    # setup 姿态的世界矩阵（下面判"平面性"用）
    e0 = _setup_entry(entries)
    assign_all = assignments_for_entry(
        mdl, samplers, entries, e0, deduped_default=a.deduped_default)
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
        # 这是"能否用 2D TRS 表示 3D 骨骼运动"的筛选。略离面但投影非退化
        # 的骨不能简单丢弃；它们由下面的 `--deform-residual` 做逐顶点校正。
        return (abs(v[2]) < 1e-4 and abs(v[6]) < 1e-4
                and abs(v[8]) < 1e-4 and abs(v[9]) < 1e-4)

    # ---- 需要哪些骨：被部件用到过的 transform + 其祖先（**只收平面内的**）----
    need = set()

    def add_chain(tfid):
        if not tfid:                       # Unity 的 m_Bones 里有 0 占位（"无骨"）
            return
        cur, hops = tfid, 0
        while cur is not None and cur != 0 and hops < 300:
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
    def nearest_kept_parent(tfid):
        """Nearest ancestor that survives the planar-bone filter."""
        cur = (mdl.transforms.get(tfid) or {}).get("father")
        hops = 0
        while cur is not None and cur != 0 and hops < 300:
            if cur in need:
                return cur
            cur = (mdl.transforms.get(cur) or {}).get("father")
            hops += 1
        return None

    # **父必须先于子**（Spine 解析时按名字找父，父不存在会直接崩）
    order = []
    seen = set()
    active = set()

    def walk(tfid):
        if (not tfid or tfid in seen or tfid in active
                or tfid not in need or tfid not in mdl.transforms):
            return
        active.add(tfid)
        fa = nearest_kept_parent(tfid)
        if fa:
            walk(fa)
        seen.add(tfid)
        order.append(tfid)
        active.discard(tfid)

    for t in list(mdl.transforms):
        if t in need:
            walk(t)
    order = [t for t in order if t in mdl.transforms]      # 防御：别把 0/None 带进来
    # Spine 3.8 的二进制骨表只有一个 0 号根：后续每根骨都会写/读一个父下标。
    # 多根骨架如果把第二个根直接写进去，运行时会把它挂到 0 号根下，继承错误的
    # 平移/缩放（C0 实测：狼被放大到整张画布）。JSON 支持多根，但 .skel 不支持，
    # 因此统一加一个单位变换的合成根，保证两种格式语义一致。
    root_tfids = [
        t for t in order
        if (mdl.transforms.get(t) or {}).get("father") not in need
    ]
    add_multi_root = len(root_tfids) > 1
    bone_index_offset = 1 if add_multi_root else 0
    bone_idx_export = {
        tfid: i + bone_index_offset for i, tfid in enumerate(order)
    }
    if add_multi_root:
        print("[bones] %d 个独立根 → 合成根 __multi_root" % len(root_tfids))

    def bone_name(tfid):
        td = mdl.transforms.get(tfid) or {}
        nm = (td.get("name") or "").replace("/", "_").replace(" ", "_")
        return "%s_%d" % (nm or "node", tfid)

    # ---- setup 姿态（与主转换器一致的 lobby t=0）与逐帧局部分解 ----
    e0 = _setup_entry(entries)
    assign0 = assignments_for_entry(
        mdl, samplers, entries, e0, deduped_default=a.deduped_default)

    def local_of(tfid, t, assign=assign0):
        """该 transform 在时刻 t 的**局部**矩阵（副动画按其自身时长）。"""
        td = mdl.transforms[tfid]
        aa = assign.get(tfid)
        if aa is None:
            return trs_mat(td["pos"], td["quat"], td["scale"])
        dur = aa["duration"]
        tt = t + float(aa.get("time_offset", 0.0) or 0.0)
        tt = tt % dur if dur > 1e-6 else tt
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

    def kept_parent_of(tfid):
        """最近的"保留祖先"（中间被剔除的层会被烘进子骨的局部矩阵）。"""
        return nearest_kept_parent(tfid)

    def local_to_kept(tfid, t, assign=assign0):
        """tfid 相对**最近保留祖先**的局部矩阵（把中间被剔除层的变换乘进来）。"""
        M = local_of(tfid, t, assign)
        cur = (mdl.transforms.get(tfid) or {}).get("father")
        hops = 0
        while cur is not None and cur != 0 and cur not in need and hops < 300:
            M = _mat_mul(local_of(cur, t, assign), M)
            cur = (mdl.transforms.get(cur) or {}).get("father")
            hops += 1
        return M

    bones = []
    if add_multi_root:
        bones.append({"name": "__multi_root", "x": 0, "y": 0,
                      "rotation": 0, "scaleX": 1, "scaleY": 1})
    for tfid in order:
        td = mdl.transforms[tfid]
        lp = kept_parent_of(tfid)
        lx, ly, rot, sx, sy = mat_decompose(local_to_kept(tfid, 0.0))
        b = {"name": bone_name(tfid), "x": round((lx) * k, 4),
             "y": round((ly) * k, 4), "rotation": round(rot, 4),
             "scaleX": round(sx, 5), "scaleY": round(sy, 5)}
        if lp:
            b["parent"] = bone_name(lp)
            # 根骨才减原点（子骨的 x/y 是相对父的）
        else:
            b["x"] = round((lx - ox) * k, 4)
            b["y"] = round((ly - oy) * k, 4)
            if add_multi_root:
                b["parent"] = "__multi_root"
        bones.append(b)

    # ---- 部件 → slot / attachment ----
    slots, skin = [], {}
    part_of_slot = {}
    residual_layout = {}

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
        meta = parts_meta.get(nm) or {}
        slot = {"name": nm, "bone": bone_name(host), "attachment": nm,
                "color": _static_slot_color(meta)}
        if meta.get("blend") not in (None, "", "normal"):
            slot["blend"] = meta["blend"]
        slots.append(slot)
        uvs_flat = [round(c, 6) for uv in uvs for c in (uv if isinstance(uv, (list, tuple)) else (uv,))]
        att = {"type": "mesh", "uvs": uvs_flat,
               "triangles": list(tris), "width": 1, "height": 1}
        if p.kind in ("static", "sprite") or not (getattr(p, "bones", None) or []):
            # 无权：顶点在骨局部（把世界点乘回去）
            v = []
            local_xy = []
            for q in pts:
                lx, ly = _planar_inverse_point(world0[host], q)
                lx *= k
                ly *= k
                v += [round(lx, 4), round(ly, 4)]
                local_xy.append((lx, ly))
            att["vertices"] = v
            residual_layout[nm] = {
                "part": p, "weighted": False, "host": host,
                "vertices": local_xy, "dropped": False,
            }
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
            raw = p.mesh.get("boneIndexRaw") or []
            wts = p.mesh.get("weights") or []
            verts = []
            influence_layout = []
            dropped_influence = False
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
                            else:
                                dropped_influence = True
                elif bl2 is not None:
                    for bi in (bl2 if isinstance(bl2, (list, tuple)) else [bl2]):
                        if isinstance(bi, int) and 0 <= bi < len(raw_bones):
                            tf = raw_bones[bi]
                            if tf in bone_idx_export:
                                infl[tf] = 1.0
                            else:
                                dropped_influence = True
                            break
                if not infl:                    # 没权重/下标不可用 → 挂到宿主骨
                    infl = {host: 1.0}
                # ⚠️ **绝不能跳过顶点**：`worldVerticesLength` = `len(uvs)/2`，
                # 少写一组就会让 spine 越界读（症状：加载后塌成一团 / 内存暴涨）。
                # 所以每个顶点都必须写出至少一组 (骨, x, y, 权重)。
                tot = sum(abs(w) for w in infl.values()) or 1.0
                verts.append(len(infl))
                packed_layout = []
                for tf in sorted(infl, key=lambda z: bone_idx_export[z]):
                    lx, ly = _planar_inverse_point(world0[tf], q)
                    lx *= k
                    ly *= k
                    weight = infl[tf] / tot
                    verts += [bone_idx_export[tf],
                              round(lx, 4), round(ly, 4),
                              round(weight, 5)]
                    packed_layout.append((tf, lx, ly, weight))
                influence_layout.append(packed_layout)
            att["hull"] = len(pts)
            att["vertices"] = verts
            residual_layout[nm] = {
                "part": p, "weighted": True, "host": host,
                "vertices": influence_layout,
                "dropped": dropped_influence,
            }
        att["path"] = page_of.get(nm, "tex0")
        skin.setdefault(nm, {})[nm] = att
        part_of_slot[nm] = p

    # ---- 动画：每根骨逐帧写 translate/rotate/scale（可抽稀）----
    animations = {}
    for e in entries:
        assign = assignments_for_entry(
            mdl, samplers, entries, e, deduped_default=a.deduped_default,
            secondary_phase=a.secondary_phase)
        times = _animation_times_for(e)
        times = _add_visibility_transitions(mdl, e, parts, times)
        simplify_keys = [0, 0]

        anim = {}
        slot_anim = {}
        # Spine 的时间轴是**相对 setup 的增量**（2026-10-30 用双色 quad 实测：
        # translate 键写 0 时骨头不动、写 200 时被推远；rotate 同理）。
        # 旧实现写的是**绝对值** ⇒ 运行期再叠加一次 setup ⇒ 整只角色散成一团。
        # 这里：① 只写"真的变化"的通道；② 值一律减去该骨的 setup。
        setup_b = {b["name"]: b for b in bones}
        for tfid in order:
            bn = bone_name(tfid)
            sb = setup_b.get(bn) or {}
            tn, rn, sn = [], [], []
            for t in times:
                lx, ly, rot, sx, sy = mat_decompose(
                    local_to_kept(tfid, t, assign))
                if (mdl.transforms[tfid].get("father")) not in need:
                    lx, ly = lx - ox, ly - oy
                tx = lx * k - sb.get("x", 0)
                ty = ly * k - sb.get("y", 0)
                ta = rot - sb.get("rotation", 0)
                while ta > 180:
                    ta -= 360
                while ta < -180:
                    ta += 360
                # Spine 3.8 ScaleTimeline.Apply 是：
                #   bone.scaleX = key.x * bone.data.scaleX
                # 因此 JSON 键写倍率；translate/rotate 才是相对 setup 的增量。
                sbx = sb.get("scaleX", 1)
                sby = sb.get("scaleY", 1)
                tsx = sx / sbx if abs(sbx) > 1e-8 else 1.0
                tsy = sy / sby if abs(sby) > 1e-8 else 1.0
                if a.tolerance <= 0:
                    tn.append({"time": round(t, 4), "x": round(tx, 4),
                               "y": round(ty, 4)})
                    rn.append({"time": round(t, 4), "angle": round(ta, 4)})
                    sn.append({"time": round(t, 4), "x": round(tsx, 5),
                               "y": round(tsy, 5)})
                else:
                    if (not tn or abs(tn[-1]["x"] - tx) > a.tolerance
                            or abs(tn[-1]["y"] - ty) > a.tolerance):
                        tn.append({"time": round(t, 4), "x": round(tx, 4),
                                   "y": round(ty, 4)})
                    if not rn or abs(rn[-1]["angle"] - ta) > a.tolerance:
                        rn.append({"time": round(t, 4), "angle": round(ta, 4)})
                    if (not sn or abs(sn[-1]["x"] - tsx) > a.tolerance / 100.0
                            or abs(sn[-1]["y"] - tsy) > a.tolerance / 100.0):
                        sn.append({"time": round(t, 4), "x": round(tsx, 5),
                                   "y": round(tsy, 5)})
            ch = {}
            # 全是 0（= 从没离开 setup）的通道不写
            if tn and any(abs(v["x"]) > 1e-4 or abs(v["y"]) > 1e-4 for v in tn):
                ch["translate"] = tn
            if rn and any(abs(v["angle"]) > 1e-4 for v in rn):
                ch["rotate"] = rn
            if sn and any(abs(v["x"] - 1) > 1e-4 or abs(v["y"] - 1) > 1e-4
                          for v in sn):
                ch["scale"] = sn
            if ch and a.simplify > 0:
                raw_keys = sum(len(v) for v in ch.values())
                if "translate" in ch:
                    ch["translate"] = _simplify(
                        ch["translate"], ("x", "y"), a.simplify)
                if "rotate" in ch:
                    ch["rotate"] = _simplify(
                        ch["rotate"], ("angle",), a.simplify)
                if "scale" in ch:
                    ch["scale"] = _simplify(
                        ch["scale"], ("x", "y"), a.simplify / 100.0)
                simplify_keys[0] += raw_keys
                simplify_keys[1] += sum(len(v) for v in ch.values())
            if ch:
                anim[bn] = ch

        # 略离面的 Unity 蒙皮骨无法由 Spine 2D TRS 精确表达。对这些部件，
        # 在骨动画之上追加逐顶点 deform 残差；未离面/没有丢权重的部件不写。
        deform_anim = {}
        for nm, layout in residual_layout.items():
            if a.deform_residual <= 0:
                break
            if not layout.get("dropped"):
                continue
            part = layout["part"]
            weighted = layout["weighted"]
            local_vertices = layout["vertices"]
            frames = []
            overall_max = 0.0
            for tm in times:
                world_t = _sample_world_multi(mdl, assign, tm)
                exact = _part_points(part, world_t)
                if len(exact) != len(local_vertices):
                    continue
                offsets = []
                frame_max = 0.0
                for vi, point in enumerate(exact):
                    ex, ey = float(point[0]), float(point[1])
                    if weighted:
                        ax = ay = 0.0
                        for tf, lx, ly, weight in local_vertices[vi]:
                            px, py = _planar_apply(world_t[tf], lx / k, ly / k)
                            ax += px * weight
                            ay += py * weight
                        dx, dy = ex - ax, ey - ay
                        frame_max = max(frame_max, math.hypot(dx, dy))
                        for tf, _lx, _ly, _weight in local_vertices[vi]:
                            ldx, ldy = _planar_inverse_vector(
                                world_t[tf], dx * k, dy * k)
                            offsets.extend((ldx, ldy))
                    else:
                        lx, ly = local_vertices[vi]
                        ax, ay = _planar_apply(world_t[layout["host"]],
                                               lx / k, ly / k)
                        dx, dy = ex - ax, ey - ay
                        frame_max = max(frame_max, math.hypot(dx, dy))
                        ldx, ldy = _planar_inverse_vector(
                            world_t[layout["host"]], dx * k, dy * k)
                        offsets.extend((ldx, ldy))
                overall_max = max(overall_max, frame_max)
                frames.append({
                    # Keep six decimals: four-decimal rounding can collapse
                    # adjacent visibility/transition samples into one time.
                    "time": round(tm, 6),
                    "vertices": [round(value, 4) for value in offsets],
                })
            if overall_max > a.deform_residual and frames:
                raw_frames = len(frames)
                frames = _simplify_deform(
                    frames, max(a.simplify, a.deform_residual * k))
                deform_anim.setdefault(nm, {})[nm] = frames
                print("  deform残差 %-28s %d → %d 帧 / 最大 %.5f 世界单位"
                      % (nm, raw_frames, len(frames), overall_max))

        unset = object()
        for nm, part in part_of_slot.items():
            meta = parts_meta.get(nm) or {}
            if not a.no_slot_anims:
                attachment_frames = []
                previous = unset
                for tm in times:
                    attachment = nm if part_visible(
                        mdl, e.get("clip") or {}, tm, part.tfid) else None
                    if previous is unset or attachment != previous:
                        attachment_frames.append({
                            "time": round(tm, 6), "name": attachment})
                        previous = attachment
                if attachment_frames and (
                        len(attachment_frames) > 1
                        or attachment_frames[0]["name"] is None):
                    slot_anim.setdefault(nm, {})["attachment"] = attachment_frames
            td = mdl.transforms.get(part.tfid) or {}
            color_frames = color_timeline(
                part, e.get("clip") or {}, td.get("anim_path") or "",
                (e.get("clip") or {}).get("_prefix") or "",
                lambda value: round(float(value), 4),
                _static_slot_color(meta),
                bake_dark=bool(meta.get("multiplyBaked")))
            if color_frames:
                slot_anim.setdefault(nm, {})["color"] = color_frames
        ad = {"bones": anim}
        if slot_anim:
            ad["slots"] = slot_anim
        if deform_anim:
            ad["deform"] = {"default": deform_anim}
        animations[e["state"]] = ad
        if a.simplify > 0 and simplify_keys[0]:
            print("  抽稀 %-28s %d → %d 键（误差 %.4g）"
                  % (e["state"], simplify_keys[0], simplify_keys[1],
                     a.simplify))
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
    if not a.no_skel:
        skel_path = os.path.splitext(js)[0] + ".skel"
        write_skeleton_binary(skel, skel_path)
        print("写出 %s（%.2f MB）"
              % (skel_path, os.path.getsize(skel_path) / 1e6))
    if a.reuse_from:
        for f in os.listdir(a.reuse_from):
            if f.endswith((".atlas", ".png")):
                src = os.path.join(a.reuse_from, f)
                dst = os.path.join(a.out, f.replace(base + "_static", base + "_static")
                                   if False else f)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
        print("已复用贴图集：%s" % a.reuse_from)


if __name__ == "__main__":
    main()
