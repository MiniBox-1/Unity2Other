# -*- coding: utf-8 -*-
"""Feasibility probe: py-moc3 write-back vs Live2D Cubism Core consistency check."""
import ctypes
import os
import sys

DLL = r"D:\VB\Convert\Live2d\Cubism\Plugins\Windows\x86_64\Live2DCubismCore.dll"
SAMPLES = r"D:\VB\Convert\Live2d\Cubism\Samples\Models"

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "vendor" / "py-moc3"))


def load_core():
    d = ctypes.WinDLL(DLL)
    d.csmGetVersion.restype = ctypes.c_uint32
    d.csmGetLatestMocVersion.restype = ctypes.c_uint32
    d.csmGetMocVersion.restype = ctypes.c_uint32
    d.csmGetMocVersion.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    d.csmHasMocConsistency.restype = ctypes.c_int
    d.csmHasMocConsistency.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    return d


def check(d, data):
    buf = ctypes.create_string_buffer(data, len(data))
    ok = d.csmHasMocConsistency(ctypes.cast(buf, ctypes.c_void_p), len(data))
    ver = d.csmGetMocVersion(ctypes.cast(buf, ctypes.c_void_p), len(data))
    return ok, ver


def main():
    d = load_core()
    print("core version:", d.csmGetVersion(), "latest moc:", d.csmGetLatestMocVersion())

    from moc3 import Moc3

    for name in ["Koharu", "Mao", "Natori"]:
        p = os.path.join(SAMPLES, name, name + ".moc3")
        if not os.path.exists(p):
            print("skip", p)
            continue
        raw = open(p, "rb").read()
        ok, ver = check(d, raw)
        print(f"\n{name}: {len(raw)} bytes  consistency={ok} mocVersion={ver}")
        moc = Moc3.from_bytes(raw)
        print(moc.summary())
        out = moc.to_bytes()
        print("  roundtrip identical:", out == raw, "len", len(out))
        ok2, ver2 = check(d, out)
        print("  rewritten consistency:", ok2, "mocVersion:", ver2)


if __name__ == "__main__":
    main()
