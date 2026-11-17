# -*- coding: utf-8 -*-
r"""查 SpriteRenderer 用的**材质/着色器/颜色**（判断影子的"乘法/暗化"是不是靠 shader，
而转换器只按普通 alpha 混合导出 ⇒ 变成浅粉）。

用法:
    python probe_sprite_mat.py --prefab <prefab> --assets <Assets> --name parts_Leg_L_Up_Shadow [...]
"""

import argparse
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from probe_sprite_rect import field, guid_map, split_docs  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefab", required=True)
    ap.add_argument("--assets", required=True)
    ap.add_argument("--name", action="append", required=True)
    a = ap.parse_args()
    g2p = guid_map(a.assets)
    docs = split_docs(io.open(a.prefab, encoding="utf-8", errors="replace").read())
    go = {}
    for cid, fid, L in docs:
        if cid == 1 and field(L, "m_Name"):
            go.setdefault(field(L, "m_Name"), fid)
    sr = {}
    for cid, fid, L in docs:
        if cid == 212:
            m = re.search(r"fileID:\s*(-?\d+)", field(L, "m_GameObject") or "")
            if m:
                sr[m.group(1)] = L
    for nm in a.name:
        L = sr.get(go.get(nm) or "")
        print("=== %s" % nm)
        if not L:
            print("    没有 SpriteRenderer")
            continue
        block = "\n".join(L)
        mats = re.findall(r"guid:\s*([0-9a-fA-F]{32})", block)
        mp = g2p.get(mats[0]) if mats else None
        print("    材质: %s" % mp)
        if not mp:
            continue
        txt = io.open(mp, encoding="utf-8", errors="replace").read()
        sh = re.search(r"m_Shader:\s*\{fileID:\s*(-?\d+),\s*guid:\s*([0-9a-fA-F]{32})", txt)
        print("    shader guid=%s -> %s%s" % (sh.group(2) if sh else "?",
                                             g2p.get(sh.group(2)) if sh else "?",
                                             "" if sh and sh.group(1) == "4800000" else
                                             "  (内建 fileID=%s)" % (sh.group(1) if sh else "?")))
        sp = g2p.get(sh.group(2)) if sh else None
        if sp and os.path.isfile(sp):
            st = io.open(sp, encoding="utf-8", errors="replace").read()
            nm2 = re.search(r"m_Name:\s*(.*)", st)
            print("        shader 资源名: %s" % (nm2.group(1).strip() if nm2 else "?"))
            print("        关键字/混合:", re.findall(r"(Blend[^\n]*)", st)[:4],
                  re.findall(r"ZWrite[^\n]*", st)[:2])
        for key in ("_Color", "_TintColor", "_MulColor", "_Alpha"):
            m = re.search(r"%s:\s*(\{[^}]*\})" % key, txt)
            if m:
                print("        材质 %s = %s" % (key, m.group(1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
