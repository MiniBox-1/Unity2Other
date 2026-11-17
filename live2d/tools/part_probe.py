# -*- coding: utf-8 -*-
r"""Probe why a specific source part is dropped by the pipeline."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model)
from unity2live2d.convert.pipeline import (  # noqa: E402
    _guid_index, load_states, segment_part, collect_bones)

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")


def main(name, needle):
    prefab = PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"
    mdl, parts = build_character_model(str(prefab), str(PROJ / "Assets"))
    world = _world_matrices(mdl, {})
    bone_ids = {b for p in parts for b in (p.bones or []) if b}
    bones = collect_bones(mdl, bone_ids)
    states = load_states(prefab, _guid_index(PROJ / "Assets"))
    for p in parts:
        if needle not in p.name:
            continue
        mesh = p.mesh or {}
        v = _skin_mesh(p, mesh, world)
        raw = list(mesh.get("uvs") or [])
        flat = ([c for uv in raw for c in uv]
                if raw and isinstance(raw[0], (tuple, list)) else list(raw))
        print(f"{p.name}: kind={p.kind} verts={len(v)} uvs={len(flat)} "
              f"tris={len(mesh.get('triangles') or [])} bones={len(p.bones or [])}")
        clip = states[0][2] if states else None
        if clip is not None:
            from unity2live2d.convert.anim_world import make_sampler
            wa = make_sampler(mdl, clip)
            seg = segment_part(p, mdl, bones, world, wa, [0.0],
                               texture=0)
            print(f"  segment_part -> {len(seg)} segment(s)")
        break


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
