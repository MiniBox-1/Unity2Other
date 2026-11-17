# -*- coding: utf-8 -*-
"""骨骼树 → RotationDeformer 链。

2D 仿射约定：矩阵是 2x3 (a, b, c, d, tx, ty)，
    x' = a*x + c*y + tx
    y' = b*x + d*y + ty
（列主序，与 Unity 的 TRS 平面投影一致。）

做法：
1. 收集角色用到的骨骼（parts 的 bones 并集）；
2. 每个骨骼的局部变换 = inv(W_parent) ∘ W_bone，拆成
   `origin + 旋转角 + 等比缩放`（RotationDeformer 的 keyform 三件套）；
3. 用这个「近似链」重新算每个骨骼的 W'，顶点存 inv(W'_bone) * world，
   这样即使有非等比缩放/剪切，**静止姿态仍然逐顶点精确**；
4. ArtMesh 挂到「主导骨骼」的变形器下。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

Affine = Tuple[float, float, float, float, float, float]   # a,b,c,d,tx,ty


# --------------------------------------------------------------------------- #
# 2D 仿射
# --------------------------------------------------------------------------- #
def affine(a=1.0, b=0.0, c=0.0, d=1.0, tx=0.0, ty=0.0) -> Affine:
    return (a, b, c, d, tx, ty)


def mul(m: Affine, n: Affine) -> Affine:
    """m ∘ n（先 n 后 m）。"""
    a, b, c, d, tx, ty = m
    e, f, g, h, ux, uy = n
    return (a * e + c * f, b * e + d * f,
            a * g + c * h, b * g + d * h,
            a * ux + c * uy + tx, b * ux + d * uy + ty)


def apply(m: Affine, p: Tuple[float, float]) -> Tuple[float, float]:
    a, b, c, d, tx, ty = m
    return (a * p[0] + c * p[1] + tx, b * p[0] + d * p[1] + ty)


def safe_id(text: str, limit: int = 44) -> str:
    """moc3 的 id 字段是 64 字节定长，这里统一压到安全长度。"""
    s = re.sub(r"[^0-9A-Za-z_\-]+", "_", text or "")
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:limit] or "X"


def param_id(bone: "Bone") -> str:
    """骨骼 → 参数 id（唯一；骨骼重名时用 tfid 后缀区分）。"""
    base = bone.name or f"Bone_{bone.tfid}"
    clean = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in base)
    return f"P_{clean}_{bone.tfid % 1000000:06d}_Rz"


def inv(m: Affine) -> Affine:
    a, b, c, d, tx, ty = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        det = 1e-12
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return (ia, ib, ic, id_,
            -(ia * tx + ic * ty), -(ib * tx + id_ * ty))


def from_trs(pos, quat, scale) -> Affine:
    """Unity (x,y,z,w) 四元数 → 平面仿射（取完整 3x3 旋转的 XY 投影）。

    不能只取 Z 分量：这批 prefab 的骨骼常带 X 轴 180° 翻转，只按 Z 算会把
    整条骨链算歪（表现为 origin 飞到 6+ 单位外）。
    """
    x, y, z, w = quat
    r00 = 1 - 2 * (y * y + z * z)
    r01 = 2 * (x * y - z * w)
    r10 = 2 * (x * y + z * w)
    r11 = 1 - 2 * (x * x + z * z)
    sx, sy = scale[0], scale[1]
    return (r00 * sx, r10 * sx, r01 * sy, r11 * sy, pos[0], pos[1])


def decompose(m: Affine) -> Tuple[Tuple[float, float], float, float, bool]:
    """拆成 (origin, angle_deg, uniform_scale, is_uniform)。"""
    a, b, c, d, tx, ty = m
    sx = math.hypot(a, b)
    sy = math.hypot(c, d)
    # Live2D 的正角度是顺时针（模型空间 (x,y)->(y,-x)），与数学正方向相反
    ang = -math.degrees(math.atan2(b, a))
    uniform = abs(sx - sy) <= 1e-3 * max(1.0, sx)
    # 剪切检测：两轴是否正交
    dot = a * c + b * d
    uniform = uniform and abs(dot) <= 1e-3 * max(1e-6, sx * sy)
    scale = (sx + sy) / 2.0 if uniform else sx
    return ((tx, ty), ang, scale, uniform)


def from_deformer(origin, angle_deg, scale) -> Affine:
    """Live2D 角度约定（正 = 顺时针）→ 数学仿射。"""
    r = math.radians(angle_deg)
    ca, sa = math.cos(r), math.sin(r)
    # p' = R(-angle) * scale * p + origin
    return (ca * scale, -sa * scale, sa * scale, ca * scale, origin[0], origin[1])


# --------------------------------------------------------------------------- #
# 骨骼
# --------------------------------------------------------------------------- #
@dataclass
class Bone:
    tfid: int
    name: str
    father: int
    world: Affine
    parent: int = -1          # 父骨骼 tfid（最近的骨骼祖先）
    origin: Tuple[float, float] = (0.0, 0.0)
    angle: float = 0.0
    scale: float = 1.0
    exact: bool = True
    approx_world: Affine = affine()
    deformer: int = -1


def _father(mdl, tfid):
    t = mdl.transforms.get(tfid)
    return t.get("father") if t else None


def collect_bones(mdl, bone_ids, world=None) -> Dict[int, Bone]:
    """world: 可选的 tfid -> 2D 仿射（用于「以某个动画帧为基准姿势」）。"""
    world_cache: Dict[int, Affine] = {}

    def world_of(tfid):
        if tfid in world_cache:
            return world_cache[tfid]
        if world is not None and tfid in world:
            m = world[tfid]
            world_cache[tfid] = m
            return m
        t = mdl.transforms[tfid]
        m = from_trs(t["pos"], t["quat"], t["scale"])
        f = t.get("father")
        if f in mdl.transforms:
            m = mul(world_of(f), m)
        world_cache[tfid] = m
        return m

    bones: Dict[int, Bone] = {}
    for tfid in bone_ids:
        t = mdl.transforms[tfid]
        bones[tfid] = Bone(tfid=tfid, name=t.get("name", ""),
                           father=t.get("father"), world=world_of(tfid))

    # 最近的骨骼祖先
    for tfid, b in bones.items():
        f = b.father
        while f is not None and f not in bones and f in mdl.transforms:
            f = _father(mdl, f)
        b.parent = f if f in bones else -1

    # 局部变换 → origin / angle / scale，并用近似链重算 world
    order = sorted(bones.values(), key=lambda b: _depth(mdl, b.tfid))
    for b in order:
        pw = bones[b.parent].approx_world if b.parent in bones else affine()
        local = mul(inv(pw), b.world)
        (ox, oy), ang, sc, exact = decompose(local)
        b.origin, b.angle, b.scale, b.exact = (ox, oy), ang, sc, exact
        b.approx_world = mul(pw, from_deformer((ox, oy), ang, sc))
    return bones


def _depth(mdl, tfid) -> int:
    d = 0
    t = mdl.transforms.get(tfid)
    while t and t.get("father") in mdl.transforms:
        d += 1
        t = mdl.transforms[t["father"]]
    return d


def part_weights_by_bone(part) -> Dict[int, float]:
    """按 boneIndexRaw + weights 把每个顶点的权重汇总到骨骼 tfid。"""
    bones = [b for b in (part.bones or []) if b]
    mesh = part.mesh or {}
    weights = mesh.get("weights") or []
    raw = mesh.get("boneIndexRaw") or []
    acc: Dict[int, float] = {}
    for vi, w in enumerate(weights):
        bi = raw[vi] if vi < len(raw) else (0, 0, 0, 0)
        for k in range(min(4, len(w))):
            ww = float(w[k])
            if abs(ww) < 1e-6:
                continue
            idx = int(round(float(bi[k]))) if k < len(bi) else 0
            if 0 <= idx < len(bones):
                acc[bones[idx]] = acc.get(bones[idx], 0.0) + ww
    return acc


#: 表情用骨骼：这些骨由游戏的表情系统驱动，不该拿来当部件的主骨
_EXPR_BONE = re.compile(r"(Mouth|Eye|Brow|Face|Cheek|Tear|Drool)", re.I)


def dominant_bone(part, bones: Dict[int, "Bone"], verts=None) -> int | None:
    """主导骨骼：逐顶点「最大权重」投票，排除表情骨。

    这批 SMR 的 `m_Bones` 表里混了表情骨与手/臂骨，权重和不可靠；
    逐顶点投票只统计「这根骨是这个顶点的主骨」的次数。若一个部件几乎没有
    非表情主骨（脸部件就是这种），回落到 `Bone_Head`；再不行才用几何最近骨。
    """
    votes: Dict[int, int] = {}
    bone_list = [b for b in (part.bones or []) if b]
    mesh = part.mesh or {}
    weights = mesh.get("weights") or []
    raw = mesh.get("boneIndexRaw") or []
    for vi, w in enumerate(weights):
        if not w:
            continue
        bi = raw[vi] if vi < len(raw) else (0, 0, 0, 0)
        k = max(range(min(4, len(w))), key=lambda j: float(w[j]))
        if float(w[k]) < 0.5:
            continue                      # 混合权重：没有单一主骨
        idx = int(round(float(bi[k]))) if k < len(bi) else 0
        if 0 <= idx < len(bone_list):
            tfid = bone_list[idx]
            b = bones.get(tfid)
            if b and not _EXPR_BONE.search(b.name or ""):
                votes[tfid] = votes.get(tfid, 0) + 1

    verts = verts or []
    cxs = sum(v[0] for v in verts) / len(verts) if verts else 0.0
    cys = sum(v[1] for v in verts) / len(verts) if verts else 0.0

    n = len(weights) or 1
    if votes and sum(votes.values()) >= 0.3 * n:
        # 票数要高，也要离部件近（否则手臂骨会抢走脸部件）
        def score(kv):
            tfid, cnt = kv
            b = bones[tfid]
            d = math.hypot(b.world[4] - cxs, b.world[5] - cys)
            return cnt / (1.0 + 4.0 * d)
        return max(votes.items(), key=score)[0]

    # 没有任何权重（Sprite/静态部件）：按几何最近骨归属，不能用 Head 兜底
    verts = verts or []
    if not bone_list and verts:
        best, best_d = None, 1e18
        for tfid, b in bones.items():
            if _EXPR_BONE.search(b.name or ""):
                continue
            d = math.hypot(b.world[4] - cxs, b.world[5] - cys)
            if d < best_d:
                best, best_d = tfid, d
        if best is not None:
            return best

    for tfid, b in bones.items():
        if (b.name or "") == "Bone_Head":
            return tfid
    best, best_d = None, 1e18
    for tfid, b in bones.items():
        if _EXPR_BONE.search(b.name or ""):
            continue
        d = math.hypot(b.world[4] - cxs, b.world[5] - cys)
        if d < best_d:
            best, best_d = tfid, d
    return best
