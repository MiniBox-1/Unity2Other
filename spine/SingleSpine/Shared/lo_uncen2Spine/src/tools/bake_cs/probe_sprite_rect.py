# -*- coding: utf-8 -*-
r"""查某个 SpriteRenderer 用的 Sprite 资源：textureRect / rect / offset / pivot /
mesh 的 UV 范围 —— 用于定位"附件采样到图集错误位置"（UV 取错）。

用法:
    python probe_sprite_rect.py --prefab <prefab> --assets <Assets> --name parts_Tail_Shadow [...]
"""

import argparse
import io
import os
import re
import sys


def split_docs(text):
    docs, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^--- !u!(\d+) &(\d+)(?: stripped)?\s*$", line)
        if m:
            if cur:
                docs.append(cur)
            cur = [int(m.group(1)), m.group(2), []]
            continue
        if cur is not None:
            cur[2].append(line)
    if cur:
        docs.append(cur)
    return docs


def field(lines, key, indent=None):
    pat = (r"^\s{%d}%s:\s*(.*)$" % (indent, re.escape(key))) if indent \
        else (r"^\s+%s:\s*(.*)$" % re.escape(key))
    for ln in lines:
        m = re.match(pat, ln)
        if m:
            return m.group(1).strip()
    return None


def guid_map(assets):
    out = {}
    for root, _dirs, files in os.walk(assets):
        for fn in files:
            if not fn.endswith(".meta"):
                continue
            p = os.path.join(root, fn)
            try:
                txt = io.open(p, encoding="utf-8", errors="replace").read(400)
            except OSError:
                continue
            m = re.search(r"guid:\s*([0-9a-fA-F]{32})", txt)
            if m:
                out[m.group(1)] = p[:-len(".meta")]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefab", required=True)
    ap.add_argument("--assets", required=True)
    ap.add_argument("--name", action="append", required=True)
    a = ap.parse_args()

    g2p = guid_map(a.assets)
    docs = split_docs(io.open(a.prefab, encoding="utf-8", errors="replace").read())
    go_by_name = {}
    for cid, fid, lines in docs:
        if cid == 1:
            nm = field(lines, "m_Name")
            if nm:
                go_by_name.setdefault(nm, fid)
    sr_by_go = {}
    for cid, fid, lines in docs:
        if cid == 212:
            go = field(lines, "m_GameObject") or ""
            m = re.search(r"fileID:\s*(-?\d+)", go)
            if m:
                sr_by_go[m.group(1)] = lines

    for nm in a.name:
        fid = go_by_name.get(nm)
        L = sr_by_go.get(fid or "")
        print("=== %s" % nm)
        if not L:
            print("    没有 SpriteRenderer")
            continue
        sp = field(L, "m_Sprite") or ""
        gu = re.search(r"guid:\s*([0-9a-fA-F]{32})", sp)
        print("    m_FlipX=%s  m_Size=%s  m_DrawMode=%s"
              % (field(L, "m_FlipX"), field(L, "m_Size"), field(L, "m_DrawMode")))
        if not gu:
            print("    m_Sprite 是内建/空")
            continue
        path = g2p.get(gu.group(1))
        print("    Sprite 资源: %s" % path)
        if not path:
            continue
        d2 = split_docs(io.open(path, encoding="utf-8", errors="replace").read())
        for cid, fid2, lines in d2:
            if cid != 213:            # Sprite
                continue
            rd = field(lines, "m_RD")
            print("    m_Rect=%s" % field(lines, "m_Rect"))
            print("    m_Offset=%s  m_Pivot=%s  m_PixelsToUnits=%s  m_Extrude=%s"
                  % (field(lines, "m_Offset"), field(lines, "m_Pivot"),
                     field(lines, "m_PixelsToUnits"), field(lines, "m_Extrude")))
            for k in ("textureRect", "textureRectOffset", "settingsRaw",
                      "downscaleMultiplier"):
                v = field(lines, k)
                if v is not None:
                    print("    m_RD.%s=%s" % (k, v))
            # mesh UV0
            txt = "\n".join(lines)
            muv = re.search(r"m_UV0:\s*data:\s*\n((?:\s+-\s*[-\d.eE]+\n)+)", txt)
            if muv:
                vals = [float(x) for x in re.findall(r"-\s*([-\d.eE]+)", muv.group(1))]
                if vals:
                    us = vals[0::2]
                    vs = vals[1::2]
                    print("    mesh UV0: %d 个   u=[%.4f,%.4f] v=[%.4f,%.4f]"
                          % (len(vals) // 2, min(us), max(us), min(vs), max(vs)))
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
