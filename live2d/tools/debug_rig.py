# -*- coding: utf-8 -*-
r"""Bisect the rigged build: how many parts / bones until consistency breaks."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model)

from unity2live2d.convert.rig import collect_bones, dominant_bone  # noqa: E402
from unity2live2d.convert.rigged_model import RigPart, build_rigged  # noqa: E402
from unity2live2d.moc3 import CubismCore  # noqa: E402

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
PREFAB = PROJ / "Assets" / "Prefabs" / "2DModel_3P_Alexandra_N.uAnim.prefab"


def load():
    mdl, parts = build_character_model(str(PREFAB), str(PROJ / "Assets"))
    world = _world_matrices(mdl, {})
    bone_ids = set()
    for p in parts:
        for b in (p.bones or []):
            if b:
                bone_ids.add(b)
    bones = collect_bones(mdl, bone_ids)

    rig = []
    for p in parts:
        mesh = p.mesh or {}
        verts = ([(v[0], v[1]) for v in _skin_mesh(p, mesh, world)]
                 if p.kind == "skinned" else
                 [(v[0], v[1]) for v in (mesh.get("positions") or [])])
        raw_uvs = list(mesh.get("uvs") or [])
        uvs = ([c for uv in raw_uvs for c in uv]
               if raw_uvs and isinstance(raw_uvs[0], (tuple, list)) else list(raw_uvs))
        tris = list(mesh.get("triangles") or [])
        if not verts or not uvs or not tris:
            continue
        rig.append(RigPart(name=p.name, verts=verts, uvs=uvs, indices=tris,
                           bone=dominant_bone(p, bones, verts) or -1,
                           sorting_order=p.sorting_order, order=p.order))
    rig.sort(key=lambda s: (s.sorting_order, s.order))
    return mdl, bones, rig


def main():
    core = CubismCore()
    mdl, bones, rig = load()
    for n in range(1, len(rig) + 1):
        sub = rig[:n]
        for no_def in (False, True):
            bs = {} if no_def else bones
            r = build_rigged(sub, mdl, bones=bs, ppu=1000.0)
            ok = core.consistency(r.moc)
            print(f"parts={n:2d} deformers={'off' if no_def else len(bs):3d} "
                  f"consistency={ok} bytes={len(r.moc)}")
            if not ok:
                return


if __name__ == "__main__":
    main()
