# -*- coding: utf-8 -*-
r"""Scan prefabs for render parts that live under control-only groups (source data only)."""
import re
import sys
from pathlib import Path

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
BLOCK = re.compile(r"^--- !u!(\d+) &(\d+).*?$", re.M)
GO, TR = 1, 4
RENDERERS = {212, 137, 23, 33, 114}


def parse(prefab: Path):
    text = prefab.read_text(encoding="utf-8", errors="replace")
    marks = list(BLOCK.finditer(text))
    names = {}
    tr_go = {}
    tr_father = {}
    go_comps = {}
    for i, m in enumerate(marks):
        cls, fid = int(m.group(1)), int(m.group(2))
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        if cls == GO:
            nm = re.search(r"m_Name:\s*(.*)", body)
            names[fid] = nm.group(1).strip() if nm else ""
            comps = re.findall(r"component:\s*\{fileID:\s*(-?\d+)\}", body)
            go_comps[fid] = [int(c) for c in comps]
        elif cls == TR:
            g = re.search(r"m_GameObject:\s*\{fileID:\s*(-?\d+)\}", body)
            f = re.search(r"m_Father:\s*\{fileID:\s*(-?\d+)\}", body)
            if g:
                tr_go[fid] = int(g.group(1))
            if f:
                tr_father[fid] = int(f.group(1))
    return names, tr_go, tr_father, go_comps


def ancestors(tr, tr_father, names, tr_go, limit=12):
    out = []
    cur = tr
    for _ in range(limit):
        par = tr_father.get(cur, 0)
        if not par:
            break
        g = tr_go.get(par)
        out.append(names.get(g, ""))
        cur = par
    return out


def main(names_):
    for n in names_:
        prefab = PROJ / "Assets" / "Prefabs" / f"{n}.uAnim.prefab"
        if not prefab.exists():
            print(n, "no prefab")
            continue
        names, tr_go, tr_father, comps = parse(prefab)
        hits = []
        for tr, go in tr_go.items():
            chain = ancestors(tr, tr_father, names, tr_go)
            if any(a == "Global_CTRL" or a.endswith("_GRP") and "CTRL" in a for a in chain):
                hits.append((names.get(go, ""), chain[:3]))
        print(f"{n}: {len(hits)} parts under control groups")
        for h in hits[:6]:
            print("   ", h[0], "|", " < ".join(h[1]))


if __name__ == "__main__":
    main(sys.argv[1:] or ["2DModel_BR_RoyalArsenal_NS1"])
