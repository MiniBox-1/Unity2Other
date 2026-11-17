# -*- coding: utf-8 -*-
"""带骨骼变形的静态模型：Parts + RotationDeformer 链 + ArtMesh。

与 `static_model.py` 的区别：ArtMesh 不再直接挂在模型空间，而是挂在
「主导骨骼」的 RotationDeformer 下；变形器链照抄 Unity 骨骼层级。
静止姿态与静态模型**逐顶点一致**（顶点用近似链的逆变换回骨骼空间）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

from ..moc3 import ArtMeshKeyform, Moc3Builder, RotationKeyform
from .rig import Bone, apply, collect_bones, inv, param_id, safe_id


@dataclass
class RigPart:
    name: str
    verts: List[Tuple[float, float]]
    uvs: List[float]
    indices: List[int]
    bone: int = -1                 # 主导骨骼 tfid
    sorting_order: int = 0
    order: int = 0
    texture: int = 0               # 贴图页下标


@dataclass
class RigResult:
    moc: bytes
    canvas_w: float
    canvas_h: float
    ppu: float
    bbox: Tuple[float, float, float, float]
    center: Tuple[float, float]
    parts: List[RigPart]
    bones: Dict[int, Bone]
    deformers: List[int] = field(default_factory=list)


def build_rigged(parts: List[RigPart], mdl, bones=None,
                 ppu: float = 1000.0, margin: float = 0.05,
                 angle_range: Tuple[float, float] | None = None,
                 bounds=None) -> RigResult:
    """bounds: 可选的画布包围盒 (minx,maxx,miny,maxy)，用于忽略远端碎片。"""
    if bounds is not None:
        minx, maxx, miny, maxy = bounds
    else:
        xs = [v[0] for p in parts for v in p.verts]
        ys = [v[1] for p in parts for v in p.verts]
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    w = (maxx - minx) * (1 + 2 * margin)
    h = (maxy - miny) * (1 + 2 * margin)

    b = Moc3Builder(w * ppu, h * ppu, ppu=ppu)

    if bones is None:
        bone_ids = {p.bone for p in parts if p.bone >= 0}
        bones = collect_bones(mdl, bone_ids)

    for i, p in enumerate(parts):
        b.add_part(f"Part_{i:02d}_{safe_id(p.name, 40)}")

    # 变形器按深度创建（父先子后）
    def depth(tfid):
        d = 0
        cur = bones[tfid].parent
        while cur in bones:
            d += 1
            cur = bones[cur].parent
        return d

    order = sorted(bones.values(), key=lambda x: depth(x.tfid))
    # 变形器挂在「第一个使用它的 ArtMesh 所属的 Part」上（索引 = parts 下标）
    part_of_bone: Dict[int, int] = {}
    for i, p in enumerate(parts):
        part_of_bone.setdefault(p.bone, i)

    for bone in order:
        parent_idx = bones[bone.parent].deformer if bone.parent in bones else -1
        part_index = part_of_bone.get(bone.tfid, 0)
        origin = bone.origin
        if parent_idx < 0:
            # 根变形器的 origin 在模型空间，需要跟着整体居中一起平移
            origin = (origin[0] - cx, origin[1] - cy)

        if angle_range is None:
            axes, kfs = [], [RotationKeyform(angle=bone.angle, origin=origin,
                                             scale=bone.scale)]
        else:
            lo, hi = angle_range
            pid = param_id(bone)
            b.add_param(pid, lo, hi, 0.0, decimals=2)
            axes = [(pid, [lo, 0.0, hi])]
            base = bone.angle
            kfs = [RotationKeyform(angle=base + lo, origin=origin, scale=bone.scale),
                   RotationKeyform(angle=base, origin=origin, scale=bone.scale),
                   RotationKeyform(angle=base + hi, origin=origin, scale=bone.scale)]
        bone.deformer = b.add_rotation_deformer(
            name_of(bone), part=part_index, parent=parent_idx,
            axes=axes, keyforms=kfs)

    for i, p in enumerate(parts):
        bone = bones.get(p.bone)
        if bone is not None:
            # 顶点存到「骨骼局部空间」：inv(W') * world（W' 未居中，与上面的
            # 根 origin 平移正好抵消，见模块说明）
            local = [apply(inv(bone.approx_world), (x, y)) for x, y in p.verts]
            deformer = bone.deformer
        else:
            local = [(x - cx, y - cy) for x, y in p.verts]
            deformer = -1

        uvs = [c if k % 2 == 0 else 1.0 - c for k, c in enumerate(p.uvs)]
        b.add_artmesh(f"Art_{i:02d}", part=i, texture=p.texture, uvs=uvs,
                      indices=p.indices, deformer=deformer,
                      keyforms=[ArtMeshKeyform(local)])

    return RigResult(b.build(), w * ppu, h * ppu, ppu,
                     (minx, maxx, miny, maxy), (cx, cy), parts, bones,
                     [bones[t].deformer for t in bones])


def name_of(bone: Bone) -> str:
    return f"D_{safe_id(bone.name or ('Bone_' + str(bone.tfid)), 40)}_{bone.tfid % 100000}"



