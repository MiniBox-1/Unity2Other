# -*- coding: utf-8 -*-
r"""Build a character with no bone deformers (all parts on root) for comparison."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _world_matrices, build_character_model)
from unity2live2d.convert.pipeline import rigid_parts, _canvas_bounds  # noqa: E402
from unity2live2d.convert.rigged_model import build_rigged  # noqa: E402
from unity2live2d.convert.static_model import write_package  # noqa: E402

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")


def main(name):
    prefab = PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"
    mdl, parts = build_character_model(str(prefab), str(PROJ / "Assets"))
    world = _world_matrices(mdl, {})
    tex_of = {}
    for i, p in enumerate(parts):
        tex_of.setdefault(str(p.texture_path), i)
    rp = rigid_parts(parts, mdl, {}, world, tex_of)
    bounds = _canvas_bounds(rp)
    res = build_rigged(rp, mdl, bones={}, ppu=1000.0, margin=0.05, bounds=bounds)
    out = ROOT / "Products" / f"_flat_{name}"
    write_package(res, name, out)
    print("built", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_AGS_RheinRitter_NS1")
