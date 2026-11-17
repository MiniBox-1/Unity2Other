# -*- coding: utf-8 -*-
"""Try to synthesize a minimal moc3 (1 part / 1 art mesh / 1 parameter) from scratch."""
import ctypes
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "vendor" / "py-moc3"))
from moc3 import Moc3
from moc3._core import CountIdx as C

DLL = r"D:\VB\Convert\Live2d\Cubism\Plugins\Windows\x86_64\Live2DCubismCore.dll"


def build():
    m = Moc3()
    m.header.version = 1

    m.canvas.pixels_per_unit = 1000.0
    m.canvas.origin_x = 500.0
    m.canvas.origin_y = 500.0
    m.canvas.canvas_width = 1000.0
    m.canvas.canvas_height = 1000.0
    m.canvas.canvas_flag = 0

    counts = [0] * 23
    counts[C.PARTS] = 1
    counts[C.DEFORMERS] = 0
    counts[C.WARP_DEFORMERS] = 0
    counts[C.ROTATION_DEFORMERS] = 0
    counts[C.ART_MESHES] = 1
    counts[C.PARAMETERS] = 1
    counts[C.PART_KEYFORMS] = 1
    counts[C.WARP_DEFORMER_KEYFORMS] = 0
    counts[C.ROTATION_DEFORMER_KEYFORMS] = 0
    counts[C.ART_MESH_KEYFORMS] = 2
    counts[C.KEYFORM_POSITIONS] = 16   # floats (2 keyforms x 4 verts x 2)
    counts[C.KEYFORM_BINDING_INDICES] = 1
    counts[C.KEYFORM_BINDING_BANDS] = 2
    counts[C.KEYFORM_BINDINGS] = 1
    counts[C.KEYS] = 2
    counts[C.UVS] = 8
    counts[C.POSITION_INDICES] = 6
    counts[C.DRAWABLE_MASKS] = 0
    counts[C.DRAW_ORDER_GROUPS] = 1
    counts[C.DRAW_ORDER_GROUP_OBJECTS] = 1
    counts[C.GLUES] = 0
    counts[C.GLUE_INFOS] = 0
    counts[C.GLUE_KEYFORMS] = 0
    m.counts = counts

    def s(name, data):
        m[name] = data

    # ---- parts ----
    s("part.ids", ["Part0"])
    s("part.keyform_binding_band_indices", [0])
    s("part.keyform_begin_indices", [0])
    s("part.keyform_counts", [1])
    s("part.visibles", [True])
    s("part.enables", [True])
    s("part.parent_part_indices", [-1])

    # ---- art mesh ----
    s("art_mesh.ids", ["Art0"])
    s("art_mesh.keyform_binding_band_indices", [1])
    s("art_mesh.keyform_begin_indices", [0])
    s("art_mesh.keyform_counts", [2])
    s("art_mesh.visibles", [True])
    s("art_mesh.enables", [True])
    s("art_mesh.parent_part_indices", [0])
    s("art_mesh.parent_deformer_indices", [-1])
    s("art_mesh.texture_indices", [0])
    s("art_mesh.drawable_flags", [0])
    # NOTE: py-moc3 labels these two swapped vs. the real file
    s("art_mesh.position_index_counts", [4])   # real meaning: vertex count
    s("art_mesh.uv_begin_indices", [0])
    s("art_mesh.position_index_begin_indices", [0])
    s("art_mesh.vertex_counts", [6])           # real meaning: index count
    s("art_mesh.mask_begin_indices", [0])
    s("art_mesh.mask_counts", [0])

    # ---- parameters ----
    s("parameter.ids", ["ParamAngleX"])
    s("parameter.min_values", [-1.0])
    s("parameter.max_values", [1.0])
    s("parameter.default_values", [0.0])
    s("parameter.repeats", [False])
    s("parameter.decimal_places", [2])
    s("parameter.keyform_binding_begin_indices", [0])
    s("parameter.keyform_binding_counts", [1])

    # ---- keyform bindings ----
    s("part_keyform.draw_orders", [0.0])
    s("art_mesh_keyform.opacities", [1.0, 1.0])
    s("art_mesh_keyform.draw_orders", [0.0, 0.0])
    s("art_mesh_keyform.keyform_position_begin_indices", [0, 8])

    # quad in model space: key 0, then key 1 shifted right by 0.1.
    # NOTE: moc3 stores keyform positions with Y negated (measured, see e5_y_axis.py),
    # so flip Y on the way in; readback then matches model space exactly.
    quad = [-0.25, -0.25, 0.25, -0.25, 0.25, 0.25, -0.25, 0.25]
    key1 = [v + 0.1 if i % 2 == 0 else v for i, v in enumerate(quad)]

    def store(pts):
        return [v if i % 2 == 0 else -v for i, v in enumerate(pts)]

    s("keyform_position.xys", store(quad) + store(key1))

    s("keyform_binding_band.begin_indices", [0, 0])
    s("keyform_binding_band.counts", [0, 1])
    s("keyform_binding.keys_begin_indices", [0])
    s("keyform_binding.keys_counts", [2])
    s("keyform_binding_index.indices", [0])
    s("keys.values", [-1.0, 1.0])

    # ---- uv / indices ----
    s("uv.xys", [0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0])
    s("position_index.indices", [0, 1, 2, 0, 2, 3])

    # ---- draw order group ----
    s("draw_order_group.object_begin_indices", [0])
    s("draw_order_group.object_counts", [1])
    s("draw_order_group.object_total_counts", [1])
    s("draw_order_group.min_draw_orders", [0])
    s("draw_order_group.max_draw_orders", [0])
    s("draw_order_group_object.types", [0])
    s("draw_order_group_object.indices", [0])
    s("draw_order_group_object.group_indices", [-1])

    return m


