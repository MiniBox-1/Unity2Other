# -*- coding: utf-8 -*-
r"""Resolve material GUID -> shader reference from the project (source data only)."""
import re
import sys
from pathlib import Path

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
ASSETS = PROJ / "Assets"

GUID_RE = re.compile(r"guid:\s*([0-9a-f]{32})")


def index_meta(root: Path):
    out = {}
    for meta in root.rglob("*.meta"):
        try:
            txt = meta.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        m = GUID_RE.search(txt)
        if m:
            out.setdefault(m.group(1), meta.with_suffix(""))
    return out


def main(guids):
    idx = index_meta(ASSETS)
    for g in guids:
        p = idx.get(g)
        if p is None:
            print(g, "NOT FOUND")
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"m_Shader:\s*\{fileID:\s*(-?\d+),\s*guid:\s*([0-9a-f]{32})", txt)
        nm = re.search(r"m_Name:\s*(.*)", txt)
        print(f"{g} -> {p.name:40s} name={nm.group(1).strip() if nm else '?'} "
              f"shader={m.groups() if m else None}")


if __name__ == "__main__":
    main(sys.argv[1:])
