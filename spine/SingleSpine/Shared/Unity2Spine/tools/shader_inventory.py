# -*- coding: utf-8 -*-
r"""清点工程里所有材质引用的 **shader**（内建 fileID / 自定义 guid → shader 名）。

用法:
    python tools\shader_inventory.py [--assets <Unity 工程 Assets>] [--max-names 6]

输出每条：shader 标识 → 材质数 → 材质名样例，以及"转换器当前怎么处理它"。
"""
import argparse
import collections
import io
import os
import re

ASSETS = r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Assets"

# 转换器目前认得的特殊 shader（内建 fileID）
KNOWN = {200: "Legacy Shaders/Particles/Additive → additive",
         205: "Legacy Shaders/Particles/Multiply → multiply",
         10753: "Sprites/Default → normal",
         10754: "Sprites-Default(材质) → normal",
         10750: "Sprites/Diffuse → normal",
         10751: "Sprites/Mask → normal",
         10752: "Sprites/Default(premultiply) → normal",
         104: "Legacy Shaders/Transparent/VertexLit → normal",
         103: "Legacy Shaders/Transparent/Diffuse → normal"}


def read_meta_guid(path):
    try:
        t = io.open(path, encoding="utf-8", errors="replace").read(400)
    except OSError:
        return None
    m = re.search(r"^guid:\s*([0-9a-f]{32})", t, re.M)
    return m.group(1) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=ASSETS)
    ap.add_argument("--max-names", type=int, default=6)
    a = ap.parse_args()
    root = a.assets

    # 1) 先建 shader guid -> 名字
    shader_name = {}
    for dirpath, _dn, fns in os.walk(root):
        for fn in fns:
            if not fn.endswith(".shader"):
                continue
            p = os.path.join(dirpath, fn)
            g = read_meta_guid(p + ".meta")
            if not g:
                continue
            try:
                txt = io.open(p, encoding="utf-8", errors="replace").read(3000)
            except OSError:
                continue
            m = re.search(r'Shader\s+"([^"]+)"', txt)
            shader_name[g] = m.group(1) if m else os.path.splitext(fn)[0]

    # 2) 扫所有 .mat
    mats = collections.defaultdict(list)
    n_mat = 0
    for dirpath, _dn, fns in os.walk(root):
        for fn in fns:
            if not fn.endswith(".mat"):
                continue
            n_mat += 1
            p = os.path.join(dirpath, fn)
            try:
                txt = io.open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            m = re.search(r"m_Shader:\s*\{fileID:\s*(\d+),\s*guid:\s*([0-9a-f]+)",
                          txt)
            if not m:
                mats[("?", "无 m_Shader")].append(fn)
                continue
            fid, g = int(m.group(1)), m.group(2)
            if g.startswith("0000000000000000"):
                key = ("builtin", fid)
            else:
                key = ("custom", "%s (%s)" % (g, shader_name.get(g, "名字未知")))
            mats[key].append(fn)

    print("Unity 工程: %s" % root)
    print("材质 .mat 总数: %d；其中被用到的 shader 种类: %d\n" % (n_mat, len(mats)))
    rows = sorted(mats.items(), key=lambda kv: -len(kv[1]))
    for (kind, tag), names in rows:
        if kind == "builtin":
            desc = KNOWN.get(tag, "**未登记的内建 shader**")
            label = "内建 fileID %-6d  %s" % (tag, desc)
        else:
            label = "自定义 %s" % tag
        sample = "、".join(sorted(set(names))[:a.max_names])
        print("  %-58s 材质 %3d 个   例: %s" % (label, len(names), sample))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
