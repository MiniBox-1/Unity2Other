# -*- coding: utf-8 -*-
"""moc3 构建器（v1 基础格式）。

设计约定（全部由 tools/core_probe 与 reverse/ 的实测结论得出）：

* 目标 moc 版本 1（Cubism 3.0 基础格式），Core 5-r.5 向后兼容；
* 头部：SOT 在 +64（160 个 u32），v<=5 的上下文结构在 +704（逆向确认，
  见 reverse/ 与 docs/05）；
* ArtMesh 的「顶点数 / 索引数」在段表里是 `position_index_counts`（顶点）
  与 `vertex_counts`（索引）——公开解析库把两者标反了，这里按实测写；
* keyform 顶点按 **Y 取反** 存储（`stored_y = -model_y`），读回时再翻回来；
* `keyform_position_begin_indices` 单位是 float 下标；
* 多参数 keyform：第一个参数（axes[0]）变化最快；
* 渲染顺序：draw order group 的 min/max 固定 0/0，render order 按
  `draw_order_group_object.indices` 的位置分配 0..n-1；
* keyform 位置池顺序 = 先所有 Warp 网格块，再所有 ArtMesh 顶点块，
  每块 64 字节对齐（与官方导出器一致；读回只依赖 begin 下标，但对齐更安全）。

用法：

    b = Moc3Builder(1000, 1000, ppu=1000)
    b.add_param("ParamAngleX", -1, 1, 0)
    part = b.add_part("P0")
    rot = b.add_rotation_deformer("R0", part=part, axes=[("ParamAngleX", [-1, 1])],
                                  keyforms=[RotationKeyform(angle=-30),
                                            RotationKeyform(angle=30)])
    b.add_artmesh("A0", part=part, deformer=rot, texture=0, uvs=..., indices=...,
                  keyforms=[ArtMeshKeyform(verts)])
    data = b.build()
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

_VENDOR = Path(__file__).resolve().parents[3] / "tools" / "vendor" / "py-moc3"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from moc3 import Moc3  # noqa: E402
from moc3._core import CountIdx as C  # noqa: E402

Vec2 = Tuple[float, float]


# --------------------------------------------------------------------------- #
# 定义
# --------------------------------------------------------------------------- #
@dataclass
class ParamDef:
    pid: str
    minimum: float
    maximum: float
    default: float
    repeats: bool = False
    decimals: int = 2


@dataclass
class ArtMeshKeyform:
    """单个 keyform 下的 ArtMesh 状态（顶点为模型空间坐标）。"""
    verts: List[Vec2]
    opacity: float = 1.0
    draw_order: float = 0.0


@dataclass
class RotationKeyform:
    """旋转变形器 keyform（角度单位为度，origin 为模型空间）。"""
    angle: float = 0.0
    origin: Vec2 = (0.0, 0.0)
    scale: float = 1.0
    opacity: float = 1.0
    reflect_x: bool = False
    reflect_y: bool = False


@dataclass
class WarpKeyform:
    """弯曲变形器 keyform：网格点（行主序，(rows+1)*(cols+1) 个）。"""
    points: List[Vec2]
    opacity: float = 1.0


@dataclass
class PartDef:
    pid: str
    parent: int = -1
    visible: bool = True
    enabled: bool = True
    axes: List[Tuple[str, Sequence[float]]] = field(default_factory=list)
    draw_orders: List[float] = field(default_factory=lambda: [0.0])


@dataclass
class ArtMeshDef:
    aid: str
    part: int
    texture: int
    uvs: List[float]                 # 2 * n_verts
    indices: List[int]
    deformer: int = -1
    axes: List[Tuple[str, Sequence[float]]] = field(default_factory=list)
    keyforms: List[ArtMeshKeyform] = field(default_factory=list)
    visible: bool = True
    enabled: bool = True


@dataclass
class DeformerDef:
    did: str
    kind: str                        # 'warp' | 'rotation'
    part: int
    parent: int = -1
    axes: List[Tuple[str, Sequence[float]]] = field(default_factory=list)
    keyforms: list = field(default_factory=list)
    rows: int = 0                    # 仅 warp：段数（网格点 = (rows+1)*(cols+1)）
    cols: int = 0
    base_angle: float = 0.0          # 仅 rotation


# --------------------------------------------------------------------------- #
# 构建器
# --------------------------------------------------------------------------- #
class Moc3Builder:
    #: 多参数 keyform 的排列：**第一个参数（axes[0]）变化最快**。
    #: 实测 axes=[A,B] 时 index = iB*len(A) + iA；(A=1,B=0) 命中第 1 个 keyform。
    #: keyforms 列表必须按这个顺序给，用 `grid_indices()` 生成最稳妥。
    keyform_axis_order = "first"

    #: 输出 draw_order_group。实测：min/max 取 0/0 时 render order 严格按
    #: `draw_order_group_object.indices` 的位置分配 0..n-1，也就是**按 ArtMesh
    #: 的添加顺序**（后面的盖前面的）。用 Part 的真实 draw order 填 min/max
    #: 会让所有 render order 退化成 0，所以这里固定 0/0。
    use_draw_order_group = True
    #: group 内对象的排列（写进 draw_order_group_object.indices）。
    draw_order_group_orders: List[int] | None = None

    #: 每个 keyform 位置块按 64 字节对齐（官方导出器的做法）。
    align_keyform_positions = True

    def __init__(self, canvas_w: float, canvas_h: float, ppu: float | None = None):
        self.canvas_w = canvas_w
        self.canvas_h = canvas_h
        self.ppu = canvas_w if ppu is None else ppu
        self.params: List[ParamDef] = []
        self.parts: List[PartDef] = []
        self.deformers: List[DeformerDef] = []
        self.artmeshes: List[ArtMeshDef] = []
        self._param_index: Dict[str, int] = {}

    # -- 添加对象 ---------------------------------------------------------- #
    def add_param(self, pid: str, minimum: float, maximum: float,
                  default: float, repeats: bool = False, decimals: int = 2) -> int:
        if pid in self._param_index:
            raise ValueError(f"duplicate parameter id: {pid}")
        idx = len(self.params)
        self._param_index[pid] = idx
        self.params.append(ParamDef(pid, minimum, maximum, default, repeats, decimals))
        return idx

    def add_part(self, pid: str, parent: int = -1, visible: bool = True,
                 enabled: bool = True, axes=None, draw_orders=None) -> int:
        axes = list(axes or [])
        count = self._keyform_count(axes)
        draw_orders = list(draw_orders) if draw_orders is not None else [0.0] * count
        if len(draw_orders) != count:
            raise ValueError(f"part {pid}: expected {count} draw orders, got {len(draw_orders)}")
        self.parts.append(PartDef(pid, parent, visible, enabled, axes, draw_orders))
        return len(self.parts) - 1

    def add_rotation_deformer(self, did: str, part: int, parent: int = -1,
                              base_angle: float = 0.0, axes=None,
                              keyforms=None) -> int:
        axes = list(axes or [])
        keyforms = list(keyforms or [RotationKeyform()])
        self._check_keyforms(did, axes, keyforms)
        self.deformers.append(DeformerDef(did, "rotation", part, parent, axes, keyforms,
                                          base_angle=base_angle))
        return len(self.deformers) - 1

    def add_warp_deformer(self, did: str, part: int, rows: int, cols: int,
                          parent: int = -1, axes=None, keyforms=None) -> int:
        axes = list(axes or [])
        keyforms = list(keyforms or [])
        self._check_keyforms(did, axes, keyforms)
        n_points = (rows + 1) * (cols + 1)
        for kf in keyforms:
            if len(kf.points) != n_points:
                raise ValueError(f"warp {did}: expected {n_points} grid points, "
                                 f"got {len(kf.points)}")
        self.deformers.append(DeformerDef(did, "warp", part, parent, axes, keyforms,
                                          rows=rows, cols=cols))
        return len(self.deformers) - 1

    def add_artmesh(self, aid: str, part: int, texture: int, uvs, indices,
                    axes=None, keyforms=None, deformer: int = -1,
                    visible: bool = True, enabled: bool = True) -> int:
        axes = list(axes or [])
        keyforms = list(keyforms or [])
        self._check_keyforms(aid, axes, keyforms)
        n_verts = len(uvs) // 2
        for kf in keyforms:
            if len(kf.verts) != n_verts:
                raise ValueError(f"artmesh {aid}: keyform vertex count mismatch")
        if indices and (min(indices) < 0 or max(indices) >= n_verts):
            raise ValueError(f"artmesh {aid}: index out of range")
        self.artmeshes.append(ArtMeshDef(aid, part, texture, list(uvs), list(indices),
                                         deformer, axes, keyforms, visible, enabled))
        return len(self.artmeshes) - 1

    # -- 辅助 -------------------------------------------------------------- #
    def _keyform_count(self, axes) -> int:
        count = 1
        for _, values in axes:
            if not values:
                raise ValueError("axis without key values")
            count *= len(values)
        return count

    def _check_keyforms(self, name, axes, keyforms):
        count = self._keyform_count(axes)
        if not keyforms:
            raise ValueError(f"{name}: at least one keyform required")
        if len(keyforms) != count:
            raise ValueError(f"{name}: expected {count} keyforms, got {len(keyforms)}")

    @staticmethod
    def grid_indices(axes) -> List[tuple]:
        """按 Core 的顺序（第一个参数变化最快）列出每个 keyform 的键组合下标。

        返回值与 `axes` 同序：axes=[A,B] 时为 (0,0) (1,0) (0,1) (1,1)。
        """
        axes = list(axes)
        if not axes:
            return [()]
        sizes = [len(values) for _, values in axes]
        total = 1
        for s in sizes:
            total *= s
        out = []
        for i in range(total):
            rem, combo = i, []
            for s in sizes:                        # 第一个轴 stride 最小 => 变化最快
                combo.append(rem % s)
                rem //= s
            out.append(tuple(combo))
        return out

    # -- 序列化 ------------------------------------------------------------ #
    def build(self) -> bytes:
        moc = Moc3()
        moc.header.version = 1
        moc.canvas.pixels_per_unit = self.ppu
        moc.canvas.origin_x = self.canvas_w / 2.0
        moc.canvas.origin_y = self.canvas_h / 2.0
        moc.canvas.canvas_width = self.canvas_w
        moc.canvas.canvas_height = self.canvas_h
        moc.canvas.canvas_flag = 0

        # ---- 参数与 key ------------------------------------------------ #
        keys_pool: List[float] = []
        bindings: List[Tuple[int, int, int]] = []  # (param_idx, key_begin, key_count)
        bands: List[List[int]] = []                # band -> binding indices

        def make_band(axes) -> int:
            band: List[int] = []
            for pid, values in axes:
                if pid not in self._param_index:
                    raise KeyError(f"unknown parameter {pid}")
                begin = len(keys_pool)
                keys_pool.extend(float(v) for v in values)
                band.append(len(bindings))
                bindings.append((self._param_index[pid], begin, len(values)))
            bands.append(band)
            return len(bands) - 1

        part_bands = [make_band(p.axes) for p in self.parts]
        deformer_bands = [make_band(d.axes) for d in self.deformers]
        mesh_bands = [make_band(a.axes) for a in self.artmeshes]

        warps = [d for d in self.deformers if d.kind == "warp"]
        rots = [d for d in self.deformers if d.kind == "rotation"]

        # ---- counts ----------------------------------------------------- #
        counts = [0] * 23
        counts[C.PARTS] = len(self.parts)
        counts[C.DEFORMERS] = len(self.deformers)
        counts[C.WARP_DEFORMERS] = len(warps)
        counts[C.ROTATION_DEFORMERS] = len(rots)
        counts[C.ART_MESHES] = len(self.artmeshes)
        counts[C.PARAMETERS] = len(self.params)
        counts[C.PART_KEYFORMS] = sum(len(p.draw_orders) for p in self.parts)
        counts[C.WARP_DEFORMER_KEYFORMS] = sum(len(d.keyforms) for d in warps)
        counts[C.ROTATION_DEFORMER_KEYFORMS] = sum(len(d.keyforms) for d in rots)
        counts[C.ART_MESH_KEYFORMS] = sum(len(a.keyforms) for a in self.artmeshes)
        counts[C.KEYFORM_BINDING_INDICES] = len(bindings)
        counts[C.KEYFORM_BINDING_BANDS] = len(bands)
        counts[C.KEYFORM_BINDINGS] = len(bindings)
        counts[C.KEYS] = len(keys_pool)
        counts[C.UVS] = sum(len(a.uvs) for a in self.artmeshes)
        counts[C.POSITION_INDICES] = sum(len(a.indices) for a in self.artmeshes)
        counts[C.DRAWABLE_MASKS] = 0
        if self.use_draw_order_group:
            counts[C.DRAW_ORDER_GROUPS] = 1 if self.artmeshes else 0
            counts[C.DRAW_ORDER_GROUP_OBJECTS] = len(self.artmeshes)
        counts[C.GLUES] = 0
        counts[C.GLUE_INFOS] = 0
        counts[C.GLUE_KEYFORMS] = 0

        # ---- keyform 位置池（先 warp 网格，再 art 顶点，块 64B 对齐） ------ #
        positions: List[float] = []
        warp_pos_begin: List[int] = []
        art_pos_begin: List[int] = []

        def push_block(points: Sequence[Vec2], flip_y: bool) -> int:
            if self.align_keyform_positions:
                # 当前 float 下标按 64 字节（16 float）对齐
                pad = (-len(positions)) % 16
                positions.extend([0.0] * pad)
            begin = len(positions)
            for x, y in points:
                positions.append(float(x))
                # 实测：ArtMesh 顶点按 Y 取反存储；Warp 网格点按模型空间原样存储
                positions.append(-float(y) if flip_y else float(y))
            return begin

        for d in warps:
            for kf in d.keyforms:
                warp_pos_begin.append(push_block(kf.points, flip_y=False))
        for a in self.artmeshes:
            for kf in a.keyforms:
                art_pos_begin.append(push_block(kf.verts, flip_y=True))

        counts[C.KEYFORM_POSITIONS] = len(positions)
        moc.counts = counts

        def s(name, data):
            moc[name] = data

        # ---- parts ------------------------------------------------------ #
        s("part.ids", [p.pid for p in self.parts])
        s("part.keyform_binding_band_indices", part_bands)
        s("part.keyform_begin_indices",
          _begins([len(p.draw_orders) for p in self.parts]))
        s("part.keyform_counts", [len(p.draw_orders) for p in self.parts])
        s("part.visibles", [p.visible for p in self.parts])
        s("part.enables", [p.enabled for p in self.parts])
        s("part.parent_part_indices", [p.parent for p in self.parts])
        s("part_keyform.draw_orders", [d for p in self.parts for d in p.draw_orders])

        # ---- deformers --------------------------------------------------- #
        s("deformer.ids", [d.did for d in self.deformers])
        s("deformer.keyform_binding_band_indices", deformer_bands)
        s("deformer.visibles", [True] * len(self.deformers))
        s("deformer.enables", [True] * len(self.deformers))
        s("deformer.parent_part_indices", [d.part for d in self.deformers])
        s("deformer.parent_deformer_indices", [d.parent for d in self.deformers])
        s("deformer.types", [0 if d.kind == "warp" else 1 for d in self.deformers])

        specific: List[int] = []
        warp_i = rot_i = 0
        for d in self.deformers:
            if d.kind == "warp":
                specific.append(warp_i)
                warp_i += 1
            else:
                specific.append(rot_i)
                rot_i += 1
        s("deformer.specific_indices", specific)

        # warp 专属
        s("warp_deformer.rows", [d.rows for d in warps])
        s("warp_deformer.cols", [d.cols for d in warps])
        s("warp_deformer.vertex_counts", [len(d.keyforms[0].points) for d in warps])
        s("warp_deformer.keyform_binding_band_indices",
          [deformer_bands[self.deformers.index(d)] for d in warps])
        s("warp_deformer.keyform_begin_indices", _begins([len(d.keyforms) for d in warps]))
        s("warp_deformer.keyform_counts", [len(d.keyforms) for d in warps])
        s("warp_deformer_keyform.opacities", [kf.opacity for d in warps for kf in d.keyforms])
        s("warp_deformer_keyform.keyform_position_begin_indices", warp_pos_begin)

        # rotation 专属
        s("rotation_deformer.base_angles", [d.base_angle for d in rots])
        s("rotation_deformer.keyform_binding_band_indices",
          [deformer_bands[self.deformers.index(d)] for d in rots])
        s("rotation_deformer.keyform_begin_indices", _begins([len(d.keyforms) for d in rots]))
        s("rotation_deformer.keyform_counts", [len(d.keyforms) for d in rots])
        s("rotation_deformer_keyform.opacities", [kf.opacity for d in rots for kf in d.keyforms])
        s("rotation_deformer_keyform.angles", [kf.angle for d in rots for kf in d.keyforms])
        s("rotation_deformer_keyform.origin_xs",
          [kf.origin[0] for d in rots for kf in d.keyforms])
        s("rotation_deformer_keyform.origin_ys",
          [-kf.origin[1] for d in rots for kf in d.keyforms])
        s("rotation_deformer_keyform.scales", [kf.scale for d in rots for kf in d.keyforms])
        s("rotation_deformer_keyform.reflect_xs",
          [kf.reflect_x for d in rots for kf in d.keyforms])
        s("rotation_deformer_keyform.reflect_ys",
          [kf.reflect_y for d in rots for kf in d.keyforms])

        # ---- art meshes --------------------------------------------------- #
        s("art_mesh.ids", [a.aid for a in self.artmeshes])
        s("art_mesh.keyform_binding_band_indices", mesh_bands)
        s("art_mesh.keyform_begin_indices",
          _begins([len(a.keyforms) for a in self.artmeshes]))
        s("art_mesh.keyform_counts", [len(a.keyforms) for a in self.artmeshes])
        s("art_mesh.visibles", [a.visible for a in self.artmeshes])
        s("art_mesh.enables", [a.enabled for a in self.artmeshes])
        s("art_mesh.parent_part_indices", [a.part for a in self.artmeshes])
        s("art_mesh.parent_deformer_indices", [a.deformer for a in self.artmeshes])
        s("art_mesh.texture_indices", [a.texture for a in self.artmeshes])
        s("art_mesh.drawable_flags", [0 for _ in self.artmeshes])
        # 实测：这两个段名与「顶点数/索引数」是反的
        s("art_mesh.position_index_counts", [len(a.uvs) // 2 for a in self.artmeshes])
        s("art_mesh.uv_begin_indices",
          _begins([len(a.uvs) for a in self.artmeshes], scale=1))
        s("art_mesh.position_index_begin_indices",
          _begins([len(a.indices) for a in self.artmeshes]))
        s("art_mesh.vertex_counts", [len(a.indices) for a in self.artmeshes])
        s("art_mesh.mask_begin_indices", [0 for _ in self.artmeshes])
        s("art_mesh.mask_counts", [0 for _ in self.artmeshes])

        # ---- parameters ---------------------------------------------------- #
        s("parameter.ids", [p.pid for p in self.params])
        s("parameter.min_values", [p.minimum for p in self.params])
        s("parameter.max_values", [p.maximum for p in self.params])
        s("parameter.default_values", [p.default for p in self.params])
        s("parameter.repeats", [p.repeats for p in self.params])
        s("parameter.decimal_places", [p.decimals for p in self.params])
        per_param = [sum(1 for b in bindings if b[0] == i)
                     for i in range(len(self.params))]
        s("parameter.keyform_binding_begin_indices", _begins(per_param))
        s("parameter.keyform_binding_counts", per_param)

        # ---- keyform bindings ---------------------------------------------- #
        s("keyform_binding_band.begin_indices", _begins([len(b) for b in bands]))
        s("keyform_binding_band.counts", [len(b) for b in bands])
        s("keyform_binding.keys_begin_indices", [b[1] for b in bindings])
        s("keyform_binding.keys_counts", [b[2] for b in bindings])
        s("keyform_binding_index.indices", [b[0] for b in bindings])
        s("keys.values", keys_pool)

        # ---- keyform 数据 --------------------------------------------------- #
        s("keyform_position.xys", positions)
        s("art_mesh_keyform.keyform_position_begin_indices", art_pos_begin)
        s("art_mesh_keyform.opacities",
          [kf.opacity for a in self.artmeshes for kf in a.keyforms])
        s("art_mesh_keyform.draw_orders",
          [kf.draw_order for a in self.artmeshes for kf in a.keyforms])

        # ---- uv / 索引 ------------------------------------------------------ #
        s("uv.xys", [v for a in self.artmeshes for v in a.uvs])
        s("position_index.indices", [i for a in self.artmeshes for i in a.indices])

        # ---- draw order group ------------------------------------------------ #
        if self.use_draw_order_group and self.artmeshes:
            s("draw_order_group.object_begin_indices", [0])
            s("draw_order_group.object_counts", [len(self.artmeshes)])
            s("draw_order_group.object_total_counts", [len(self.artmeshes)])
            s("draw_order_group.min_draw_orders", [0])
            s("draw_order_group.max_draw_orders", [0])
            s("draw_order_group_object.types", [0] * len(self.artmeshes))
            s("draw_order_group_object.indices",
              self.draw_order_group_orders or list(range(len(self.artmeshes))))
            s("draw_order_group_object.group_indices", [-1] * len(self.artmeshes))

        return moc.to_bytes()


def _begins(lengths: Sequence[int], scale: int = 1) -> List[int]:
    """累计起点（moc3 的 begin 数组都是「前 n 项长度和」）。"""
    out, acc = [], 0
    for n in lengths:
        out.append(acc)
        acc += n * scale
    return out
