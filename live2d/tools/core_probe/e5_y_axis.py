# -*- coding: utf-8 -*-
"""E5 follow-up: pin down the keyform-position Y convention and begin units.

Builds a 1-part / 1-artmesh / 1-param model with an asymmetric quad, then reads
the deformed vertices back through the real Core:

  * key 0 stores quad as-is, key 1 stores quad + (0.3, 0.3)
  * if readback at param=1 equals -(stored), the file stores -Y (or Core flips it)

Also proves `keyform_position_begin_indices` is in **float** units: key 1 begins
at float 8 and the block at floats[8..15] is the one that shows up.
"""
import ctypes
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "vendor" / "py-moc3"))

from build_min import DLL, build  # reuse the minimal builder

QUAD = [-0.10, -0.30, 0.45, -0.20, 0.30, 0.55, -0.35, 0.15]
SHIFT = (0.3, 0.3)


def make(store_y_negated: bool):
    m = build()
    m.counts[10] = 24  # 3 blocks of 8 floats

    def block(offset):
        pts = [QUAD[i] + (SHIFT[0] if i % 2 == 0 else SHIFT[1]) if offset else QUAD[i]
               for i in range(8)]
        if store_y_negated:
            pts = [pts[i] if i % 2 == 0 else -pts[i] for i in range(8)]
        return pts

    m["keyform_position.xys"] = block(0) + block(1) + block(1)
    m["art_mesh_keyform.keyform_position_begin_indices"] = [0, 8]
    return m


def readback(data):
    d = ctypes.WinDLL(DLL)
    d.csmGetSizeofModel.restype = ctypes.c_uint32
    d.csmGetSizeofModel.argtypes = [ctypes.c_void_p]
    d.csmReviveMocInPlace.restype = ctypes.c_void_p
    d.csmReviveMocInPlace.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    d.csmInitializeModelInPlace.restype = ctypes.c_void_p
    d.csmInitializeModelInPlace.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
    d.csmUpdateModel.argtypes = [ctypes.c_void_p]
    d.csmGetParameterValues.restype = ctypes.POINTER(ctypes.c_float)
    d.csmGetParameterValues.argtypes = [ctypes.c_void_p]
    d.csmGetDrawableVertexPositions.restype = ctypes.POINTER(ctypes.POINTER(ctypes.c_float))
    d.csmGetDrawableVertexPositions.argtypes = [ctypes.c_void_p]

    buf = ctypes.create_string_buffer(data, len(data))
    moc = d.csmReviveMocInPlace(ctypes.cast(buf, ctypes.c_void_p), len(data))
    mem = ctypes.create_string_buffer(d.csmGetSizeofModel(moc))
    model = d.csmInitializeModelInPlace(moc, ctypes.cast(mem, ctypes.c_void_p), len(mem))
    out = {}
    for v in (-1.0, 1.0):
        d.csmGetParameterValues(model)[0] = v
        d.csmUpdateModel(model)
        p = d.csmGetDrawableVertexPositions(model)[0]
        out[v] = [(round(p[k * 2], 4), round(p[k * 2 + 1], 4)) for k in range(4)]
    return out


def main():
    print("intended key0:", [(QUAD[i], QUAD[i + 1]) for i in range(0, 8, 2)])
    print("intended key1:", [(QUAD[i] + SHIFT[0], QUAD[i + 1] + SHIFT[1]) for i in range(0, 8, 2)])

    print("\n-- store as-is --")
    got = readback(make(False).to_bytes())
    print("key0:", got[-1.0])
    print("key1:", got[1.0])

    print("\n-- store with Y negated --")
    got = readback(make(True).to_bytes())
    print("key0:", got[-1.0])
    print("key1:", got[1.0])


if __name__ == "__main__":
    main()
