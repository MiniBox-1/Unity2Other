# -*- coding: utf-8 -*-
r"""Debug: material GUID -> .mat -> shader ref for one character."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
ASSETS = PROJ / "Assets"
REF = ROOT / "Products" / "_unity_ref"
sys.path.insert(0, r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
from unity2spine.convert.convert_2dmodel import build_character_model  # noqa: E402

GUID_RE = re.compile(r"guid:\s*([0-9a-f]{32})")
SHADER_RE = re.compile(r"m_Shader:\s*\{fileID:\s*(-?\d+),\s*guid:\s*([0-9a-f]{32})")


def main(name):
    prefab = PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"
    _, parts = build_character_model(str(prefab), str(ASSETS))
    mats = {p["name"]: p["shader"] for p in
            json.loads((REF / f"{name}.mats.json").read_text(encoding="utf-8"))["parts"]}
    print("parts", len(parts), "mats", len(mats))
    shown = 0
    for p in parts:
        if not p.materials:
            continue
        shader = None
        for k, v in mats.items():
            if p.name == k or p.name.startswith(k + "_"):
                shader = v
                break
        if shown < 8:
            print(f"  {p.name[:30]:30s} mat={p.materials[0][:8]} unity_shader={shader}")
            shown += 1


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_BR_WarWolf_NS1")
