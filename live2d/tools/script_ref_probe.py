# -*- coding: utf-8 -*-
r"""For a prefab GameObject (by name), list its MonoBehaviour scripts (guid -> .cs path)."""
import re
import sys
from pathlib import Path

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
BLOCK = re.compile(r"^--- !u!(\d+) &(\d+).*?$", re.M)


def guid_index(root: Path):
    out = {}
    for meta in root.rglob("*.meta"):
        try:
            txt = meta.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        m = re.search(r"guid:\s*([0-9a-f]{32})", txt)
        if m:
            out.setdefault(m.group(1), meta.with_name(meta.name[:-5]))
    return out


def main(prefab: Path, needle: str):
    text = prefab.read_text(encoding="utf-8", errors="replace")
    marks = list(BLOCK.finditer(text))
    blocks = {}
    go_names = {}
    for i, m in enumerate(marks):
        cls, fid = int(m.group(1)), int(m.group(2))
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        blocks[fid] = (cls, body)
        if cls == 1:
            nm = re.search(r"m_Name:\s*(.*)", body)
            if nm:
                go_names[fid] = nm.group(1).strip()

    idx = guid_index(PROJ / "Assets")
    for go, name in go_names.items():
        if needle not in name:
            continue
        cls, body = blocks[go]
        comps = [int(c) for c in re.findall(r"component:\s*\{fileID:\s*(-?\d+)\}", body)]
        print(f"GO {name} ({go})")
        for c in comps:
            if c not in blocks:
                continue
            ccls, cbody = blocks[c]
            if ccls != 114:
                continue
            m = re.search(r"m_Script:\s*\{fileID:\s*(-?\d+),\s*guid:\s*([0-9a-f]{32})", cbody)
            if m:
                p = idx.get(m.group(2))
                print(f"   script guid={m.group(2)[:8]} -> {p.name if p else '?'} "
                      f"({p.parent.name if p and p.parent else ''})")
                for kv in re.findall(r"^\s+(\w+):\s*(\S+)$", cbody, re.M)[:6]:
                    print(f"      {kv[0]} = {kv[1]}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "FullBodyIMG")
