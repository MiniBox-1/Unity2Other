# -*- coding: utf-8 -*-
r"""Dump ActorPartsView serialized fields (GameObject lists) from a prefab."""
import re
import sys
from pathlib import Path

BLOCK = re.compile(r"^--- !u!(\d+) &(\d+).*?$", re.M)
SCRIPT_RE = re.compile(r"m_Script:\s*\{fileID:\s*-?\d+,\s*guid:\s*([0-9a-f]{32})")


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


def main(prefab: Path, script_name="ActorPartsView"):
    text = prefab.read_text(encoding="utf-8", errors="replace")
    marks = list(BLOCK.finditer(text))
    go_names = {}
    for i, m in enumerate(marks):
        cls, fid = int(m.group(1)), int(m.group(2))
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        if cls == 1:
            nm = re.search(r"m_Name:\s*(.*)", body)
            if nm:
                go_names[fid] = nm.group(1).strip()

    idx = guid_index(Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old") / "Assets")
    for i, m in enumerate(marks):
        cls, fid = int(m.group(1)), int(m.group(2))
        if cls != 114:
            continue
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        sm = SCRIPT_RE.search(body)
        if not sm:
            continue
        p = idx.get(sm.group(1))
        if not p or p.stem != script_name:
            continue
        print("==", script_name, "at", prefab.name)
        for line in body.splitlines():
            t = line.strip()
            if t.startswith(("isDefaultOn", "_isSwapParts", "_useChangeInfo")):
                print("  ", t)
            elif re.match(r"-\s*\{fileID:\s*-?\d+\}", t):
                gid = int(re.search(r"-?\d+", t).group(0))
                print("    ->", go_names.get(gid, f"?{gid}"))
        # 分组名
        for label in ("_listParts", "_listBg", "_listDialogDeactiveParts",
                      "_listSwapActiveObject", "_listSwapDeactiveObject"):
            m2 = re.search(rf"{label}:\s*\n((?:\s*-\s*\{{fileID:\s*-?\d+\}}\n)+)", body)
            if m2:
                ids = [int(x) for x in re.findall(r"-?\d+", m2.group(1))]
                print(f"  {label}: {len(ids)} -> {[go_names.get(i, i) for i in ids][:8]}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "ActorPartsView")
