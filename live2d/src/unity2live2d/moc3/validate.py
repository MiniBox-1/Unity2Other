# -*- coding: utf-8 -*-
"""用真实 Live2DCubismCore 校验/读回 moc3。

用法：

    core = CubismCore()
    print(core.consistency(data))          # 1 = 通过
    m = core.load(data)                    # 失败返回 None
    print(m.parameter_ids(), m.part_ids())
    m.set_param("ParamAngleX", 1.0)
    print(m.vertices(0))
"""
from __future__ import annotations

import ctypes
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

DEFAULT_DLL = Path(r"D:\VB\Convert\Live2d\Cubism\Plugins\Windows\x86_64\Live2DCubismCore.dll")


class CubismCore:
    def __init__(self, dll: str | Path = DEFAULT_DLL):
        self._dll = ctypes.WinDLL(str(dll))
        d = self._dll
        d.csmGetVersion.restype = ctypes.c_uint32
        d.csmGetLatestMocVersion.restype = ctypes.c_uint32
        d.csmHasMocConsistency.restype = ctypes.c_int
        d.csmHasMocConsistency.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        d.csmGetMocVersion.restype = ctypes.c_uint32
        d.csmGetMocVersion.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        d.csmGetSizeofModel.restype = ctypes.c_uint32
        d.csmGetSizeofModel.argtypes = [ctypes.c_void_p]
        d.csmReviveMocInPlace.restype = ctypes.c_void_p
        d.csmReviveMocInPlace.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        d.csmInitializeModelInPlace.restype = ctypes.c_void_p
        d.csmInitializeModelInPlace.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
        d.csmUpdateModel.argtypes = [ctypes.c_void_p]
        d.csmReadCanvasInfo.argtypes = [ctypes.c_void_p] * 4

        for n in ("csmGetParameterCount", "csmGetPartCount", "csmGetDrawableCount"):
            getattr(d, n).restype = ctypes.c_int
            getattr(d, n).argtypes = [ctypes.c_void_p]
        for n in ("csmGetParameterIds", "csmGetPartIds", "csmGetDrawableIds"):
            getattr(d, n).restype = ctypes.POINTER(ctypes.c_char_p)
            getattr(d, n).argtypes = [ctypes.c_void_p]
        for n in ("csmGetParameterMinimumValues", "csmGetParameterMaximumValues",
                  "csmGetParameterDefaultValues", "csmGetParameterValues"):
            getattr(d, n).restype = ctypes.POINTER(ctypes.c_float)
            getattr(d, n).argtypes = [ctypes.c_void_p]
        for n in ("csmGetParameterKeyCounts",):
            getattr(d, n).restype = ctypes.POINTER(ctypes.c_int)
            getattr(d, n).argtypes = [ctypes.c_void_p]
        d.csmGetParameterKeyValues.restype = ctypes.POINTER(ctypes.POINTER(ctypes.c_float))
        d.csmGetParameterKeyValues.argtypes = [ctypes.c_void_p]

        for n in ("csmGetDrawableVertexCounts", "csmGetDrawableIndexCounts",
                  "csmGetDrawableTextureIndices", "csmGetRenderOrders"):
            getattr(d, n).restype = ctypes.POINTER(ctypes.c_int)
            getattr(d, n).argtypes = [ctypes.c_void_p]
        d.csmGetDrawableVertexPositions.restype = ctypes.POINTER(ctypes.POINTER(ctypes.c_float))
        d.csmGetDrawableVertexPositions.argtypes = [ctypes.c_void_p]
        d.csmGetDrawableVertexUvs.restype = ctypes.POINTER(ctypes.POINTER(ctypes.c_float))
        d.csmGetDrawableVertexUvs.argtypes = [ctypes.c_void_p]
        d.csmGetDrawableIndices.restype = ctypes.POINTER(ctypes.POINTER(ctypes.c_short))
        d.csmGetDrawableIndices.argtypes = [ctypes.c_void_p]

    # -- 基础 -------------------------------------------------------------- #
    @property
    def version(self) -> int:
        return self._dll.csmGetVersion()

    @property
    def latest_moc_version(self) -> int:
        return self._dll.csmGetLatestMocVersion()

    def consistency(self, data: bytes) -> int:
        buf = ctypes.create_string_buffer(data, len(data))
        return self._dll.csmHasMocConsistency(ctypes.cast(buf, ctypes.c_void_p), len(data))

    def load(self, data: bytes) -> Optional["Model"]:
        if not self.consistency(data):
            return None
        buf = ctypes.create_string_buffer(data, len(data))
        moc = self._dll.csmReviveMocInPlace(ctypes.cast(buf, ctypes.c_void_p), len(data))
        if not moc:
            return None
        size = self._dll.csmGetSizeofModel(moc)
        mem = ctypes.create_string_buffer(size)
        model = self._dll.csmInitializeModelInPlace(
            moc, ctypes.cast(mem, ctypes.c_void_p), size)
        if not model:
            return None
        return Model(self._dll, model, buf, mem)


