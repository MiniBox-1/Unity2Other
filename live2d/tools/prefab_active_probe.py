# -*- coding: utf-8 -*-
r"""Parse prefab YAML: disabled GameObjects/renderers and map to transform fileIDs."""
import re
import sys
from pathlib import Path

BLOCK = re.compile(r"^--- !u!(\d+) &(\d+).*?$", re.M)


def parse(prefab: Path):
    text = prefab.read_text(encoding="utf-8", errors="replace")
    marks = list(BLOCK.finditer(text))
    go_active = {}
    comp_owner = {}
    comp_enabled = {}
    tr_owner = {}
    for i, m in enumerate(marks):
        cls, fid = int(m.group(1)), int(m.group(2))
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        if cls == 1:  # GameObject
            a = re.search(r"m_IsActive:\s*(\d)", body)
            go_active[fid] = (a.group(1) == "1") if a else True
        elif cls == 4:  # Transform
            o = re.search(r"m_GameObject:\s*\{fileID:\s*(\d+)\}", body)
            if o:
                tr_owner[fid] = int(o.group(1))
        elif cls in (212, 137, 23, 33, 114):  # renderers
            o = re.search(r"m_GameObject:\s*\{fileID:\s*(\d+)\}", body)
            e = re.search(r"m_Enabled:\s*(\d)", body)
            if o:
                comp_owner[fid] = int(o.group(1))
                comp_enabled[fid] = (e.group(1) == "1") if e else True
    disabled_go = {go for go, act in go_active.items() if not act}
    for comp, go in comp_owner.items():
        if not comp_enabled.get(comp, True):
            disabled_go.add(go)
    disabled_tr = {tr for tr, go in tr_owner.items() if go in disabled_go}
    return {
        "gameobjects": len(go_active),
        "inactive_go": sum(1 for v in go_active.values() if not v),
        "renderers": len(comp_owner),
        "disabled_renderers": sum(1 for v in comp_enabled.values() if not v),
        "disabled_transforms": len(disabled_tr),
        "ids": disabled_tr,
    }


def main(name):
    PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
    info = parse(PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab")
    print({k: v for k, v in info.items() if k != "ids"})
    sys.path.insert(0, str(Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")))
    from unity2spine.convert.convert_2dmodel import build_character_model
    mdl, parts = build_character_model(
        str(PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"), str(PROJ / "Assets"))
    hit = [p for p in parts if p.tfid in info["ids"]]
    print(f"parts={len(parts)} on disabled transforms={len(hit)}")
    for p in hit[:6]:
        print("   ", p.name, p.kind, p.tfid)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_BR_Khan_N")
