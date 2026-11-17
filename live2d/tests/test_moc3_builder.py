# -*- coding: utf-8 -*-
r"""Moc3Builder 的回归测试：用真实 Cubism Core 校验生成结果。

跑法： python D:\VB\Convert\Live2d\tests\test_moc3_builder.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity2live2d.moc3 import (
    ArtMeshKeyform, CubismCore, Moc3Builder, RotationKeyform, WarpKeyform)  # noqa: E402

CORE = CubismCore()
QUAD = [(-0.25, -0.25), (0.25, -0.25), (0.25, 0.25), (-0.25, 0.25)]
UVS = [0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
TRI = [0, 1, 2, 0, 2, 3]


def shifted(dx=0.0, dy=0.0):
    return [(x + dx, y + dy) for x, y in QUAD]


def approx(got, want, tol=1e-5):
    return len(got) == len(want) and all(
        abs(g[0] - w[0]) <= tol and abs(g[1] - w[1]) <= tol
        for g, w in zip(got, want))


def test_single_param():
    b = Moc3Builder(1000, 1000, ppu=1000)
    b.add_param("ParamAngleX", -1, 1, 0)
    part = b.add_part("Part0")
    b.add_artmesh("Art0", part=part, texture=0, uvs=UVS, indices=TRI,
                  axes=[("ParamAngleX", [-1, 1])],
                  keyforms=[ArtMeshKeyform(shifted()),
                            ArtMeshKeyform(shifted(0.1))])

    data = b.build()
    assert CORE.consistency(data) == 1, "consistency failed"

    m = CORE.load(data)
    assert m is not None
    assert m.parameter_ids() == ["ParamAngleX"]
    assert m.parameter_range("ParamAngleX") == (-1.0, 1.0, 0.0)
    assert m.parameter_keys("ParamAngleX") == [-1.0, 1.0]

    m.set_param("ParamAngleX", -1.0)
    m.update()
    assert approx(m.vertices(0), QUAD), m.vertices(0)

    m.set_param("ParamAngleX", 0.0)
    m.update()
    mid = m.vertices(0)
    assert approx(mid, shifted(0.05)), mid

    m.set_param("ParamAngleX", 1.0)
    m.update()
    assert approx(m.vertices(0), shifted(0.1)), m.vertices(0)

    print("ok  single param: consistency, range, keys, Y convention, interpolation")


def test_two_params_axis_order():
    """判定多参数 keyform 的排列顺序（哪个参数变化最快）。"""
    b = Moc3Builder(1000, 1000, ppu=1000)
    b.add_param("A", 0, 1, 0)
    b.add_param("B", 0, 1, 0)
    part = b.add_part("Part0")
    # 4 个 keyform 的 X 依次为 0.0 / 0.1 / 0.2 / 0.3
    kfs = [ArtMeshKeyform(shifted(0.1 * i)) for i in range(4)]
    b.add_artmesh("Art0", part=part, texture=0, uvs=UVS, indices=TRI,
                  axes=[("A", [0, 1]), ("B", [0, 1])], keyforms=kfs)

    data = b.build()
    assert CORE.consistency(data) == 1

    m = CORE.load(data)
    m.set_param("A", 1.0)
    m.set_param("B", 0.0)
    m.update()
    x = m.vertices(0)[0][0]
    index = round((x + 0.25) / 0.1)

    order = "B fastest (index = A*2 + B)" if index == 2 else "A fastest (index = B*2 + A)"
    print(f"ok  two params: (A=1,B=0) -> keyform index {index}  => {order}")
    # 实测：第一个参数变化最快，因此 (A=1,B=0) 命中第 1 个 keyform
    assert index == 1, index
    # A 变化最快：(0,0) (1,0) (0,1) (1,1)
    assert Moc3Builder.grid_indices([("A", [0, 1]), ("B", [0, 1])]) == [
        (0, 0), (1, 0), (0, 1), (1, 1)]


def test_parts_and_meshes():
    b = Moc3Builder(800, 600, ppu=800)
    b.add_param("P", 0, 1, 0)
    # 排序由 Part 的 draw_order 决定；ArtMesh 的 draw_order 保持 0（实测非 0 会打乱）
    p0 = b.add_part("Body", draw_orders=[0.0])
    p1 = b.add_part("Head", parent=p0, draw_orders=[100.0])
    b.add_artmesh("BodyA", part=p0, texture=0, uvs=UVS, indices=TRI,
                  keyforms=[ArtMeshKeyform(shifted())])
    b.add_artmesh("HeadA", part=p1, texture=0, uvs=UVS, indices=TRI,
                  keyforms=[ArtMeshKeyform(shifted(0.0, 0.2))])

    data = b.build()
    assert CORE.consistency(data) == 1
    m = CORE.load(data)
    assert m.part_ids() == ["Body", "Head"]
    assert m.drawable_ids() == ["BodyA", "HeadA"]
    assert m.drawable(0)["vertex_count"] == 4
    assert m.drawable(1)["vertex_count"] == 4
    assert m.drawable(0)["render_order"] < m.drawable(1)["render_order"]
    print("ok  parts/meshes: hierarchy, ids, draw orders")


def test_rotation_deformer():
    """旋转变形器：angle 正方向、origin 平移、scale 缩放。"""
    verts = [(0.5, -0.1), (0.7, -0.1), (0.7, 0.1), (0.5, 0.1)]

    def build(kfs):
        b = Moc3Builder(1000, 1000, ppu=1000)
        b.add_param("P", 0, 1, 0)
        p = b.add_part("P0")
        rot = b.add_rotation_deformer("R0", part=p, axes=[("P", [0, 1])], keyforms=kfs)
        b.add_artmesh("A", part=p, deformer=rot, texture=0, uvs=UVS, indices=TRI,
                      keyforms=[ArtMeshKeyform(verts)])
        return CORE.load(b.build())

    # angle: 0 -> 90（正角度 = 顺时针，模型空间 (x,y) -> (y,-x)）
    m = build([RotationKeyform(angle=0.0), RotationKeyform(angle=90.0)])
    m.set_param("P", 0.0); m.update()
    assert approx(m.vertices(0), verts), m.vertices(0)
    m.set_param("P", 1.0); m.update()
    assert approx(m.vertices(0), [(-0.1, -0.5), (-0.1, -0.7), (0.1, -0.7), (0.1, -0.5)]), m.vertices(0)

    # origin: 平移
    m = build([RotationKeyform(angle=0.0, origin=(0.5, 0.0)),
               RotationKeyform(angle=0.0, origin=(0.5, 0.0))])
    m.set_param("P", 1.0); m.update()
    assert approx(m.vertices(0), [(x + 0.5, y) for x, y in verts]), m.vertices(0)

    # scale: 以 origin 为基点缩放
    m = build([RotationKeyform(angle=0.0, scale=1.0),
               RotationKeyform(angle=0.0, scale=2.0)])
    m.set_param("P", 1.0); m.update()
    assert approx(m.vertices(0), [(x * 2, y * 2) for x, y in verts]), m.vertices(0)
    print("ok  rotation deformer: angle / origin / scale")


def test_warp_deformer():
    """弯曲变形器：网格点定义绝对位置，Q=0 恒等、Q=1 拉伸。"""
    verts = [(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)]

    def grid(sy):
        return [(0.0, 0.0), (1.0, 0.0), (0.0, sy), (1.0, sy)]

    b = Moc3Builder(1000, 1000, ppu=1000)
    b.add_param("Q", 0, 1, 0)
    p = b.add_part("P0")
    w = b.add_warp_deformer("W", part=p, rows=1, cols=1, axes=[("Q", [0, 1])],
                            keyforms=[WarpKeyform(grid(1.0)), WarpKeyform(grid(2.0))])
    b.add_artmesh("B", part=p, deformer=w, texture=0, uvs=UVS, indices=TRI,
                  keyforms=[ArtMeshKeyform(verts)])

    data = b.build()
    assert CORE.consistency(data) == 1
    m = CORE.load(data)
    m.set_param("Q", 0.0); m.update()
    assert approx(m.vertices(0), verts), m.vertices(0)
    m.set_param("Q", 1.0); m.update()
    assert approx(m.vertices(0), [(0.25, 0.5), (0.75, 0.5), (0.75, 1.5), (0.25, 1.5)]), m.vertices(0)
    print("ok  warp deformer: grid mapping")


def test_nested_deformers():
    """父子变形器：父旋转 90°，子平移，验证层级组合。"""
    b = Moc3Builder(1000, 1000, ppu=1000)
    b.add_param("R", 0, 1, 0)
    b.add_param("T", 0, 1, 0)
    p = b.add_part("P0")
    parent = b.add_rotation_deformer("Rp", part=p, axes=[("R", [0, 1])],
                                     keyforms=[RotationKeyform(angle=0.0),
                                               RotationKeyform(angle=90.0)])
    child = b.add_rotation_deformer("Rc", part=p, parent=parent, axes=[("T", [0, 1])],
                                    keyforms=[RotationKeyform(angle=0.0, origin=(0.0, 0.0)),
                                              RotationKeyform(angle=0.0, origin=(1.0, 0.0))])
    b.add_artmesh("A", part=p, deformer=child, texture=0, uvs=UVS, indices=TRI,
                  keyforms=[ArtMeshKeyform(QUAD)])

    data = b.build()
    assert CORE.consistency(data) == 1
    m = CORE.load(data)
    m.set_param("R", 0.0); m.set_param("T", 0.0); m.update()
    assert approx(m.vertices(0), QUAD), m.vertices(0)
    # 子平移 (1,0)，再由父旋转 90°（顺时针）：(x+1, y) -> (y, -(x+1))
    m.set_param("T", 1.0); m.set_param("R", 1.0); m.update()
    want = [(y, -(x + 1.0)) for x, y in QUAD]
    assert approx(m.vertices(0), want), m.vertices(0)
    print("ok  nested deformers: parent rotation composes")


def test_many_meshes():
    """多部件 / 多参数 / 不同顶点数：验证 counts 与索引体系算得对。"""
    import math

    b = Moc3Builder(1440, 2560, ppu=1440)
    axes = [(f"P{i}", [-1, 1]) for i in range(3)]        # 2^3 = 8 keyforms
    for i in range(3):
        b.add_param(f"P{i}", -1, 1, 0)

    parts = []
    for i in range(8):
        parts.append(b.add_part(f"Part{i}", parent=-1 if i < 2 else parts[0],
                                draw_orders=[i * 100.0]))

    n_verts = 0
    for i in range(24):
        vc = 6 + i % 11                                   # 6..16 顶点
        n_verts += vc
        verts = [(math.cos(2 * math.pi * k / vc) * 0.1,
                  math.sin(2 * math.pi * k / vc) * 0.1) for k in range(vc)]
        # 三角扇：v0 与相邻顶点成三角
        tri = []
        for k in range(1, vc - 1):
            tri += [0, k, k + 1]
        uvs = [0.0] * (vc * 2)
        kfs = [ArtMeshKeyform(verts) for _ in range(8)]
        b.add_artmesh(f"Art{i}", part=parts[i % len(parts)], texture=i % 2,
                      uvs=uvs, indices=tri, axes=axes, keyforms=kfs)

    data = b.build()
    assert CORE.consistency(data) == 1
    m = CORE.load(data)
    assert len(m.part_ids()) == 8
    assert len(m.drawable_ids()) == 24
    for i in range(24):
        assert m.drawable(i)["vertex_count"] == 6 + i % 11
        assert m.drawable(i)["texture"] == i % 2
    orders = [m.drawable(i)["render_order"] for i in range(24)]
    assert orders == sorted(orders) and len(set(orders)) == 24, orders
    print(f"ok  many meshes: 24 artmeshes / {n_verts} verts / 3-param grid")


if __name__ == "__main__":
    test_single_param()
    test_two_params_axis_order()
    test_parts_and_meshes()
    test_rotation_deformer()
    test_warp_deformer()
    test_nested_deformers()
    test_many_meshes()
    print("\nall builder tests passed")