class Model:
    """已加载的模型。必须持有 buf/mem 引用，否则原生内存会被回收。"""

    def __init__(self, dll, ptr, buf, mem):
        self._dll = dll
        self._ptr = ptr
        self._buf = buf
        self._mem = mem
        self._index = {}
        n = dll.csmGetParameterCount(ptr)
        ids = dll.csmGetParameterIds(ptr)
        for i in range(n):
            self._index[ids[i].decode("utf-8")] = i

    # -- 画布 -------------------------------------------------------------- #
    def canvas(self) -> Tuple[float, float, float, float, float]:
        arr = (ctypes.c_float * 5)()
        base = ctypes.addressof(arr)
        self._dll.csmReadCanvasInfo(self._ptr, ctypes.c_void_p(base),
                                    ctypes.c_void_p(base + 8), ctypes.c_void_p(base + 16))
        return tuple(arr)  # w, h, origin_x, origin_y, ppu

    # -- 参数 -------------------------------------------------------------- #
    def parameter_ids(self) -> List[str]:
        n = self._dll.csmGetParameterCount(self._ptr)
        ids = self._dll.csmGetParameterIds(self._ptr)
        return [ids[i].decode("utf-8") for i in range(n)]

    def parameter_range(self, pid: str):
        i = self._index[pid]
        d = self._dll
        return (d.csmGetParameterMinimumValues(self._ptr)[i],
                d.csmGetParameterMaximumValues(self._ptr)[i],
                d.csmGetParameterDefaultValues(self._ptr)[i])

    def parameter_keys(self, pid: str) -> List[float]:
        i = self._index[pid]
        d = self._dll
        kc = d.csmGetParameterKeyCounts(self._ptr)[i]
        kv = d.csmGetParameterKeyValues(self._ptr)[i]
        return [round(kv[k], 4) for k in range(kc)]

    def set_param(self, pid: str, value: float):
        i = self._index[pid]
        self._dll.csmGetParameterValues(self._ptr)[i] = float(value)

    def update(self):
        self._dll.csmUpdateModel(self._ptr)

    # -- 部件 / ArtMesh ----------------------------------------------------- #
    def part_ids(self) -> List[str]:
        n = self._dll.csmGetPartCount(self._ptr)
        ids = self._dll.csmGetPartIds(self._ptr)
        return [ids[i].decode("utf-8") for i in range(n)]

    def drawable_ids(self) -> List[str]:
        n = self._dll.csmGetDrawableCount(self._ptr)
        ids = self._dll.csmGetDrawableIds(self._ptr)
        return [ids[i].decode("utf-8") for i in range(n)]

    def drawable(self, index: int):
        d = self._dll
        return {
            "vertex_count": d.csmGetDrawableVertexCounts(self._ptr)[index],
            "index_count": d.csmGetDrawableIndexCounts(self._ptr)[index],
            "texture": d.csmGetDrawableTextureIndices(self._ptr)[index],
            "render_order": d.csmGetRenderOrders(self._ptr)[index],
        }

    def vertices(self, index: int) -> List[Tuple[float, float]]:
        d = self._dll
        n = d.csmGetDrawableVertexCounts(self._ptr)[index]
        p = d.csmGetDrawableVertexPositions(self._ptr)[index]
        return [(p[k * 2], p[k * 2 + 1]) for k in range(n)]

    def uvs(self, index: int) -> List[Tuple[float, float]]:
        d = self._dll
        n = d.csmGetDrawableVertexCounts(self._ptr)[index]
        p = d.csmGetDrawableVertexUvs(self._ptr)[index]
        return [(p[k * 2], p[k * 2 + 1]) for k in range(n)]

    def indices(self, index: int) -> List[int]:
        d = self._dll
        n = d.csmGetDrawableIndexCounts(self._ptr)[index]
        p = d.csmGetDrawableIndices(self._ptr)[index]
        return [p[k] for k in range(n)]
