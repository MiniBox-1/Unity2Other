# -*- coding: utf-8 -*-
"""一个角色从 Unity prefab 到标准 Cubism 包的完整流水线。

    convert_character(prefab, assets_root, out_dir) ->
        {consistency, max_err, parts, segments, deformers, motions, ...}

流程：解析 prefab → 骨骼链 → （可选）按动作真值逐顶点分块 →
RotationDeformer + 参数 → 写包 → 动作 → Core 复验。
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
if str(U2S) not in sys.path:
    sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model)
from unity2spine.unity import unity_2dmodel as u2d  # noqa: E402
from unity2spine.unity import unity_anim2d as ua  # noqa: E402

from .anim_world import affine_world_at, make_sampler  # noqa: E402
from .attribute import attribute  # noqa: E402
from .motion3 import sample_clip, to_motion3, write_motion  # noqa: E402
from .rig import collect_bones, dominant_bone, safe_id  # noqa: E402
from .rigged_model import RigPart, build_rigged  # noqa: E402
from .static_model import verify, write_package  # noqa: E402


# --------------------------------------------------------------------------- #
# 资源定位
# --------------------------------------------------------------------------- #
def _guid_index(assets: Path) -> Dict[str, Path]:
    idx: Dict[str, Path] = {}
    for meta in assets.rglob("*.meta"):
        try:
            s = meta.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r"^guid: ([0-9a-f]+)", s, re.M)
        if m:
            idx.setdefault(m.group(1), meta.with_suffix(""))
    return idx


def controller_of(prefab: Path) -> str | None:
    t = prefab.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"m_Controller: \{fileID: 9100000, guid: ([0-9a-f]+)", t)
    return m.group(1) if m else None


def load_states(prefab: Path, guid_index: Dict[str, Path]):
    """返回 [(state_name, clip_path, clip_dict)]。"""
    guid = controller_of(prefab)
    if not guid or guid not in guid_index:
        return []
    try:
        states = u2d.parse_animator_controller(str(guid_index[guid]))
    except Exception:
        return []
    out = []
    for st in states:
        cp = guid_index.get(st["clipGuid"])
        if not cp or cp.suffix != ".anim":
            continue
        try:
            out.append((st.get("name") or cp.stem, cp, ua.parse_clip(str(cp))))
        except Exception:
            continue
    return out


# --------------------------------------------------------------------------- #
# 分块：按动作真值给每个顶点选骨
# --------------------------------------------------------------------------- #
def _uvs_unity(p, mesh) -> List[float]:
    """把 UV 统一成 Unity 约定（左下原点）。

    库里对 Sprite 自建四边形时已经把 V 翻成左上原点，而蒙皮网格给的是 Unity
    原生 UV —— 混在一起会让同一模型里一半部件贴图上下颠倒（表现为「碎掉」）。
    这里对非蒙皮部件再翻一次，统一回 Unity 约定。
    """
    raw = list(mesh.get("uvs") or [])
    flat = ([c for uv in raw for c in uv]
            if raw and isinstance(raw[0], (tuple, list)) else list(raw))
    # 保守修正：位置对、但当前朝向采样到全透明、翻过来却有内容的部件才翻
    # （RheinRitter 的 Mesh 部件就是这种；正常部件 raw 不透明比例高，不会动）。
    try:
        from .uv_orient import needs_flip
        if flat and needs_flip(flat, getattr(p, "texture_path", None)):
            for i in range(1, len(flat), 2):
                flat[i] = 1.0 - flat[i]
            return flat
    except Exception:
        pass

    if os.environ.get("U2L2D_NO_UVFIX") == "1":
        return flat
    flip_all = os.environ.get("U2L2D_UVFLIP_ALL") == "1"
    if flip_all and flat:
        for i in range(1, len(flat), 2):
            flat[i] = 1.0 - flat[i]
        return flat
    # 只有 Sprite 部件需要翻：库里自建四边形时用的是左上原点；
    # 蒙皮网格与 Mesh 部件本来就是 Unity 的左下原点，翻了反而会采样到透明
    # （RheinRitter 的 Tail/Gun 部件就是这样消失的）。
    if p.kind == "sprite" and flat:
        for i in range(1, len(flat), 2):
            flat[i] = 1.0 - flat[i]
    return flat


def segment_part(p, mdl, bones: Dict[int, object], world, world_at,
                 frames: List[float], texture: int = 0,
                 overlap_edges: bool = False) -> List[RigPart]:
    mesh = p.mesh or {}
    if not mesh.get("positions"):
        return []

    # 非蒙皮部件（Sprite / 静态网格）：整体挂到最近的骨，顶点用世界变换
    if p.kind != "skinned":
        verts = [(v[0], v[1]) for v in _skin_mesh(p, mesh, world)]
        uvs = _uvs_unity(p, mesh)
        tris = list(mesh.get("triangles") or [])
        if not verts or len(uvs) != 2 * len(verts) or not tris:
            return []
        bone = dominant_bone(p, bones, verts)
        bname = safe_id(bones[bone].name, 24) if bone in bones else "root"
        return [RigPart(name=f"{p.name}_{bname}", verts=verts, uvs=uvs,
                        indices=tris, bone=bone if bone is not None else -1,
                        sorting_order=p.sorting_order, order=p.order,
                        texture=texture)]

    rest_v = [(v[0], v[1]) for v in _skin_mesh(p, mesh, world)]
    uvs = _uvs_unity(p, mesh)
    tris = list(mesh.get("triangles") or [])
    if not rest_v or len(uvs) != 2 * len(rest_v) or not tris:
        return []

    cand = [b for b in (p.bones or []) if b in bones]
    if not cand:
        # 有些蒙皮部件没有 m_Bones 列表（例如 Eternity 的坐垫）：整块按几何最近骨处理，
        # 否则会整件丢失。
        bone = dominant_bone(p, bones, rest_v)
        bname = safe_id(bones[bone].name, 24) if bone in bones else "root"
        return [RigPart(name=f"{p.name}_{bname}", verts=rest_v, uvs=uvs,
                        indices=list(tris), bone=bone if bone is not None else -1,
                        sorting_order=p.sorting_order, order=p.order,
                        texture=texture)]

    getters = [world_at(t) for t in frames]
    truth = [[(v[0], v[1]) for v in _skin_mesh(p, mesh, {k: g(k) for k in mdl.transforms})]
             for g in getters]
    bone_worlds = [[g(b) for b in cand] for g in getters]
    bone_rest = [world[b] for b in cand]
    vb = attribute(rest_v, truth, bone_worlds, bone_rest, cand)

    # 刚性部件保护：>90% 顶点都投同一根骨时不分块，避免把道具/硬边切裂
    votes = Counter(vb)
    top_bone, top_n = votes.most_common(1)[0]
    if top_n >= 0.9 * len(vb):
        uv_flat = []
        for g in range(len(rest_v)):
            uv_flat += [uvs[g * 2], uvs[g * 2 + 1]]
        return [RigPart(
            name=f"{p.name}_{safe_id(bones[cand[top_bone]].name, 24)}",
            verts=rest_v, uvs=uv_flat, indices=list(tris),
            bone=cand[top_bone], sorting_order=p.sorting_order, order=p.order,
            texture=texture)]

    # 三角形分配：默认按多数顶点；overlap_edges=True 时把跨骨三角形复制到
    # 两侧（用重复绘制填掉硬切缝隙，代价是接缝处重叠一层）
    groups: Dict[int, List[int]] = {}
    for t in range(0, len(tris) - 2, 3):
        tri = [tris[t], tris[t + 1], tris[t + 2]]
        bones_of = {vb[v] for v in tri}
        if overlap_edges and len(bones_of) > 1:
            targets = bones_of
        else:
            votes_t = Counter(vb[v] for v in tri)
            targets = {max(votes_t.items(), key=lambda kv: kv[1])[0]}
        for b in targets:
            groups.setdefault(b, []).extend(tri)

    out: List[RigPart] = []
    for bi, tl in groups.items():
        if len(tl) < 3:
            continue
        used = sorted(set(tl))
        remap = {g: i for i, g in enumerate(used)}
        uv_flat = []
        for g in used:
            uv_flat += [uvs[g * 2], uvs[g * 2 + 1]]
        out.append(RigPart(
            name=f"{p.name}_{safe_id(bones[cand[bi]].name, 24)}",
            verts=[rest_v[g] for g in used],
            uvs=uv_flat,
            indices=[remap[g] for g in tl],
            bone=cand[bi], sorting_order=p.sorting_order, order=p.order,
            texture=texture))
    return out


def rigid_parts(parts, mdl, bones, world, tex_of=None) -> List[RigPart]:
    out = []
    for p in parts:
        mesh = p.mesh or {}
        # 所有类型都走 _skin_mesh：sprite/static 会套用渲染器的世界矩阵，
        # 直接拿 mesh 局部坐标会把部件丢在错误位置（PA00EL 那批就是这种）
        verts = [(v[0], v[1]) for v in _skin_mesh(p, mesh, world)]
        uvs = _uvs_unity(p, mesh)
        tris = list(mesh.get("triangles") or [])
        if not verts or not uvs or len(uvs) != 2 * len(verts) or not tris:
            continue
        out.append(RigPart(name=p.name, verts=verts, uvs=uvs, indices=tris,
                           bone=dominant_bone(p, bones, verts) or -1,
                           sorting_order=p.sorting_order, order=p.order,
                           texture=(tex_of or {}).get(str(p.texture_path), 0)))
    return out


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def convert_character(prefab: Path, assets_root: Path, out_dir: Path | None = None,
                      name: str | None = None, angle: float = 30.0,
                      guid_index: Dict[str, Path] | None = None,
                      segment: bool = True,
                      overlap_edges: bool = False) -> dict:
    prefab = Path(prefab)
    assets_root = Path(assets_root)
    name = name or prefab.stem.replace(".uAnim", "")
    out_dir = Path(out_dir) if out_dir else prefab.parents[3] / "Products" / name

    mdl, parts = build_character_model(str(prefab), str(assets_root))
    world = _world_matrices(mdl, {})
    world_aff = None
    rest_t0 = os.environ.get("U2L2D_REST_T0") == "1"

    bone_ids = {b for p in parts for b in (p.bones or []) if b}

    guid_index = guid_index if guid_index is not None else _guid_index(assets_root)
    states = load_states(prefab, guid_index)

    # 基准姿势 = 默认动画 t=0（全部来自 prefab + controller + clip，属源数据）。
    # 之前失败是因为 `anim_world.rest_dict` 漏了位置，采样出的骨骼全在原点；
    # 修好后实测与 Unity 同一时刻的逐部件包围盒完全一致（中心偏差 0.000）。
    # 说明：`rest_dict` 修好位置后，「默认动画 t=0」确实与 Unity 同一时刻的逐部件
    # 包围盒一致（center diff 0.000）；但把 t=0 当基准姿势重建后：
    # RheinRitter 无变化（0.554），Khan 反而 0.896→0.710，Alexandra/Brownie 不变。
    # 说明这些角色 prefab 存的姿势本就等于 t=0，故仍用 bind pose（见 docs E41）。
    if rest_t0 and states:
        try:
            clip0 = states[0][2]
            g0 = make_sampler(mdl, clip0)(0.0)
            world = {tfid: g0(tfid) for tfid in mdl.transforms}
            world_aff = affine_world_at(mdl, clip0, 0.0)
        except Exception as exc:
            print(f"  [t0] {name}: fallback bind ({type(exc).__name__})")

    bones = collect_bones(mdl, bone_ids, world=world_aff)

    # 贴图页：一个角色可能有多张（不同部件用不同图集）
    tex_paths: List[Path] = []
    tex_of: Dict[str, int] = {}
    for p in parts:
        tp = p.texture_path
        if tp and str(tp) not in tex_of:
            tex_of[str(tp)] = len(tex_paths)
            tex_paths.append(Path(tp))

    # ---- 只保留 Unity 实际会绘制的部件 ----
    # prefab 里存在大量「备用姿势」部件（隐藏骨骼、放下/抬起的手臂等），
    # 它们在 Unity 里 inactive / renderer 关闭，但照单全收会画成散落碎片。
    try:
        from .prefab_filter import disabled_transforms
        bad = set() if os.environ.get("U2L2D_KEEP_DISABLED") == "1" else disabled_transforms(prefab)
        if bad:
            kept = [p for p in parts if p.tfid not in bad]
            if kept:
                parts = kept
    except Exception:
        pass

    # ---- 跳过「控制组」下的可视化物体（IK 圆环等；Unity 运行时由脚本隐藏）----
    try:
        from .prefab_filter import control_transforms
        ctrl = control_transforms(prefab)
        if ctrl:
            before = len(parts)
            parts = [p for p in parts if p.tfid not in ctrl]
            if len(parts) != before:
                print(f"  [ctrl] {name}: skipped {before - len(parts)} control gizmo part(s)")
    except Exception:
        pass

    # ---- 跳过 moc3 v1 无法表达的特效件（粒子/叠加/正片叠底 shader）----
    # 只读 prefab 的材质 GUID + 项目里的 .mat + 内置 shader id 常量表，不依赖真值。
    # 特效件（粒子/叠加/正片叠底）在 moc3 v1 里只能二选一：
    # 跳过，或把发光烘焙成普通 alpha。实测烘焙对 WarWolf/Scathy 是灾难
    # （0.976 → 0.17/0.35），对 Aeda 无改善（0.749 → 0.746），因此仍选择跳过。
    # 实验开关：U2L2D_FX_BAKE=1 时改为「保留特效件 + 烘焙进贴图」，用于对比评估。
    fx_parts = []
    try:
        from .shader_kind import is_effect_part
        if os.environ.get("U2L2D_FX_BAKE") == "1":
            fx_parts = [p for p in parts if is_effect_part(p, assets_root)]
            if fx_parts:
                print(f"  [fx] {name}: {len(fx_parts)} effect part(s) -> bake")
        else:
            fx_before = len(parts)
            parts = [p for p in parts if not is_effect_part(p, assets_root)]
            if len(parts) != fx_before:
                print(f"  [fx] {name}: skipped {fx_before - len(parts)} effect part(s)")
    except Exception:
        pass

    # 说明（重要）：转换过程**不读取任何 Unity 真值产物**。
    # 之前用过的 `[drop]`/`[fx]`/`[uni]` 三步依赖 Products\_unity_ref 里按角色
    # dump 的材质/可见性数据，属于「用测试集参与转换」，已全部移除；
    # Unity 截图与包围盒只作为 tests 用的评估集（tools\unity_iou_audit.py 等）。

    # ---- 分块 ----
    rig_parts: List[RigPart] = []
    if segment and states:
        clip = states[0][2]
        dur = float(clip.get("duration") or 0.0)
        frames = [dur * i / 3.0 for i in range(4)] if dur > 0 else [0.0]
        world_at = make_sampler(mdl, clip)
        for p in parts:
            rig_parts.extend(segment_part(p, mdl, bones, world, world_at, frames,
                                          tex_of.get(str(p.texture_path), 0),
                                          overlap_edges=overlap_edges))
    if not rig_parts:
        rig_parts = rigid_parts(parts, mdl, bones, world, tex_of)
    if not rig_parts:
        raise ValueError(f"{name}: no convertible parts")

    # 丢弃「远离主体的碎片」：极少数顶点被错误骨骼甩到很远，会把画布撑大、
    # 让角色在画布里变成一个小点（Emily 那类）。用稳健包围盒判定。
    rig_parts, dropped = _drop_stray(rig_parts)
    if dropped:
        print(f"  [stray] {name}: dropped {len(dropped)} part(s) far from body")

    rig_parts.sort(key=lambda s: (s.sorting_order, s.order))
    # 画布包围盒：全体部件参与，但剔除「又小又远」的孤立碎片
    # （错误权重常把几个顶点甩到很远，会把画布撑大、角色缩成小点）
    bounds = _canvas_bounds(rig_parts)
    # 调试开关：U2L2D_NOBONES=1 时不做骨骼变形器（全部挂根），用于排查「骨骼缩放
    # 被重复应用」这类问题（见 RheinRitter，骨骼统一 0.119 缩放）。
    use_bones = bones
    if os.environ.get("U2L2D_NOBONES") == "1":
        use_bones = {}

    result = build_rigged(rig_parts, mdl, bones=use_bones, ppu=1000.0, margin=0.05,
                          angle_range=(-angle, angle), bounds=bounds)
    write_package(result, name, out_dir, textures=tex_paths)

    if fx_parts and os.environ.get("U2L2D_FX_BAKE") == "1":
        try:
            from .texture_bake import BakeRect, bake_pages
            rects = []
            for p in fx_parts:
                uvs = (p.mesh or {}).get("uvs") or []
                flat = ([c for uv in uvs for c in (uv if isinstance(uv, (tuple, list)) else (uv,))]
                        if uvs else [])
                page = tex_of.get(str(p.texture_path))
                if len(flat) < 4 or page is None:
                    continue
                rects.append(BakeRect(page=page,
                                      u0=min(flat[0::2]), u1=max(flat[0::2]),
                                      v0=min(flat[1::2]), v1=max(flat[1::2])))
            if rects:
                pages = [out_dir / "textures" / f"texture_{i:02d}.png"
                         for i in range(len(tex_paths))]
                n = bake_pages(pages, rects)
                print(f"  [fx-bake] {name}: baked {n} rect(s)")
        except Exception as exc:
            print(f"  [fx-bake] {name}: skipped ({type(exc).__name__}: {exc})")

    report = verify(result, name)
    report.update({"source": str(prefab), "segments": len(rig_parts),
                   "source_parts": len(parts), "deformers": len(bones),
                   "angle_range": angle, "segmented": bool(segment and states)})

    # ---- 动作 ----
    motions = {}
    for sname, clip_path, clip in states:
        curves = sample_clip(clip, bones, mdl.transforms)
        if not curves:
            continue
        mname = safe_id((sname or "").strip() or clip_path.stem, 40)
        motion = to_motion3(curves, float(clip.get("duration") or 0.0),
                            fps=30.0, loop=mname != "Start",
                            fade_in=0.3, fade_out=0.3)
        p = write_motion(motion, out_dir / "motions" / f"{mname}.motion3.json")
        motions[mname] = {"file": p.name, "duration": motion["Meta"]["Duration"],
                          "curves": len(curves)}

    mp = out_dir / f"{name}.model3.json"
    model3 = json.loads(mp.read_text(encoding="utf-8"))
    model3["FileReferences"]["Motions"] = {
        n: [{"File": f"motions/{m['file']}"}] for n, m in motions.items()
    }

    mp.write_text(json.dumps(model3, ensure_ascii=False, indent=2), encoding="utf-8")
    report["motions"] = motions

    # ---- 独立校验 ----
    from ..moc3 import CubismCore

    core = CubismCore()
    model = core.load((out_dir / f"{name}.moc3").read_bytes())
    if model is not None:
        known = set(model.parameter_ids())
        unknown = 0
        for n, m in motions.items():
            mot = json.loads((out_dir / "motions" / m["file"]).read_text(encoding="utf-8"))
            unknown += sum(1 for c in mot["Curves"] if c["Id"] not in known)
        report["unknown_motion_ids"] = unknown
        report["params"] = len(known)

        # cdi3：参数/部件的可读名（Live2DViewerEX 等会显示）
        cdi = _build_cdi(model, bones)
        if cdi:
            (out_dir / f"{name}.cdi3.json").write_text(
                json.dumps(cdi, ensure_ascii=False, indent=2), encoding="utf-8")
            model3["FileReferences"]["DisplayInfo"] = f"{name}.cdi3.json"
            mp.write_text(json.dumps(model3, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        report["cdi3"] = bool(cdi)
    else:
        report["unknown_motion_ids"] = None

    (out_dir / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _canvas_bounds(rig_parts: List[RigPart]):
    """画布包围盒 = 所有部件的并集。

    之前用「中位点 + MAD 半径」排除远端碎片，但会把正常部件也切掉
    （Atalanta 的下半身就被裁出画布外）。真正的碎片已在 `_drop_stray`
    丢掉，这里直接取并集，保证「画布里能看到整个角色」。
    """
    xs = [v[0] for p in rig_parts for v in p.verts]
    ys = [v[1] for p in rig_parts for v in p.verts]
    if not xs:
        return (0.0, 1.0, 0.0, 1.0)
    return (min(xs), max(xs), min(ys), max(ys))


def _drop_stray(rig_parts: List[RigPart], pad: float = 0.5):
    """剔除整体落在稳健包围盒之外的部件（典型的错误权重碎片）。"""
    import numpy as np

    xs = [v[0] for p in rig_parts for v in p.verts]
    ys = [v[1] for p in rig_parts for v in p.verts]
    if len(xs) < 10:
        return rig_parts, []
    x = np.array(xs)
    y = np.array(ys)
    lo_x, hi_x = np.percentile(x, 0.5), np.percentile(x, 99.5)
    lo_y, hi_y = np.percentile(y, 0.5), np.percentile(y, 99.5)
    w = max(1e-6, hi_x - lo_x)
    h = max(1e-6, hi_y - lo_y)
    lo_x -= pad * w; hi_x += pad * w
    lo_y -= pad * h; hi_y += pad * h

    keep, dropped = [], []
    for p in rig_parts:
        inside = any(lo_x <= v[0] <= hi_x and lo_y <= v[1] <= hi_y for v in p.verts)
        (keep if inside else dropped).append(p)
    return keep, dropped


def _build_cdi(model, bones) -> dict:
    """cdi3.json：参数/部件的可读名（id 直接取自真实模型）。"""
    from .rig import param_id

    by_id = {param_id(b): b.name for b in bones.values() if b is not None}
    params = []
    for pid in model.parameter_ids():
        name = by_id.get(pid) or pid
        params.append({"Id": pid, "GroupId": "", "Name": name})
    parts = []
    for part_id in model.part_ids():
        # Part_03_parts_Body_04_01 -> parts_Body_04_01
        label = re.sub(r"^Part_\d+_", "", part_id)
        parts.append({"Id": part_id, "Name": label})
    return {"Version": 3, "Parameters": params, "ParameterGroups": [], "Parts": parts}