def check(data):
    d = ctypes.WinDLL(DLL)
    d.csmGetSizeofModel.restype = ctypes.c_uint32
    d.csmGetSizeofModel.argtypes = [ctypes.c_void_p]
    d.csmReviveMocInPlace.restype = ctypes.c_void_p
    d.csmReviveMocInPlace.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    d.csmInitializeModelInPlace.restype = ctypes.c_void_p
    d.csmInitializeModelInPlace.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
    d.csmHasMocConsistency.restype = ctypes.c_int
    d.csmHasMocConsistency.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    d.csmUpdateModel.argtypes = [ctypes.c_void_p]
    d.csmGetDrawableCount.restype = ctypes.c_int
    d.csmGetDrawableCount.argtypes = [ctypes.c_void_p]
    d.csmGetDrawableVertexCounts.restype = ctypes.POINTER(ctypes.c_int)
    d.csmGetDrawableVertexCounts.argtypes = [ctypes.c_void_p]
    d.csmGetDrawableVertexPositions.restype = ctypes.POINTER(ctypes.POINTER(ctypes.c_float))
    d.csmGetDrawableVertexPositions.argtypes = [ctypes.c_void_p]
    d.csmGetParameterCount.restype = ctypes.c_int
    d.csmGetParameterCount.argtypes = [ctypes.c_void_p]
    d.csmGetParameterIds.restype = ctypes.POINTER(ctypes.c_char_p)
    d.csmGetParameterIds.argtypes = [ctypes.c_void_p]
    d.csmGetParameterValues.restype = ctypes.POINTER(ctypes.c_float)
    d.csmGetParameterValues.argtypes = [ctypes.c_void_p]

    buf = ctypes.create_string_buffer(data, len(data))
    ok = d.csmHasMocConsistency(ctypes.cast(buf, ctypes.c_void_p), len(data))
    print("consistency:", ok, "size:", len(data))
    if not ok:
        return
    moc = d.csmReviveMocInPlace(ctypes.cast(buf, ctypes.c_void_p), len(data))
    print("moc:", moc)
    if not moc:
        return
    mem = ctypes.create_string_buffer(d.csmGetSizeofModel(moc))
    model = d.csmInitializeModelInPlace(moc, ctypes.cast(mem, ctypes.c_void_p), len(mem))
    print("model:", model)
    if not model:
        return
    print("params:", d.csmGetParameterCount(model), d.csmGetParameterIds(model)[0])
    d.csmUpdateModel(model)
    dc = d.csmGetDrawableCount(model)
    vc = d.csmGetDrawableVertexCounts(model)
    pos = d.csmGetDrawableVertexPositions(model)
    for i in range(dc):
        print(" drawable", i, "vc", vc[i],
              [(round(pos[i][k * 2], 3), round(pos[i][k * 2 + 1], 3)) for k in range(vc[i])])


if __name__ == "__main__":
    import pathlib

    moc = build()
    data = moc.to_bytes()
    out = pathlib.Path(__file__).with_name("min.moc3")
    out.write_bytes(data)
    print("wrote", out)
    check(data)
