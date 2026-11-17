# -*- coding: utf-8 -*-
r"""Build the builtin-shader id table from selected characters (offline, one-off)."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_shader_table as B  # noqa: E402
from unity2spine.convert.convert_2dmodel import build_character_model  # noqa: E402


def main(names, out=None):
    idx = B.index_meta(B.ASSETS)
    votes = {}
    for n in names:
        prefab = B.PROJ / "Assets" / "Prefabs" / f"{n}.uAnim.prefab"
        mats_file = B.REF / f"{n}.mats.json"
        if not prefab.exists() or not mats_file.exists():
            print("skip", n)
            continue
        mats = {p["name"]: p["shader"] for p in
                json.loads(mats_file.read_text(encoding="utf-8"))["parts"]}
        try:
            _, parts = build_character_model(str(prefab), str(B.ASSETS))
        except Exception as e:
            print("build fail", n, e)
            continue
        for p in parts:
            if not p.materials:
                continue
            shader = None
            for k, v in mats.items():
                if p.name == k or p.name.startswith(k + "_"):
                    shader = v
                    break
            if not shader:
                continue
            mp = idx.get(p.materials[0])
            if mp is None or not mp.exists():
                continue
            m = B.SHADER_RE.search(mp.read_text(encoding="utf-8", errors="replace"))
            if not m:
                continue
            votes.setdefault((m.group(1), m.group(2)), Counter())[shader] += 1
    table = {f"{k[0]}|{k[1]}": {"shader": c.most_common(1)[0][0], "n": c.most_common(1)[0][1]}
             for k, c in votes.items()}
    out = out or (ROOT / "src" / "unity2live2d" / "convert" / "unity_shader_ids.json")
    Path(out).write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    print("entries", len(table), "->", out)
    for k, v in table.items():
        print(f"  {k:52s} {v['shader']} ({v['n']})")


if __name__ == "__main__":
    main(sys.argv[1:] or ["2DModel_BR_WarWolf_NS1"])
