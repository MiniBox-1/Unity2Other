# -*- coding: utf-8 -*-
r"""List MonoBehaviour scripts (guid -> .cs) referenced by a prefab, with counts."""
import re
import sys
from collections import Counter
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


def main(prefab: Path):
    text = prefab.read_text(encoding="utf-8", errors="replace")
    idx = guid_index(PROJ / "Assets")
    cnt = Counter()
    for m in re.finditer(r"m_Script:\s*\{fileID:\s*(-?\d+),\s*guid:\s*([0-9a-f]{32})", text):
        p = idx.get(m.group(2))
        cnt[p.name if p else "?" + m.group(2)[:6]] += 1
    print(f"{prefab.name}: {sum(cnt.values())} MonoBehaviour(s)")
    for k, v in cnt.most_common():
        print(f"  {v:3d}  {k}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
