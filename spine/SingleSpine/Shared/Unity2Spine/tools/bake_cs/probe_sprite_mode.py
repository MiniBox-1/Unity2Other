# -*- coding: utf-8 -*-
r"""看 prefab 里某个 SpriteRenderer 的绘制模式/尺寸/翻转（判断"精灵顶点取法"是否
够用：Simple 用 sprite.vertices 就够，Sliced/Tiled 必须按 m_Size 重新生成网格）。

用法:
    python probe_sprite_mode.py --prefab <prefab> --name parts_arm_R_shadow [...]
"""

import argparse
import io
import re
import sys


def split_docs(text):
    docs = []
    cur = None
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


def field(lines, key):
    for ln in lines:
        m = re.match(r"^\s+%s:\s*(.*)$" % re.escape(key), ln)
        if m:
            return m.group(1).strip()
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefab", required=True)
    ap.add_argument("--name", action="append", required=True)
    a = ap.parse_args()
    text = io.open(a.prefab, encoding="utf-8", errors="replace").read()
    docs = split_docs(text)
    # GameObject 名字 -> fileID
    gos = {}
    for cid, fid, lines in docs:
        if cid == 1:
            nm = field(lines, "m_Name")
            if nm:
                gos.setdefault(nm, fid)
    srs = {}
    for cid, fid, lines in docs:
        if cid == 212:                      # SpriteRenderer
            go = field(lines, "m_GameObject") or ""
            m = re.search(r"fileID:\s*(-?\d+)", go)
            if m:
                srs[m.group(1)] = lines
    for nm in a.name:
        fid = gos.get(nm)
        if not fid:
            print("%-32s 找不到 GameObject" % nm)
            continue
        L = srs.get(fid)
        if not L:
            print("%-32s 没有 SpriteRenderer" % nm)
            continue
        print("%-32s drawMode=%s size=%s flip=%s,%s enabled=%s sprite=%s"
              % (nm, field(L, "m_DrawMode"), field(L, "m_Size"),
                 field(L, "m_FlipX"), field(L, "m_FlipY"),
                 field(L, "m_Enabled"),
                 (field(L, "m_Sprite") or "")[:40]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
