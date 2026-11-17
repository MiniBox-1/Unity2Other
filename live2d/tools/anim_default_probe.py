# -*- coding: utf-8 -*-
r"""Find the AnimatorController's default state and its clip for a prefab."""
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


def main(name: str):
    prefab = PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"
    text = prefab.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"m_Controller:\s*\{fileID:\s*(-?\d+),\s*guid:\s*([0-9a-f]{32})", text)
    if not m:
        print("no controller")
        return
    ctrl = guid_index(PROJ / "Assets").get(m.group(2))
    print("controller:", ctrl)
    if ctrl is None or not ctrl.exists():
        return
    ctext = ctrl.read_text(encoding="utf-8", errors="replace")
    d = re.search(r"m_DefaultState:\s*\{fileID:\s*(-?\d+)\}", ctext)
    print("m_DefaultState fileID:", d.group(1) if d else None)
    if d:
        # 找到该 state 块
        for mm in BLOCK.finditer(ctext):
            if mm.group(2) == d.group(1):
                body = ctext[mm.end(): BLOCK.search(ctext, mm.end()).start()
                          if BLOCK.search(ctext, mm.end()) else len(ctext)]
                nm = re.search(r"m_Name:\s*(.*)", body)
                clip = re.search(r"m_Motion:\s*\{fileID:\s*(-?\d+),\s*guid:\s*([0-9a-f]{32})", body)
                print("default state:", nm.group(1).strip() if nm else "?")
                if clip:
                    p = guid_index(PROJ / "Assets").get(clip.group(2))
                    print("  clip:", p)
                break


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_3P_Alice_NS1_DL_N")
