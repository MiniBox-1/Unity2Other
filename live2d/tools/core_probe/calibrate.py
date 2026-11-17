# -*- coding: utf-8 -*-
"""Calibrate py-moc3 section order against the real Cubism Core.

Ground truth comes from csmGetDrawable*; every py-moc3 section whose length
equals the drawable count is compared against those arrays.
"""
import ctypes
import sys

DLL = r"D:\VB\Convert\Live2d\Cubism\Plugins\Windows\x86_64\Live2DCubismCore.dll"
P = r"D:\VB\Convert\Live2d\Cubism\Samples\Models\Koharu\Koharu.moc3"

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "vendor" / "py-moc3"))
from moc3 import Moc3


def main():
    d = ctypes.WinDLL(DLL)
    d.csmGetSizeofModel.restype = ctypes.c_uint32
    d.csmGetSizeofModel.argtypes = [ctypes.c_void_p]
    d.csmReviveMocInPlace.restype = ctypes.c_void_p
    d.csmReviveMocInPlace.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    d.csmInitializeModelInPlace.restype = ctypes.c_void_p
    d.csmInitializeModelInPlace.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
    # (model, float size[2], float origin[2], float ppu) -- one contiguous buffer!
    d.csmReadCanvasInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    for n in ("csmGetDrawableCount", "csmGetPartCount", "csmGetParameterCount"):
        getattr(d, n).restype = ctypes.c_int
        getattr(d, n).argtypes = [ctypes.c_void_p]
    for n in ("csmGetDrawableVertexCounts", "csmGetDrawableIndexCounts",
              "csmGetDrawableTextureIndices", "csmGetRenderOrders"):
        getattr(d, n).restype = ctypes.POINTER(ctypes.c_int)
        getattr(d, n).argtypes = [ctypes.c_void_p]
    d.csmGetDrawableConstantFlags.restype = ctypes.POINTER(ctypes.c_ubyte)
    d.csmGetDrawableConstantFlags.argtypes = [ctypes.c_void_p]

    raw = open(P, "rb").read()
    buf = ctypes.create_string_buffer(raw, len(raw))
    moc = d.csmReviveMocInPlace(ctypes.cast(buf, ctypes.c_void_p), len(raw))
    mem = ctypes.create_string_buffer(d.csmGetSizeofModel(moc))
    model = d.csmInitializeModelInPlace(moc, ctypes.cast(mem, ctypes.c_void_p), len(mem))

    canvas = (ctypes.c_float * 5)()
    base = ctypes.addressof(canvas)
    d.csmReadCanvasInfo(model, ctypes.c_void_p(base),
                        ctypes.c_void_p(base + 8), ctypes.c_void_p(base + 16))
    print("canvas [w,h,ox,oy,ppu]:", list(canvas))

    dc = d.csmGetDrawableCount(model)
    vc = [d.csmGetDrawableVertexCounts(model)[i] for i in range(dc)]
    ic = [d.csmGetDrawableIndexCounts(model)[i] for i in range(dc)]
    tex = [d.csmGetDrawableTextureIndices(model)[i] for i in range(dc)]
    order = [d.csmGetRenderOrders(model)[i] for i in range(dc)]
    flags = [d.csmGetDrawableConstantFlags(model)[i] for i in range(dc)]

    print("core vc[:6]", vc[:6], "sum", sum(vc))
    print("core idx[:6]", ic[:6], "sum", sum(ic))
    print("core tex[:6]", tex[:6])
    print("core order[:6]", order[:6])
    print("core flags[:6]", flags[:6])

    m = Moc3.from_file(P)
    targets = {"vc": vc, "ic": ic, "tex": tex, "order": order, "flags": flags}
    print("\n-- matching py-moc3 sections against core arrays --")
    for name, arr in m._sections.items():
        if not isinstance(arr, list) or len(arr) != dc:
            continue
        for tn, tv in targets.items():
            if list(arr) == list(tv):
                print(f"  {name:52s} == {tn}")


if __name__ == "__main__":
    main()
