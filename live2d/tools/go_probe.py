# -*- coding: utf-8 -*-
r"""Probe a prefab: for GameObjects matching a name, print active flag and component enabled flags."""
import re
import sys
from pathlib import Path

BLOCK = re.compile(r"^--- !u!(\d+) &(\d+).*?$", re.M)


def main(prefab: Path, needle: str):
    text = prefab.read_text(encoding="utf-8", errors="replace")
    marks = list(BLOCK.finditer(text))
    go_by_name = {}
    comps = {}
    for i, m in enumerate(marks):
        cls, fid = int(m.group(1)), int(m.group(2))
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        if cls == 1:
            nm = re.search(r"m_Name:\s*(.*)", body)
            act = re.search(r"m_IsActive:\s*(\d)", body)
            if nm and needle in nm.group(1):
                go_by_name[fid] = (nm.group(1).strip(), act.group(1) if act else "?")
            comps[fid] = [int(c) for c in re.findall(r"component:\s*\{fileID:\s*(-?\d+)\}", body)]
    inv = {}
    for go, cl in comps.items():
        for c in cl:
            inv[c] = go
    for i, m in enumerate(marks):
        cls, fid = int(m.group(1)), int(m.group(2))
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        if cls in (212, 137, 23, 33, 114) and fid in inv and inv[fid] in go_by_name:
            en = re.search(r"m_Enabled:\s*(\d)", body)
            nm, act = go_by_name[inv[fid]]
            print(f"{nm[:44]:44s} isActive={act} cls={cls} enabled={en.group(1) if en else '?'}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "FullBodyIMG")
