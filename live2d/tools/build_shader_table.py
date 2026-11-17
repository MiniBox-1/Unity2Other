# -*- coding: utf-8 -*-
r"""Learn builtin shader fileID -> shader name table from existing Unity dumps.

This produces a CONSTANT table (Unity builtin shader ids are global), which the
converter can then use with only source assets (material .mat files), without
needing any per-character Unity reference.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
ASSETS = PROJ / "Assets"
REF = ROOT / "Products" / "_unity_ref"
OUT = ROOT / "src" / "unity2live2d" / "convert" / "unity_shader_ids.json"

sys.path.insert(0, r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
from unity2spine.convert.convert_2dmodel import build_character_model  # noqa: E402

GUID_RE = re.compile(r"guid:\s*([0-9a-f]{32})")
SHADER_RE = re.compile(r"m_Shader:\s*\{fileID:\s*(-?\d+),\s*guid:\s*([0-9a-f]{32})")


def index_meta(root: Path):
    out = {}
    for meta in root.rglob("*.meta"):
        try:
            txt = meta.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        m = GUID_RE.search(txt)
        if m:
            out.setdefault(m.group(1), meta.with_name(meta.name[:-5]))
    return out


def main(limit=40):
    idx = index_meta(ASSETS)
    votes = {}
    names = sorted(p.name for p in (ROOT / "Products").iterdir()
                   if p.is_dir() and (p / f"{p.name}.mats.json").exists())
    for n in names[:limit]:
        prefab = PROJ / "Assets" / "Prefabs" / f"{n}.uAnim.prefab"
        if not prefab.exists():
            continue
        mats = {p["name"]: p["shader"] for p in
                json.loads((REF / f"{n}.mats.json").read_text(encoding="utf-8"))["parts"]}
        try:
            _, parts = build_character_model(str(prefab), str(ASSETS))
        except Exception:
            continue
        for p in parts:
            shader = None
            for key, val in mats.items():
                if p.name == key or p.name.startswith(key + "_"):
                    shader = val
                    break
            if not shader or not p.materials:
                continue
            mat_path = idx.get(p.materials[0])
            if mat_path is None or not mat_path.exists():
                continue
            m = SHADER_RE.search(mat_path.read_text(encoding="utf-8", errors="replace"))
            if not m:
                continue
            key = (m.group(1), m.group(2))
            votes.setdefault(key, Counter())[shader] += 1
    table = {}
    for key, c in votes.items():
        name, cnt = c.most_common(1)[0]
        table[f"{key[0]}|{key[1]}"] = {"shader": name, "n": cnt}
    OUT.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    print("entries", len(table))
    for k, v in list(table.items())[:12]:
        print(f"  {k:50s} -> {v['shader']} ({v['n']})")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
