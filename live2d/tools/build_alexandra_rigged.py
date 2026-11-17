# -*- coding: utf-8 -*-
r"""Build Alexandra with a RotationDeformer chain from the bone tree.

usage: python tools\build_alexandra_rigged.py
"""
import json
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
from unity2live2d.convert.static_model import verify, write_package  # noqa: E402

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
PREFAB = PROJ / "Assets" / "Prefabs" / "2DModel_3P_Alexandra_N.uAnim.prefab"
NAME = "2DModel_3P_Alexandra_N_rig"
OUT = ROOT / "Products" / NAME


def main():
    mdl, parts = build_character_model(str(PREFAB), str(PROJ / "Assets"))
    world = _world_matrices(mdl, {})

    # 全部候选骨骼（含祖先），这样变形器链是完整的
    bone_ids = set()
    for p in parts:
        for b in (p.bones or []):
            if b:
                bone_ids.add(b)
    bones = collect_bones(mdl, bone_ids)

    rig_parts = []
    for p in parts:
        mesh = p.mesh or {}
        if p.kind == "skinned":
            verts = [(v[0], v[1]) for v in _skin_mesh(p, mesh, world)]
        else:
            verts = [(v[0], v[1]) for v in (mesh.get("positions") or [])]
        raw_uvs = list(mesh.get("uvs") or [])
        uvs = ([c for uv in raw_uvs for c in uv]
               if raw_uvs and isinstance(raw_uvs[0], (tuple, list)) else list(raw_uvs))
        tris = list(mesh.get("triangles") or [])
        if not verts or not uvs or not tris:
            continue
        rig_parts.append(RigPart(
            name=p.name, verts=verts, uvs=uvs, indices=tris,
            bone=dominant_bone(p, bones, verts) or -1,
            sorting_order=p.sorting_order, order=p.order))

    rig_parts.sort(key=lambda s: (s.sorting_order, s.order))
    used = {p.bone for p in rig_parts if p.bone >= 0}
    print(f"parts: {len(rig_parts)}  bones: {len(bones)}  used: {len(used)}")
    for p in rig_parts:
        print(f"  {p.name:34s} -> {bones[p.bone].name if p.bone in bones else None}")

    result = build_rigged(rig_parts, mdl, bones=bones, ppu=1000.0, margin=0.05,
                          angle_range=(-30.0, 30.0))
    write_package(result, NAME, OUT, texture=Path(parts[0].texture_path))

    report = verify(result, NAME)
    report["source"] = str(PREFAB)
    report["deformers"] = len(bones)
    (OUT / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("out:", OUT)


if __name__ == "__main__":
    main()
