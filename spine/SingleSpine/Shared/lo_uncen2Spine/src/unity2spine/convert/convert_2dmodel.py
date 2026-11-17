# -*- coding: utf-8 -*-
"""NormalLocal Sprite+Mesh(2DModel) -> Spine 3.8

思路：离线逐帧求骨骼世界矩阵，把 SkinnedMeshRenderer/MeshRenderer
每帧的最终顶点烘焙成 Root 下的 Spine mesh + deform 时间线（不用
Spine 骨骼），保证与 Unity 每帧蒙皮结果一致。
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


import json
import math
import os
import shutil

from ..spine.spine_out import fnum
from ..unity.unity_2dmodel import (TwoDModel, find_asset_by_guid, parse_animator_controller)
from ..unity.unity_anim2d import AnimSampler, euler_to_quat, trs_mat, parse_clip
from ..unity.unity_mesh import (mat4_mul, mat4_vec, parse_mesh, parse_sprite,
                         sprite_mesh_from_sprite)


#: sprite 轮廓的归一化简化容差（逆向 + 拟合的结论；见 sprite_outline.py）。
#: 与 Unity 的 Sprite.vertices 对拍：tol=0.05~0.1 时顶点数逐 sprite 一致（±1）。
OUTLINE_TOL = 0.07
#: 贴图 alpha 掩码按 (贴图, rect) 缓存，避免同一张图重复解码。
_OUTLINE_CACHE = {}


def _mat4_point(m, v):
    x, y, z = v
    return (m[0] * x + m[1] * y + m[2] * z + m[3],
            m[4] * x + m[5] * y + m[6] * z + m[7],
            m[8] * x + m[9] * y + m[10] * z + m[11])


def _load_clip_texture(material_path):
    """从 .mat 取 _MainTex 的 texture guid。"""
    try:
        s = open(material_path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    import re
    m = re.search(r"_MainTex:[\s\S]*?m_Texture: \{fileID: \d+, guid: ([0-9a-f]+)",
                  s)
    return m.group(1) if m else None


class Part:
    def __init__(self):
        self.name = ""
        self.kind = None
        self.bones = []
        self.root_bone = None
        self.aabb = None          # SMR 的 m_AABB（center, extent）
        self.mesh = None
        self.texture_path = None
        self.rest_local = None
        self.tf_world = None
        self.setup_verts = None
        self.uvs = []
        self.tris = []
        self.sprite = None
        self.sorting_order = 0
        self.color = {}
        #: sprite 部件的网格来源："asset"（精灵资产里 Unity 生成的网格）/
        #: "outline"（按 alpha 复刻）/ "quad"（四边形兜底）；skinned 部件为 None
        self.mesh_source = None


def _asset_path(assets, guid):
    if not guid:
        return None
    return find_asset_by_guid(assets, guid)


def sprite_part_mesh(sp, tex_path, flip_x=False, flip_y=False, cache=None):
    """sprite 部件的局部网格（pivot 在原点、单位 = 世界单位）。

    优先级：

    1. **Sprite 资产里 Unity 自己生成的网格**（`m_RD`，`sprite_mesh_from_sprite`）——
       Unity 导入精灵时就把"alpha → 轮廓 → 简化"的结果存进资产了，直接读最准
       （`banshee_skin1` 35/35、`alice_skin1_dl_idle` 111/111 与运行时逐位一致）；
    2. **按 alpha 复刻的 Tight 网格**（`sprite_outline.py`，复刻
       `SpriteUtility.GenerateSpriteOutline`）—— 资产里没有可读网格时用；
    3. 都没有 → 返回 `(None, None)`，调用方现拼四边形（最后的安全网）。

    返回 `(mesh|None, source)`，`source ∈ {"asset", "outline", None}`。
    """
    size = None
    try:
        from PIL import Image as _I
        size = _I.open(tex_path).size
    except Exception:
        size = None
    if size:
        m = sprite_mesh_from_sprite(sp, size, flip_x=flip_x, flip_y=flip_y)
        if m:
            return m, "asset"
    try:
        from ..spine.sprite_outline import build as _build_outline
        ok = _build_outline(
            tex_path, sp.get("rect"), sp.get("pivot") or [0.5, 0.5],
            float(sp.get("pixelsToUnits") or 100),
            extrude=int(sp.get("extrude") or 0),
            alpha_cutoff=0, tol=OUTLINE_TOL,
            flip_x=flip_x, flip_y=flip_y, cache=cache)
        if ok:
            return ok, "outline"
    except Exception:
        pass
    return None, None


def build_character_model(prefab, assets):
    mdl = TwoDModel()
    mdl.build(prefab, assets)
    parts = []
    go_order = {}
    for tfid, t in mdl.transforms.items():
        go_order.setdefault(t["go"], len(go_order))

    # 把材质 guid 解析到贴图 png；mesh 解析一次
    mesh_cache = {}
    for ri, r in enumerate(mdl.renderers):
        if r["kind"] == "sprite":
            sp_path = _asset_path(assets, r.get("spriteGuid"))
            if not sp_path or not os.path.isfile(sp_path):
                continue
            sp = parse_sprite(sp_path)
            tex = _asset_path(assets, sp.get("textureGuid"))
            if not tex or not os.path.isfile(tex):
                continue
            p = Part()
            p.name = "%s_%02d" % (mdl.gameobjects.get(r["go"], {}).get("name", "sprite"), ri)
            p.kind = "sprite"
            p.texture_path = tex
            p.sprite = sp
            p.color = dict(r.get("color") or {}) if r.get("color") else {}
            p.materials = list(r.get("materials") or [])
            p.flip_x = bool(r.get("flipX"))
            p.flip_y = bool(r.get("flipY"))
            p.mesh = None
            p.tfid = r.get("tfid")
            p.go = r["go"]
            p.order = go_order.get(r["go"], ri)
            p.sorting_order = int(r.get("sortingOrder") or 0)
            rect = sp["rect"]
            units = float(sp.get("pixelsToUnits") or 100)
            px = float((sp.get("pivot") or [0.5, 0.5])[0])
            py = float((sp.get("pivot") or [0.5, 0.5])[1])
            from PIL import Image as _I
            tw, th = _I.open(tex).size
            w = rect[2] / units
            h = rect[3] / units
            # SpriteRenderer 本地 XY 平面，逆时针 4 角
            l = -rect[2] * px / units
            b = -rect[3] * py / units
            rr = l + w
            tt = b + h
            u0, u1 = rect[0] / tw, (rect[0] + rect[2]) / tw
            v0, v1 = (th - (rect[1] + rect[3])) / th, (th - rect[1]) / th
            positions = [(l, b, 0), (rr, b, 0), (rr, tt, 0), (l, tt, 0)]
            uvs = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
            tris = [0, 1, 2, 0, 2, 3]
            # SpriteRenderer 的 m_FlipX / m_FlipY：Unity 是**把四边形绕 pivot 镜像**
            # （贴图跟着镜像），不是换 UV。之前只读了这两个字段却没应用，导致
            # "pivot 不在正中 + 细长"的精灵落到 pivot 的另一侧
            # （alice_skin2 的伞：幅度 0.877 对、符号反 —— 见 已知问题.md 1.5）。
            if p.flip_x:
                positions = [(-x, y, z) for x, y, z in positions]
            if p.flip_y:
                positions = [(x, -y, z) for x, y, z in positions]
            if p.flip_x != p.flip_y:
                # 只翻一个轴会反转绕序，跟着反一下，保证三角面朝向不变
                tris = [0, 2, 1, 0, 3, 2]
            p.mesh = {
                "positions": positions,
                "uvs": uvs,
                "triangles": tris,
                "bindposes": [], "weights": [], "boneIndexRaw": [],
            }
            # 默认走 Unity 的 Tight 网格（多边形），失败才用上面的四边形。
            # 优先级：Sprite 资产里的网格 → 按 alpha 复刻的轮廓 → 四边形。
            # 理由 + 依据见 convert_2dmodel.sprite_part_mesh 与 sprite_outline.py。
            p.outline = False
            p.mesh_source = "quad"
            _m, _src = sprite_part_mesh(sp, tex, p.flip_x, p.flip_y,
                                        cache=_OUTLINE_CACHE)
            if _m:
                p.mesh = _m
                p.outline = True
                p.mesh_source = _src
            parts.append(p)
            continue
        mesh_path = _asset_path(assets, r.get("meshGuid"))
        if not mesh_path or not os.path.isfile(mesh_path):
            continue
        mesh = mesh_cache.get(mesh_path)
        if mesh is None:
            mesh = parse_mesh(mesh_path)
            mesh_cache[mesh_path] = mesh
        tex = None
        mats = r.get("materials") or []
        if not mats:
            # 尝试 MeshRenderer 同一目录/同名的贴图
            d = os.path.dirname(mesh_path)
            for fn in os.listdir(os.path.join(d, "..", "Texture2D")):
                if fn.lower().endswith(".png"):
                    tex = os.path.join(d, "..", "Texture2D", fn)
                    break
        else:
            for mg in mats:
                mat_path = _asset_path(assets, mg)
                if mat_path and os.path.isfile(mat_path):
                    tg = _load_clip_texture(mat_path)
                    tex = _asset_path(assets, tg)
                    if tex:
                        break
        if tex and not os.path.isfile(tex):
            tex = None
        p = Part()
        gid = r["go"]
        nm = mdl.gameobjects.get(gid, {}).get("name", "")
        p.name = "%s_%02d" % (nm, ri) if nm else "part_%02d" % ri
        p.kind = r["kind"]
        # 多材质的 Mesh：按子网格拆成多个部件，各用自己的贴图（Unity 就是这么画的）。
        # 顶点/权重/骨骼沿用整份，只有 triangles 段不同；贴图按子网格顺序取材质。
        subs = mesh.get("submeshes") or []
        if len(subs) > 1 and len(mats) > 1:
            for si, (start, count) in enumerate(subs):
                mtex = None
                mp = _asset_path(assets, mats[min(si, len(mats) - 1)])
                if mp and os.path.isfile(mp):
                    mtex = _asset_path(assets, _load_clip_texture(mp))
                if mtex and not os.path.isfile(mtex):
                    mtex = None
                sp2 = Part()
                sp2.name = "%s_s%d_%02d" % (nm or "part", si, ri)
                sp2.kind = r["kind"]
                sp2.mesh = dict(mesh)
                sp2.mesh["triangles"] = list(
                    mesh.get("triangles", [])[start:start + count])
                sp2.bones = list(r.get("bones") or [])
                sp2.mesh_path = mesh_path
                sp2.root_bone = r.get("rootBone") or None
                sp2.aabb = r.get("aabb")
                sp2.texture_path = mtex or tex
                sp2.materials = [mats[min(si, len(mats) - 1)]]
                sp2.flip_x = bool(r.get("flipX"))
                sp2.flip_y = bool(r.get("flipY"))
                sp2.tfid = r.get("tfid")
                sp2.go = gid
                sp2.order = go_order.get(gid, ri)
                sp2.sorting_order = int(r.get("sortingOrder") or 0)
                parts.append(sp2)
            continue
        p.mesh = mesh
        p.mesh_path = mesh_path
        # 注意：m_Bones 里可能有 null 占位（如黑莉莉丝头发第 5 个骨骼为空），
        # 必须按原样保留长度与顺序，否则索引会整体错位、蒙皮错位。
        p.bones = list(r.get("bones") or [])
        p.root_bone = r.get("rootBone")
        # fileID 0 表示"没有 rootBone"，不能当成节点 ID 0 去查（会取到别的
        # 节点矩阵，把无骨骼部件缩放错——eternity 的 Part_BallonBed 差 3 倍）
        if not p.root_bone:
            p.root_bone = None
        p.aabb = r.get("aabb")
        p.texture_path = tex
        p.materials = mats
        p.flip_x = bool(r.get("flipX"))
        p.flip_y = bool(r.get("flipY"))
        p.tfid = r.get("tfid")
        p.go = gid
        p.order = go_order.get(gid, ri)
        p.sorting_order = int(r.get("sortingOrder") or 0)
        parts.append(p)
    # ---- 同一网格被多个 SkinnedMeshRenderer 共用、骨骼表长度不一致 ----
    # 例（banshee 手，2026-09-18 定案）：父件 m_Bones 3 根、子件 4 根，而网格有
    # 4 个 bindpose。用 Unity 自己的 `PoseFrames`（`positions` = **蒙皮后的局部
    # 顶点**，`localToWorld` 一转就是世界坐标）当真的话，两个件**形状一模一样**
    # （世界张成都是 0.219 x 0.085）⇒ Unity 用的是"该网格的完整骨骼表"（蒙皮数据
    # 按网格缓存）。我们按 `m_Bones` 位置配对会把权重索引对到错的骨骼：父件被撑成
    # 0.324 x 0.264、盖住手心，边缘就是用户看到的"硬黑线 + 多一块"。
    # 规则：同一份网格里，若某个渲染器的骨骼数 == 网格的 bindpose 数，就用它那份
    # 骨骼表（长的赢）；长度本来就一致的部件不受影响。
    by_mesh = {}
    for p in parts:
        if p.kind == "skinned" and getattr(p, "mesh_path", None):
            by_mesh.setdefault(p.mesh_path, []).append(p)
    shared = []
    for mp, ps in by_mesh.items():
        nb = len(((ps[0].mesh or {}).get("bindposes")) or [])
        if nb <= 0:
            continue
        best = max(ps, key=lambda q: len(q.bones or []))
        if len(best.bones or []) != nb:
            continue                       # 没有"完整骨骼表"可用，保持原样
        for q in ps:
            if q is best or len(q.bones or []) == nb:
                continue
            q.bones = list(best.bones)
            shared.append((q.name, best.name))
    if shared:
        print("[skin] 同一网格的骨骼表按最长的共享 %d 个部件：%s"
              % (len(shared), ", ".join("%s<-%s" % t for t in shared[:6])))
    return mdl, parts


def _world_matrices(mdl, local_values):
    """local_values: tfid -> trs mat；返回 world。"""
    world = {}

    def get(tfid):
        if tfid in world:
            return world[tfid]
        t = mdl.transforms[tfid]
        local = local_values.get(tfid)
        if local is None:
            q = t["quat"]
            local = trs_mat(t["pos"], (q[0], q[1], q[2], q[3]), t["scale"])
        m = local
        f = t["father"]
        if f in mdl.transforms:
            m = mat4_mul(get(f), local)
        world[tfid] = m
        return m

    for tfid in mdl.transforms:
        get(tfid)
    return world


def _skin_mesh(part, mesh, world, root_inv=None):
    """按 Unity 蒙皮/静态规则计算顶点（3D 世界坐标）。"""

    def fit_to_smr_aabb(vertices):
        """无骨骼 SMR：用 SMR 的 m_AABB 与 mesh 的 m_LocalAABB 的比值校正顶点。

        Unity 里 m_Bones 为空的部件，渲染范围以 SMR 自己的包围盒为准，
        而 mesh 顶点可能烘在另一个尺度下（eternity 的 Part_BallonBed 差 20 倍）。
        """
        ma = (mesh or {}).get("aabb")
        sa = getattr(part, "aabb", None)
        if not ma or not sa:
            return vertices
        mc, me = ma
        sc, se = sa
        scale = []
        for i in range(3):
            if abs(me[i]) > 1e-6 and abs(se[i]) > 1e-9:
                scale.append(se[i] / me[i])
            else:
                scale.append(1.0)
        if all(abs(s - 1.0) < 0.02 for s in scale):
            return vertices
        return [((v[0] - mc[0]) * scale[0] + sc[0],
                 (v[1] - mc[1]) * scale[1] + sc[1],
                 (v[2] - mc[2]) * scale[2] + sc[2]) for v in vertices]

    out = []
    if part.kind in ("static", "sprite"):
        m = world.get(part.tfid)
        if m is None:
            return out
        for v in mesh["positions"]:
            out.append(mat4_vec(m, (v[0], v[1], v[2])))
    else:
        bind = mesh["bindposes"]
        # m_Bones 为空的 SMR：顶点可能烘在另一个尺度下（eternity 的
        # Part_BallonBed 差 20 倍），先按 SMR 包围盒统一校正一次。
        pos_list = mesh["positions"]
        if not getattr(part, "bones", None):
            pos_list = fit_to_smr_aabb(pos_list)
        for vi, v in enumerate(pos_list):
            px, py, pz = 0.0, 0.0, 0.0
            wsum = 0.0
            used_bones = 0
            wlist = None
            if vi < len(mesh["weights"]):
                wlist = mesh["weights"][vi]
            blist = mesh.get("boneIndexRaw") or []
            bi = blist[vi] if vi < len(blist) else (0, 0, 0, 0)
            if not wlist:
                # 只有骨骼索引、没有权重通道的小网格（如 audrey 的
                # parts_Flush_020：m_Channels[12].dimension=0）：Unity 会
                # 隐含"第一个索引权重 1.0"，不能退化成用渲染器自身矩阵，
                # 否则整块会有一个固定偏移。
                if blist and part.bones:
                    wlist = (1.0, 0.0, 0.0, 0.0)
                else:
                    # m_Bones 为空的 SkinnedMeshRenderer：Unity 用 rootBone
                    # 的变换（没有 rootBone 才退回渲染器自身矩阵）。用错会
                    # 让部件被整体缩放/错位——例如 eternity 的
                    # Part_BallonBed（rootBone 带 0.05 缩放，差了 10 倍）。
                    tf = part.tfid
                    rb = getattr(part, "root_bone", None)
                    if rb is not None and rb in world:
                        tf = rb
                    m = world.get(tf)
                    if m:
                        out.append(mat4_vec(m, (v[0], v[1], v[2])))
                    continue
            for k in range(4):
                w = float(wlist[k]) if k < len(wlist) else 0.0
                if abs(w) < 1e-6:
                    continue
                wsum += w
                try:
                    idx = int(round(float(bi[k]))) if k < len(bi) else 0
                except (TypeError, ValueError):
                    idx = 0
                if idx >= len(part.bones) or idx >= len(bind):
                    continue
                bw = world.get(part.bones[idx])
                if bw is None:
                    continue
                used_bones += 1
                local = mat4_vec(bind[idx], (v[0], v[1], v[2]))
                pt = mat4_vec(bw, local)
                px += pt[0] * w
                py += pt[1] * w
                pz += pt[2] * w
            if used_bones == 0:
                # 没有任何有效骨骼：权重数据不可信（例如 (-1,0,0,-1) 这种
                # 非法值），整个顶点交给渲染器自身的变换——否则
                # rem = 1-wsum 会变成 3，部件被放大（eternity 的
                # Part_BallonBed 就是这么大了 3 倍）。
                mg = world.get(part.tfid)
                if mg is not None:
                    pt = mat4_vec(mg, (v[0], v[1], v[2]))
                    px, py, pz = pt[0], pt[1], pt[2]
            elif wsum < 0.999:
                # 剩余权重由渲染器自身 Transform 承担（Unity SkinnedMesh 规则）
                mg = world.get(part.tfid)
                if mg is not None:
                    loc = mat4_vec(mg, (v[0], v[1], v[2]))
                    # 注意：负权重（(-1,0,0,-1) 这类）**不能**简单地当"无权重"
                    # 处理——用整角色参考图比对验证过：改成 rem=1 会让
                    # lindwurm 的轮廓 IoU 从 0.997 掉到 0.624。Unity 的
                    # 规则是"权重和不足 1 的部分由渲染器自身变换补齐"，
                    # 负权重也照此计算（此时 rem > 1，会抵消负权重的贡献）。
                    rem = 1.0 - wsum
                    px += loc[0] * rem
                    py += loc[1] * rem
                    pz += loc[2] * rem
            out.append((px, py, pz))
    return out


def _to_spine_xy(p, origin=None):
    """蒙皮结果在世界 XY 平面（z≈0），转到角色根坐标系；Y 取反对齐 Spine。"""
    ox = origin[0] if origin else 0.0
    oy = origin[1] if origin else 0.0
    return p[0] - ox, oy - p[1]


def _part_xy(part, pt, origin):
    """Sprite/静态件与蒙皮件在 Unity 里的 Y 方向相反，分别校正。"""
    ox, oy = origin
    if part.kind == "skinned":
        return pt[0] - ox, pt[1] - oy
    return pt[0] - ox, oy - pt[1]


def convert(prefab, assets, out_dir, dt=0.05, flip=False, truth_path=None,
            layout_path=None):
    mdl, parts = build_character_model(prefab, assets)
    from ..unity.unity_parse import load_unity_docs
    for c, fid, d in load_unity_docs(prefab):
        if c == 23 and "MeshRenderer" in d:
            mr = d["MeshRenderer"]
            gid = mdl.go_of_component.get(fid)
            mats = []
            for m0 in mr.get("m_Materials") or []:
                g = (m0 or {}).get("guid")
                if g:
                    mats.append(g)
            for p in parts:
                if p.kind == "static" and p.go == gid:
                    p.materials = mats
                    if p.texture_path is None and mats:
                        for mg in mats:
                            mat_path = _asset_path(assets, mg)
                            if mat_path and os.path.isfile(mat_path):
                                tg = _load_clip_texture(mat_path)
                                tex = _asset_path(assets, tg)
                                if tex and os.path.isfile(tex):
                                    p.texture_path = tex
                                    break
    base = os.path.splitext(os.path.basename(prefab))[0]
    if not parts:
        raise ValueError("没有找到 Mesh 部件: " + prefab)

    # 材质贴图收集为图集页
    page_texs = []
    for p in parts:
        if p.texture_path and p.texture_path not in page_texs:
            page_texs.append(p.texture_path)

    def png_size(path):
        from PIL import Image
        im = Image.open(path)
        return im.size

    tex_ids = {}
    tex_sizes = {}
    page_id_for_path = {}
    seen_hash = {}
    for tp in page_texs:
        with open(tp, "rb") as fp:
            digest = __import__("hashlib").md5(fp.read()).hexdigest()
        if digest in seen_hash:
            page_id_for_path[tp] = seen_hash[digest]
            continue
        i = len(tex_ids)
        tex_ids[tp] = i
        tex_sizes[tp] = png_size(tp)
        seen_hash[digest] = i
        page_id_for_path[tp] = i

    # 动画：从 AnimatorController 状态取 clip
    anims = []
    if mdl.animator_controller_guid:
        cp = _asset_path(assets, mdl.animator_controller_guid)
        if cp:
            for st in parse_animator_controller(cp):
                clip_path = _asset_path(assets, st["clipGuid"])
                if clip_path:
                    clip = parse_clip(clip_path)
                    # clip 里 `path_0x...` 的哈希路径要还原成真实节点路径，
                    # 否则这些曲线绑不到节点（见静态prefab路线 3.36）
                    try:
                        from .static_prefab_spine import (
                            resolve_clip_paths, _main_animator_go)
                        resolve_clip_paths(mdl, _main_animator_go(mdl), clip)
                    except Exception:
                        pass
                    anims.append((st["name"], clip))
    if not anims:
        raise ValueError("AnimatorController 里没有 clip: " + prefab)

    rest_local = {}
    rest_sampler = {}
    for tfid in mdl.transforms:
        t = mdl.transforms[tfid]
        q = t["quat"]
        rest_sampler[t["anim_path"]] = {
            "px": t["pos"][0], "py": t["pos"][1], "pz": t["pos"][2],
            "qx": q[0], "qy": q[1], "qz": q[2], "qw": q[3],
            "sx": t["scale"][0], "sy": t["scale"][1], "sz": t["scale"][2],
        }
        rest_local[tfid] = trs_mat(t["pos"], (q[0], q[1], q[2], q[3]),
                                   t["scale"])

    # 采样 setup（t=0）
    root_tf = mdl.roots[0] if mdl.roots else None
    world0 = _world_matrices(mdl, rest_local)
    root_origin = (0.0, 0.0)
    if root_tf and root_tf in world0:
        w = world0[root_tf]
        root_origin = (w[3], w[7])

    def setup_verts(part, mesh):
        pts = _skin_mesh(part, mesh, world0)
        return pts

    truth = None
    layout = None
    if truth_path:
        import json as _json
        truth = _json.load(open(truth_path, encoding="utf-8-sig"))
        truth_renderers = {r.get("path"): r for r in truth.get("renderers", [])}
        truth_transforms = {t.get("path"): t for t in truth.get("transforms", [])}
    else:
        truth_renderers = {}
        truth_transforms = {}
    if layout_path:
        import json as _json
        layout = _json.load(open(layout_path, encoding="utf-8-sig"))
    layout_renderers = {}
    if layout:
        for ch in layout.get("children", []):
            for rr in ch.get("renderers", []):
                bb = rr.get("bounds")
                if len(bb or []) == 4:
                    layout_renderers[rr.get("path")] = {
                        "type": rr.get("type"),
                        "bounds": [float(x) for x in bb],
                    }

    for p in parts:
        m = p.mesh
        p.setup = setup_verts(p, m)
        p.uvs = [list(u) for u in m.get("uvs", [])]
        p.tris = m.get("triangles", [])
        p.full_path = ""
        if p.tfid in mdl.transforms:
            p.full_path = mdl.transforms[p.tfid]["path"]

    if truth_path:
        for p in parts:
            p.truth_anchor = False
            p.affine = None
            r = truth_renderers.get(p.full_path)
            if r:
                l2w = r.get("localToWorld")
                l2w_flat = [v for row in (l2w or []) for v in row]
                local_pts = None
                if p.kind == "skinned":
                    baked = r.get("baked") or {}
                    local_pts = baked.get("positions")
                elif p.kind == "sprite":
                    corners = []
                    if r and r.get("worldCorners") and \
                            len(r["worldCorners"]) == len(p.setup):
                        corners = r["worldCorners"]
                    elif p.full_path in layout_renderers:
                        b = layout_renderers[p.full_path]["bounds"]
                        corners = [(b[0], b[1]), (b[2], b[1]),
                                   (b[2], b[3]), (b[0], b[3])]
                    if corners:
                        ox, oy = root_origin
                        p.spine_setup = [(c[0] - ox, c[1] - oy)
                                         for c in corners]
                        p.our_base = [(q[0] - ox, q[1] - oy)
                                      for q in p.setup]
                        p.truth_anchor = True
                        continue
                elif p.mesh is not None and l2w:
                    local_pts = [list(x) for x in p.mesh.get("positions", [])]
                if local_pts and l2w and len(local_pts) == len(p.setup):
                    ox, oy = root_origin
                    anchor = []
                    for lp in local_pts:
                        wp = mat4_vec(l2w_flat, (lp[0], lp[1], lp[2]))
                        anchor.append((wp[0] - ox, wp[1] - oy))
                    p.spine_setup = anchor
                    p.our_base = [(q[0] - ox, q[1] - oy) for q in p.setup]
                    p.truth_anchor = True
                    continue
            p.spine_setup = [_part_xy(p, q, root_origin) for q in p.setup]
            p.our_base = list(p.spine_setup)
        # 剔除离主骨架过远的残留/离屏 sprite（Render 会因全范围而把人压扁）
        centres = []
        for p in parts:
            if p.kind == "skinned" and getattr(p, "truth_anchor", False):
                for x, y in p.spine_setup:
                    centres.append((x, y))
        if centres:
            cx = sum(x for x, _ in centres) / len(centres)
            cy = sum(y for _, y in centres) / len(centres)
            scale = max(6.0, max(max(abs(x - cx), abs(y - cy))
                                 for x, y in centres))
            limit = scale * 3.0
            for p in parts:
                if p.kind == "sprite" and getattr(p, "truth_anchor", False):
                    far = any(abs(x - cx) > limit or abs(y - cy) > limit
                              for x, y in p.spine_setup)
                    if far:
                        p.skip = True

    # ---- 以完整立绘 Sprite(body) 为基准，对每个蒙皮部件做 UV 反投影仿射配准 ----
    try:
        import numpy as np
    except Exception:
        np = None
    body_p = None
    for p in parts:
        if p.kind == "sprite" and (p.name.startswith("body") or
                                   "body" in p.name.lower().split("_")):
            body_p = p
            break
    if truth_path is None and body_p is not None and np is not None and \
            len(body_p.setup) >= 3:
        corners = body_p.setup[:4]
        cuvs = body_p.uvs[:4]
        sp_c = [_part_xy(body_p, q, root_origin) for q in corners]
        (ux0, vx0), (ux1, vx1) = cuvs[0], cuvs[1]
        uy0 = cuvs[3][1]
        p0 = sp_c[0]

        def body_map(uv):
            uu, vv = uv
            du = sp_c[1][0] - p0[0], sp_c[1][1] - p0[1]
            dv = sp_c[3][0] - p0[0], sp_c[3][1] - p0[1]
            du_den = max(1e-9, ux1 - ux0)
            dv_den = max(1e-9, cuvs[3][1] - cuvs[0][1])
            return (p0[0] + (uu - ux0) / max(1e-9, ux1 - ux0) * du[0]
                    + (vv - uy0) / dv_den * dv[0],
                    p0[1] + (uu - ux0) / max(1e-9, ux1 - ux0) * du[1]
                    + (vv - uy0) / dv_den * dv[1])

        for p in parts:
            if p.kind != "skinned" or not p.uvs or len(p.setup) != len(p.uvs):
                p.spine_setup = [_part_xy(p, q, root_origin) for q in p.setup]
                p.affine = None
                continue
            src = []
            dst = []
            for pt, uv in zip(p.setup, p.uvs):
                sx, sy = _part_xy(p, pt, root_origin)
                tx, ty = body_map(uv)
                src.append([sx, sy, 1.0])
                dst.append([tx, ty])
            A, *_ = np.linalg.lstsq(np.array(src), np.array(dst), rcond=None)
            p.affine = A
            p.spine_setup = []
            for pt in p.setup:
                sx, sy = _part_xy(p, pt, root_origin)
                x, y = np.array([sx, sy, 1.0]) @ A
                p.spine_setup.append((float(x), float(y)))
    else:
        for p in parts:
            if not hasattr(p, "spine_setup"):
                p.spine_setup = [_part_xy(p, q, root_origin) for q in p.setup]
            p.affine = None

    # ---- 按每个部件实际 UV 区域裁切源贴图，重打包成少量大图 ----
    from ..ngui.pack_images import pack_items as _pack
    from PIL import Image as _Img
    crop_cache = {}
    pack_list = []
    raw_tex = {}
    for p in parts:
        if not p.texture_path or not p.uvs:
            p.region_id = "tex0"
            p.uvs2 = p.uvs
            continue
        tp = p.texture_path
        if tp not in raw_tex:
            raw_tex[tp] = _Img.open(tp).convert("RGBA")
        tw, th = raw_tex[tp].size
        us = [u[0] for u in p.uvs]
        vs = [u[1] for u in p.uvs]
        u0 = max(0.0, min(us)); u1 = min(1.0, max(us))
        v0 = max(0.0, min(vs)); v1 = min(1.0, max(vs))
        x0 = int(math.floor(u0 * tw)); x1 = max(x0 + 1, int(math.ceil(u1 * tw)))
        y0 = int(math.floor(v0 * th)); y1 = max(y0 + 1, int(math.ceil(v1 * th)))
        x1 = min(tw, x1); y1 = min(th, y1)
        key = (tp, x0, y0, x1, y1)
        if key not in crop_cache:
            rid = "r%04d" % len(pack_list)
            crop = raw_tex[tp].crop((x0, y0, x1, y1))
            crop_cache[key] = (rid, crop, x0, y0, x1 - x0, y1 - y0)
            pack_list.append((rid, crop, {
                "width": x1 - x0, "height": y1 - y0}))
        rid, crop, cx0, cy0, cw, ch = crop_cache[key]
        p.region_id = rid
        p.uvs2 = []
        for u, v in p.uvs:
            p.uvs2.append(((u * tw - cx0) / cw, (v * th - cy0) / ch))

    # ---- 通用选择规则：sprite 必须与蒙皮层共用角色贴图，否则视为特效/独立图 ----
    for p in parts:
        if p.kind == "static":
            p.skip = True
    skinned_tex = {p.texture_path for p in parts if p.kind == "skinned"}
    for p in parts:
        if p.kind == "sprite":
            low = p.name.lower()
            if ("glow" in low or "star" in low or "fx" in low or
                    p.texture_path not in skinned_tex):
                p.skip = True
    if not truth_path:
        centres = []
        for p in parts:
            if p.kind == "skinned" and hasattr(p, "spine_setup"):
                for x, y in p.spine_setup:
                    centres.append((x, y))
        if centres:
            cx = sum(x for x, _ in centres) / len(centres)
            cy = sum(y for _, y in centres) / len(centres)
            scale = max(6.0, max(max(abs(x - cx), abs(y - cy))
                                 for x, y in centres))
            limit = scale * 3.0
            for p in parts:
                if p.kind == "sprite" and not getattr(p, "skip", False) and \
                        hasattr(p, "spine_setup"):
                    far = any(abs(x - cx) > limit or abs(y - cy) > limit
                              for x, y in p.spine_setup)
                    if far:
                        p.skip = True

    skeleton = {
        "skeleton": {"hash": "ngui2spine-2dmodel-" + base,
                     "spine": "3.8.99", "x": 0, "y": 0,
                     "width": 0, "height": 0, "fps": 60},
        "bones": [{"name": "Root", "length": 0, "x": 0, "y": 0,
                   "rotation": 0, "scaleX": 1, "scaleY": 1}],
        "slots": [], "skins": [{"name": "default", "attachments": {}}],
        "animations": {},
    }
    used = set()

    def uniq(n):
        while n in used:
            n += "_x"
        used.add(n)
        return n

    attachments = skeleton["skins"][0]["attachments"]
    for i, p in enumerate(parts):
        if getattr(p, "skip", False):
            continue
        nm = uniq(p.name)
        region = getattr(p, "region_id", "tex0")
        sx = [0.0] * (len(p.setup) * 2)
        for k, pt in enumerate(p.spine_setup):
            sx[k * 2], sx[k * 2 + 1] = pt
            if flip:
                sx[k * 2] = -sx[k * 2]
        skeleton["slots"].append({
            "name": nm, "bone": "Root", "color": "ffffffff",
            "attachment": nm,
        })
        att = {
            "type": "mesh", "uvs": [fnum(x) for u in p.uvs2 for x in u],
            "triangles": list(p.tris),
            "vertices": [fnum(x) for x in sx],
            "hull": len(p.setup),
            "width": 1, "height": 1, "path": region,
        }
        if p.texture_path:
            att["region"] = os.path.basename(p.texture_path)
        attachments[nm] = {nm: att}
        p.spine_name = nm

    # deform 动画
    for an_name, parsed in anims:
        sampler = AnimSampler(parsed, rest=rest_sampler)
        dur = parsed["duration"]
        times = []
        t = 0.0
        while t <= dur + 1e-6:
            times.append(round(t, 6))
            t += dt
        if not times or times[-1] != dur:
            times.append(round(dur, 6))

        bone_tl = {}
        slot_deform = {}
        prev = {}
        for tm in times:
            # 采样 local 值（曲线 path 是完整层级路径）
            local_values = {}
            for tfid, tdata in mdl.transforms.items():
                sp = sampler.sample(tdata.get("anim_path", tdata["path"]), tm)
                q = sp["quat"]
                if q is None:
                    q = euler_to_quat(sp["euler"])
                local_values[tfid] = trs_mat(sp["pos"], q, sp["scale"])
            world = _world_matrices(mdl, local_values)
            for p in parts:
                if getattr(p, "skip", False):
                    continue
                m = p.mesh
                pts = _skin_mesh(p, m, world)
                cur = []
                for k, pt in enumerate(pts):
                    if p.affine is not None:
                        sx, sy = _part_xy(p, pt, root_origin)
                        r = np.array([sx, sy, 1.0]) @ p.affine
                        a = (float(r[0]), float(r[1]))
                    else:
                        a = _part_xy(p, pt, root_origin)
                    if flip:
                        a = (-a[0], a[1])
                    if getattr(p, "truth_anchor", False):
                        b = p.our_base[k]
                        cur.extend([a[0] - b[0], a[1] - b[1]])
                    else:
                        b = p.spine_setup[k]
                        if flip:
                            b = (-b[0], b[1])
                        cur.extend([a[0] - b[0], a[1] - b[1]])
                if p.spine_name in prev and cur == prev[p.spine_name]:
                    continue
                prev[p.spine_name] = list(cur)
                fr = {"time": fnum(tm)}
                if any(abs(v) > 1e-4 for v in cur):
                    fr["vertices"] = [fnum(v) for v in cur]
                slot_deform.setdefault(p.spine_name, []).append(fr)
        anim_obj = {}
        if slot_deform:
            deform = {}
            for nm2, frames in slot_deform.items():
                deform.setdefault("default", {}).setdefault(nm2, {})[nm2] = frames
            anim_obj["deform"] = deform
        skeleton["animations"][an_name] = anim_obj

    # 输出图集（每贴图一整页，一个 region）
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, base + "_2d.json")
    atlas_path = os.path.join(out_dir, base + "_2d.atlas")
    with open(json_path, "w", encoding="utf-8") as fp:
        json.dump(skeleton, fp, ensure_ascii=False, indent=1)
    from ..spine.spine_out import atlas_text as _atlas_text
    packed = _pack(pack_list, max_dim=8192)
    atlas_pages = []
    for pi, page in enumerate(packed):
        fname = "%s_2d_%d.png" % (base, pi)
        page["image"].save(os.path.join(out_dir, fname))
        atlas_pages.append({
            "file": fname,
            "size": page["size"],
            "regions": [(name, {"x": meta.get("x", 0), "y": meta.get("y", 0),
                                "width": meta["width"],
                                "height": meta["height"]})
                        for name, meta in page["regions"]],
        })
    open(atlas_path, "w", encoding="utf-8").write(_atlas_text(atlas_pages))
    from ..spine.spine_out import write_viewer_config
    write_viewer_config(out_dir, skeleton, os.path.basename(json_path),
                        os.path.basename(atlas_path),
                        [os.path.splitext(p["file"])[0] for p in atlas_pages])
    return json_path, atlas_path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="NormalLocal 2DModel -> Spine")
    ap.add_argument("prefab")
    ap.add_argument("out_dir")
    ap.add_argument("dt", nargs="?", type=float, default=0.05)
    ap.add_argument("--truth", help="Unity 调试脚本导出的 JSON 真值文件")
    ap.add_argument("--layout", help="SceneLayout JSON（sprite 世界包围盒）")
    args = ap.parse_args()
    if len(args.prefab) < 1:
        print("用法: python -m ngui2spine.convert_2dmodel <prefab> <输出目录> [dt] [--truth json]")
        sys.exit(2)
    print(convert(args.prefab,
                  _resolve(r"D:\VB\Search\NormalLocal\lastOrign\Assets"),
                  args.out_dir,
                  dt=args.dt,
                  truth_path=args.truth,
                  layout_path=args.layout))
