# -*- coding: utf-8 -*-
"""Read a moc3 through the real Cubism Core and dump structure."""
import ctypes
import os
import sys

DLL = r"D:\VB\Convert\Live2d\Cubism\Plugins\Windows\x86_64\Live2DCubismCore.dll"
P = r"D:\VB\Convert\Live2d\Cubism\Samples\Models\Koharu\Koharu.moc3"


def bind(d):
    d.csmGetSizeofModel.restype = ctypes.c_uint32
    d.csmGetSizeofModel.argtypes = [ctypes.c_void_p]
    d.csmReviveMocInPlace.restype = ctypes.c_void_p
    d.csmReviveMocInPlace.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    d.csmInitializeModelInPlace.restype = ctypes.c_void_p
    d.csmInitializeModelInPlace.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
    d.csmUpdateModel.argtypes = [ctypes.c_void_p]
    d.csmReadCanvasInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]

    d.csmGetParameterCount.restype = ctypes.c_int
    d.csmGetParameterCount.argtypes = [ctypes.c_void_p]
    d.csmGetParameterIds.restype = ctypes.POINTER(ctypes.c_char_p)
    d.csmGetParameterIds.argtypes = [ctypes.c_void_p]
    d.csmGetParameterMinimumValues.restype = ctypes.POINTER(ctypes.c_float)
    d.csmGetParameterMinimumValues.argtypes = [ctypes.c_void_p]
    d.csmGetParameterMaximumValues.restype = ctypes.POINTER(ctypes.c_float)
    d.csmGetParameterMaximumValues.argtypes = [ctypes.c_void_p]
    d.csmGetParameterDefaultValues.restype = ctypes.POINTER(ctypes.c_float)
    d.csmGetParameterDefaultValues.argtypes = [ctypes.c_void_p]
    d.csmGetParameterValues.restype = ctypes.POINTER(ctypes.c_float)
    d.csmGetParameterValues.argtypes = [ctypes.c_void_p]
    d.csmGetParameterKeyCounts.restype = ctypes.POINTER(ctypes.c_int)
    d.csmGetParameterKeyCounts.argtypes = [ctypes.c_void_p]
    d.csmGetParameterKeyValues.restype = ctypes.POINTER(ctypes.POINTER(ctypes.c_float))
    d.csmGetParameterKeyValues.argtypes = [ctypes.c_void_p]

    d.csmGetPartCount.restype = ctypes.c_int
    d.csmGetPartCount.argtypes = [ctypes.c_void_p]
    d.csmGetPartIds.restype = ctypes.POINTER(ctypes.c_char_p)
    d.csmGetPartIds.argtypes = [ctypes.c_void_p]

    d.csmGetDrawableCount.restype = ctypes.c_int
    d.csmGetDrawableCount.argtypes = [ctypes.c_void_p]
    d.csmGetDrawableIds.restype = ctypes.POINTER(ctypes.c_char_p)
    d.csmGetDrawableIds.argtypes = [ctypes.c_void_p]
    d.csmGetDrawableVertexCounts.restype = ctypes.POINTER(ctypes.c_int)
    d.csmGetDrawableVertexCounts.argtypes = [ctypes.c_void_p]
    d.csmGetDrawableVertexPositions.restype = ctypes.POINTER(ctypes.POINTER(ctypes.c_float))
    d.csmGetDrawableVertexPositions.argtypes = [ctypes.c_void_p]
    d.csmGetDrawableVertexUvs.restype = ctypes.POINTER(ctypes.POINTER(ctypes.c_float))
    d.csmGetDrawableVertexUvs.argtypes = [ctypes.c_void_p]
    d.csmGetRenderOrders.restype = ctypes.POINTER(ctypes.c_int)
    d.csmGetRenderOrders.argtypes = [ctypes.c_void_p]
    d.csmGetDrawableTextureIndices.restype = ctypes.POINTER(ctypes.c_int)
    d.csmGetDrawableTextureIndices.argtypes = [ctypes.c_void_p]
    d.csmGetDrawableIndexCounts.restype = ctypes.POINTER(ctypes.c_int)
    d.csmGetDrawableIndexCounts.argtypes = [ctypes.c_void_p]
    return d


def main():
    d = bind(ctypes.WinDLL(DLL))
    raw = open(P, "rb").read()
    buf = ctypes.create_string_buffer(raw, len(raw))
    moc = d.csmReviveMocInPlace(ctypes.cast(buf, ctypes.c_void_p), len(raw))
    print("moc ptr:", moc, "size of model:", d.csmGetSizeofModel(moc))
    mem = ctypes.create_string_buffer(d.csmGetSizeofModel(moc))
    model = d.csmInitializeModelInPlace(moc, ctypes.cast(mem, ctypes.c_void_p), len(mem))
    print("model ptr:", model)

    w, h, ppu = ctypes.c_float(), ctypes.c_float(), ctypes.c_float()
    d.csmReadCanvasInfo(model, ctypes.byref(w), ctypes.byref(h), ctypes.byref(ppu))
    print("canvas:", w.value, h.value, "ppu:", ppu.value)

    pc = d.csmGetParameterCount(model)
    pids = d.csmGetParameterIds(model)
    pmins = d.csmGetParameterMinimumValues(model)
    pmax = d.csmGetParameterMaximumValues(model)
    pdef = d.csmGetParameterDefaultValues(model)
    pvals = d.csmGetParameterValues(model)
    kc = d.csmGetParameterKeyCounts(model)
    kv = d.csmGetParameterKeyValues(model)
    print("params:", pc)
    for i in range(3):
        keys = [round(kv[i][k], 2) for k in range(kc[i])]
        print(" ", pids[i].decode(), pmins[i], pmax[i], "default", pdef[i], "keys", kc[i], keys)

    print("parts:", d.csmGetPartCount(model), [d.csmGetPartIds(model)[i].decode() for i in range(3)])

    dc = d.csmGetDrawableCount(model)
    ids = d.csmGetDrawableIds(model)
    vcs = d.csmGetDrawableVertexCounts(model)
    tids = d.csmGetDrawableTextureIndices(model)
    orders = d.csmGetRenderOrders(model)
    ics = d.csmGetDrawableIndexCounts(model)
    print("drawables:", dc, "total verts:", sum(vcs[i] for i in range(dc)))
    for i in range(3):
        print(" ", ids[i].decode(), "vc", vcs[i], "idx", ics[i], "tex", tids[i], "order", orders[i])

    d.csmUpdateModel(model)
    pos = d.csmGetDrawableVertexPositions(model)
    uv = d.csmGetDrawableVertexUvs(model)
    i0 = 0
    n = min(4, vcs[i0])
    print("first drawable verts:", [(round(pos[i0][k * 2], 3), round(pos[i0][k * 2 + 1], 3)) for k in range(n)])
    print("first drawable uvs:", [(round(uv[i0][k * 2], 3), round(uv[i0][k * 2 + 1], 3)) for k in range(n)])

    # bbox over all draws
    mnx = mny = 1e9
    mxx = mxy = -1e9
    for i in range(dc):
        for k in range(vcs[i]):
            x, y = pos[i][k * 2], pos[i][k * 2 + 1]
            mnx = min(mnx, x); mxx = max(mxx, x)
            mny = min(mny, y); mxy = max(mxy, y)
    print("all vertex bbox:", round(mnx, 2), round(mxx, 2), round(mny, 2), round(mxy, 2))


if __name__ == "__main__":
    main()
