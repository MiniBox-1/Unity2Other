# -*- coding: utf-8 -*-
r"""Measure bind-pose part spread for every character (scattered model detector)."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model)

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
OUT = ROOT / "Products" / "_bind_spread.json"


def main():
    rows = []
    for prefab in sorted((PROJ / "Assets" / "Prefabs").glob("*.uAnim.prefab")):
        name = prefab.stem.replace(".uAnim", "")
        try:
            mdl, parts = build_character_model(str(prefab), str(PROJ / "Assets"))
            w = _world_matrices(mdl, {})
            cens = []
            for p in parts:
                v = _skin_mesh(p, p.mesh, w)
                if not v:
                    continue
                cens.append((sum(a[0] for a in v) / len(v),
                             sum(a[1] for a in v) / len(v)))
            if len(cens) < 2:
                continue
            c = np.array(cens)
            spread = float(np.mean(np.std(c, axis=0)))
            rows.append((spread, name, len(cens)))
        except Exception as e:
            rows.append((-1.0, name + " ERR " + str(e)[:30], 0))
    rows.sort(reverse=True)
    OUT.write_text(__import__("json").dumps(rows, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"models={len(rows)} report={OUT}")
    print("--- 最散的 15 个（bind pose 离散度）---")
    for r in rows[:15]:
        print(f"  {r[0]:.3f} parts={r[2]:3d} {r[1]}")


if __name__ == "__main__":
    main()
