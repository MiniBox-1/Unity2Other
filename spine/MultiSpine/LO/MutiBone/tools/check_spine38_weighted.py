# -*- coding: utf-8 -*-
r"""核对 spine 3.8 **加权 mesh** 的语义：把每个影响点的 `(x,y)` 用**该骨骼的世界矩阵**
还原到骨架空间，看同一顶点的各影响点是否重合。

重合 ⇒ `(x,y)` 是**该骨局部坐标**（我们要照着写）；不重合 ⇒ 另有口径。

用法：python _scratch\check_spine38_weighted.py <3.8 骨架 json>
"""
import json
import math
import sys


def bone_world(skel):
    """返回 [ (a,b,c,d,wx,wy) ]（spine 约定）。"""
    bones = skel["bones"]
    idx = {b["name"]: i for i, b in enumerate(bones)}
    out = []
    for i, b in enumerate(bones):
        rot = math.radians(b.get("rotation", 0))
        sx, sy = b.get("scaleX", 1), b.get("scaleY", 1)
        co, si = math.cos(rot), math.sin(rot)
        a, bb, c, dd = co * sx, -si * sy, si * sx, co * sy
        x, y = b.get("x", 0), b.get("y", 0)
        par = idx.get(b.get("parent")) if b.get("parent") else None
        if par is None:
            out.append((a, bb, c, dd, x, y))
        else:
            pa, pb, pc, pd, px, py = out[par]
            out.append((pa * a + pb * c, pa * bb + pb * dd,
                        pc * a + pd * c, pc * bb + pd * dd,
                        pa * x + pb * y + px, pc * x + pd * y + py))
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    skel = json.load(open(sys.argv[1], encoding="utf-8"))
    W = bone_world(skel)

    def to_world(bi, x, y):
        a, b, c, d, wx, wy = W[bi]
        return (a * x + b * y + wx, c * x + d * y + wy)

    print("%-16s %6s %10s %s" % ("附件", "顶点", "最大不重合", "（px）"))
    for skin in skel.get("skins") or []:
        for slot, mp in (skin.get("attachments") or {}).items():
            for nm, a in mp.items():
                if a.get("type") != "mesh":
                    continue
                v = a["vertices"]
                if len(v) == len(a["uvs"]):
                    continue                       # 无权
                i = n = 0
                worst = 0.0
                while i < len(v):
                    bc = int(v[i])
                    i += 1
                    pts = []
                    for _ in range(bc):
                        bi = int(v[i])
                        pts.append(to_world(bi, v[i + 1], v[i + 2]))
                        i += 4
                    for p in pts[1:]:
                        worst = max(worst, abs(p[0] - pts[0][0]) + abs(p[1] - pts[0][1]))
                    n += 1
                print("%-16s %6d %10.4f" % (nm, n, worst))


if __name__ == "__main__":
    main()
