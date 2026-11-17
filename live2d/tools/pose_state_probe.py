# -*- coding: utf-8 -*-
r"""For each animator state, evaluate the t=0 pose and measure how assembled it is."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model)
from unity2live2d.convert.pipeline import _guid_index, load_states  # noqa: E402
from unity2live2d.convert.anim_world import make_sampler  # noqa: E402

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")


def spread(parts, world):
    cens = []
    for p in parts:
        v = _skin_mesh(p, p.mesh, world)
        if not v:
            continue
        cens.append((sum(a[0] for a in v) / len(v), sum(a[1] for a in v) / len(v)))
    if not cens:
        return 0.0
    c = np.array(cens)
    return float(np.mean(np.std(c, axis=0)))


def main(name):
    prefab = PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"
    mdl, parts = build_character_model(str(prefab), str(PROJ / "Assets"))
    gi = _guid_index(PROJ / "Assets")
    states = load_states(prefab, gi)
    bind = _world_matrices(mdl, {})
    print(f"{name}: states={[s[0] for s in states]} parts={len(parts)}")
    print(f"  bind pose spread = {spread(parts, bind):.3f}")
    for sname, clip_path, clip in states:
        for t in (0.0, 0.5):
            g = make_sampler(mdl, clip)(t)
            w = {tfid: g(tfid) for tfid in mdl.transforms}
            print(f"  {sname:10s} t={t:.1f} spread = {spread(parts, w):.3f}")


if __name__ == "__main__":
    for n in sys.argv[1:]:
        main(n)
