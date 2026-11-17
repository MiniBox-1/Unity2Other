# -*- coding: utf-8 -*-
r"""Build a static Live2D model from a real Unity character (Alexandra).

usage: python tools\build_alexandra.py
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

from unity2live2d.convert.static_model import (  # noqa: E402
    StaticPart, build_static, verify, write_package)

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
PREFAB = PROJ / "Assets" / "Prefabs" / "2DModel_3P_Alexandra_N.uAnim.prefab"
NAME = "2DModel_3P_Alexandra_N"
OUT = ROOT / "Products" / NAME


def main():
    mdl, parts = build_character_model(str(PREFAB), str(PROJ / "Assets"))
    world = _world_matrices(mdl, {})

    static_parts = []
    for p in parts:
        mesh = p.mesh or {}
        if p.kind == "skinned":
            verts = [(v[0], v[1]) for v in _skin_mesh(p, mesh, world)]
        else:
            verts = [(v[0], v[1]) for v in (mesh.get("positions") or [])]
        raw_uvs = list(mesh.get("uvs") or [])
        # UV 可能是 [(u,v), ...] 也可能是扁平 [u,v,...]
        if raw_uvs and isinstance(raw_uvs[0], (tuple, list)):
            uvs = [c for uv in raw_uvs for c in uv]
        else:
            uvs = list(raw_uvs)
        tris = list(mesh.get("triangles") or [])
        if not verts or not uvs or not tris:
            print(f"  skip {p.name}: incomplete")
            continue
        if len(uvs) != len(verts) * 2:
            print(f"  warn {p.name}: uv count {len(uvs)} vs verts {len(verts)}")
        static_parts.append(StaticPart(
            name=p.name, verts=verts, uvs=uvs, indices=tris,
            texture=Path(p.texture_path) if p.texture_path else None,
            sorting_order=p.sorting_order, order=p.order))

    static_parts.sort(key=lambda s: (s.sorting_order, s.order))
    print(f"parts: {len(static_parts)}  verts: {sum(len(p.verts) for p in static_parts)}")

    result = build_static(static_parts, NAME, ppu=1000.0, margin=0.05)
    write_package(result, NAME, OUT, texture=static_parts[0].texture)

    report = verify(result, NAME)
    report["source"] = str(PREFAB)
    report["texture"] = str(static_parts[0].texture)
    (OUT / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("out:", OUT)


if __name__ == "__main__":
    main()
