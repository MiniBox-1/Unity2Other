# -*- coding: utf-8 -*-
r"""Dump Puppet2D_GlobalControl serialized visibility flags from a prefab."""
import re
import sys
from pathlib import Path

BLOCK = re.compile(r"^--- !u!(\d+) &(\d+).*?$", re.M)
SCRIPT_RE = re.compile(r"m_Script:\s*\{fileID:\s*-?\d+,\s*guid:\s*([0-9a-f]{32})")


def main(prefab: Path):
    text = prefab.read_text(encoding="utf-8", errors="replace")
    marks = list(BLOCK.finditer(text))
    for i, m in enumerate(marks):
        cls, fid = int(m.group(1)), int(m.group(2))
        if cls != 114:
            continue
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        for key in ("ControlsVisiblity", "BonesVisiblity", "FFD_Visiblity",
                    "ControlsEnabled", "AutoRefresh", "Controls"):
            mm = re.search(rf"^\s*{key}:\s*(\d)", body, re.M)
            if mm:
                print(f"{prefab.name}: {key} = {mm.group(1)}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        main(Path(p))
