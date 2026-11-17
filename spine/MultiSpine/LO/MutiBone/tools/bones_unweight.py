# -*- coding: utf-8 -*-
r"""二分用变体：把多骨骼产物里的**加权 mesh 全改成无权**（顶点写进槽位骨的局部空间）。

目的：判"渲染不对"到底是 **骨/动画** 的问题，还是 **加权编码** 的问题。
* 变体渲染正常 ⇒ 骨/动画没问题，问题只在加权 mesh 编码；
* 变体也乱 ⇒ 骨/动画/槽位就有问题。

用法：python _scratch\bones_unweight.py <源产物目录> <目标目录>
"""
import json
import math
import os
import shutil
import sys


def bone_world(bones):
    idx = {b["name"]: i for i, b in enumerate(bones)}
    out = []
    for b in bones:
        rot = math.radians(b.get("rotation", 0))
        sx, sy = b.get("scaleX", 1), b.get("scaleY", 1)
        co, si = math.cos(rot), math.sin(rot)
        a, bb, c, dd = co * sx, -si * sy, si * sx, co * sy
        x, y = b.get("x", 0), b.get("y", 0)
        par = idx.get(b.get("parent")) if b.get("parent") else None
        if par is None:
            out.append([a, bb, c, dd, x, y])
        else:
            pa, pb, pc, pd, px, py = out[par]
            out.append([pa * a + pb * c, pa * bb + pb * dd,
                        pc * a + pd * c, pc * bb + pd * dd,
                        pa * x + pb * y + px, pc * x + pd * y + py])
    return out


def main():
    src, dst = sys.argv[1], sys.argv[2]
    os.makedirs(dst, exist_ok=True)
    for f in os.listdir(src):
        p = os.path.join(src, f)
        if os.path.isfile(p) and (f.endswith((".atlas", ".png", ".config.json"))
                                  or f.startswith(".")):
            shutil.copy2(p, os.path.join(dst, f))
    jp = [f for f in os.listdir(src) if f.endswith("_static.json")][0]
    d = json.load(open(os.path.join(src, jp), encoding="utf-8"))
    W = bone_world(d["bones"])
    idx = {b["name"]: i for i, b in enumerate(d["bones"])}
    slot_bone = {s["name"]: s["bone"] for s in d["slots"]}
    n = 0
    for skin in d["skins"]:
        for slot, mp in (skin.get("attachments") or {}).items():
            for nm, a in mp.items():
                if a.get("type") != "mesh":
                    continue
                v = a["vertices"]
                if len(v) == len(a["uvs"]):
                    continue                     # 已经无权
                bi = idx.get(slot_bone.get(slot, ""), 0)
                A = W[bi]
                out = []
                i = 0
                while i < len(v):
                    bc = int(v[i]); i += 1
                    px = py = 0.0
                    for _ in range(bc):
                        k = int(v[i]); x, y, w = v[i + 1], v[i + 2], v[i + 3]
                        B = W[k]
                        px += w * (B[0] * x + B[1] * y + B[4])
                        py += w * (B[2] * x + B[3] * y + B[5])
                        i += 4
                    # 反解到槽位骨局部
                    det = A[0] * A[3] - A[1] * A[2]
                    dx, dy = px - A[4], py - A[5]
                    lx = (A[3] * dx - A[1] * dy) / det
                    ly = (-A[2] * dx + A[0] * dy) / det
                    out += [round(lx, 4), round(ly, 4)]
                a["vertices"] = out
                a.pop("hull", None)
                n += 1
    json.dump(d, open(os.path.join(dst, jp), "w", encoding="utf-8"),
              ensure_ascii=False)
    print("改成无权的加权 mesh：%d 个 -> %s" % (n, os.path.join(dst, jp)))


if __name__ == "__main__":
    main()
