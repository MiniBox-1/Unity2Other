# -*- coding: utf-8 -*-
r"""Check whether parts are hidden at t=0 via scale≈0, and measure effect of dropping."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model)
from unity2live2d.convert.anim_world import make_sampler, rest_dict  # noqa: E402
from unity2live2d.convert.pipeline import _guid_index, load_states  # noqa: E402
from unity2spine.unity import unity_anim2d as ua  # noqa: E402

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")


def main(name):
    prefab = PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"
    mdl, parts = build_character_model(str(prefab), str(PROJ / "Assets"))
    states = load_states(prefab, _guid_index(PROJ / "Assets"))
    clip = states[0][2]
    sampler = ua.AnimSampler(clip, rest_dict(mdl))
    w = _world_matrices(mdl, {})

    hidden, sizes = [], []
    for p in parts:
        tr = mdl.transforms.get(p.tfid, {})
        ap = tr.get("anim_path")
        s = (1.0, 1.0, 1.0)
        if ap:
            r = sampler.sample(ap, 0.0)
            s = r["scale"]
        mag = max(abs(s[0]), abs(s[1]))
        v = _skin_mesh(p, p.mesh, w)
        if not v:
            continue
        sizes.append((p.name, mag, len(v)))
        if mag < 0.05:
            hidden.append((p.name, mag))

    print(f"{name}: parts={len(sizes)}  hidden(scale<0.05)={len(hidden)}")
    for h in hidden[:10]:
        print(f"   hidden: {h[0][:40]:40s} scale={h[1]:.4f}")
    # 去掉隐藏件后的离散度
    keep = [p for p in parts if p.name not in {h[0] for h in hidden}]
    cens = []
    for p in keep:
        v = _skin_mesh(p, p.mesh, w)
        if v:
            cens.append((sum(a[0] for a in v) / len(v), sum(a[1] for a in v) / len(v)))
    if cens:
        c = np.array(cens)
        print(f"   spread after hiding: {np.mean(np.std(c, axis=0)):.3f}")
    return hidden


if __name__ == "__main__":
    for n in sys.argv[1:]:
        main(n)
