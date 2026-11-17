# -*- coding: utf-8 -*-
r"""Debug: why isn't a descendant of an inactive GameObject filtered?"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from unity2live2d.convert.prefab_filter import disabled_transforms  # noqa: E402

BLOCK = re.compile(r"^--- !u!(\d+) &(\d+).*?$", re.M)


def main(prefab: Path, needle: str):
    text = prefab.read_text(encoding="utf-8", errors="replace")
    names, tr_go, tr_parent = {}, {}, {}
    for m in BLOCK.finditer(text):
        cls, fid = int(m.group(1)), int(m.group(2))
        body = text[m.end(): BLOCK.search(text, m.end()).start() if BLOCK.search(text, m.end()) else len(text)]
        if cls == 1:
            nm = re.search(r"m_Name:\s*(.*)", body)
            act = re.search(r"m_IsActive:\s*(\d)", body)
            if nm:
                names[fid] = (nm.group(1).strip(), act.group(1) if act else "?")
        elif cls == 4:
            g = re.search(r"m_GameObject:\s*\{fileID:\s*(-?\d+)\}", body)
            f = re.search(r"m_Father:\s*\{fileID:\s*(-?\d+)\}", body)
            if g:
                tr_go[fid] = int(g.group(1))
            if f:
                tr_parent[fid] = int(f.group(1))

    bad = disabled_transforms(prefab)
    hits = [(tr, names.get(tr_go.get(tr), ("?", "?"))[0]) for tr in tr_go
            if needle in names.get(tr_go.get(tr), ("", ""))[0]]
    for tr, nm in hits:
        chain = []
        cur = tr
        for _ in range(8):
            g = tr_go.get(cur)
            chain.append(f"{names.get(g, ('?','?'))[0]}{names.get(g, ('','?'))[1]}")
            cur = tr_parent.get(cur, 0)
            if not cur:
                break
        print(f"{nm[:40]:40s} tr={tr} in_bad={tr in bad} chain={' < '.join(chain)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "FullBodyIMG")
