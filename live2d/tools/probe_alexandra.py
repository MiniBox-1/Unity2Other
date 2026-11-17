# -*- coding: utf-8 -*-
r"""Probe one real character through the existing Unity2Spine extractor.

usage: python tools\probe_alexandra.py
"""
import sys
from pathlib import Path

U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model)

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
PREFAB = PROJ / "Assets" / "Prefabs" / "2DModel_3P_Alexandra_N.uAnim.prefab"


def main():
    mdl, parts = build_character_model(str(PREFAB), str(PROJ / "Assets"))
    world = _world_matrices(mdl, {})

    print(f"parts: {len(parts)}  transforms: {len(mdl.transforms)}")
    total_v = total_t = 0
    allx, ally = [], []
    for i, p in enumerate(parts):
        mesh = p.mesh or {}
        verts = _skin_mesh(p, mesh, world) if p.kind == "skinned" else [
            (v[0], v[1]) for v in (mesh.get("positions") or [])]
        xs = [v[0] for v in verts] or [0]
        ys = [v[1] for v in verts] or [0]
        allx += xs
        ally += ys
        n = len(verts)
        t = len(mesh.get("triangles") or []) // 3
        total_v += n
        total_t += t
        print(f"{i:2d} {p.name:36s} {p.kind:8s} v={n:5d} tri={t:5d} "
              f"tex={Path(p.texture_path).name if p.texture_path else None:>18s} "
              f"sort={p.sorting_order:3d} order={p.order:2d} "
              f"x=[{min(xs):8.2f},{max(xs):8.2f}] y=[{min(ys):8.2f},{max(ys):8.2f}]")
    print(f"total verts={total_v} tris={total_t}")
    if allx:
        print(f"model bbox x=[{min(allx):.2f},{max(allx):.2f}] y=[{min(ally):.2f},{max(ally):.2f}]")


if __name__ == "__main__":
    main()
