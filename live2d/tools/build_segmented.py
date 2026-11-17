# -*- coding: utf-8 -*-
r"""Build a model whose art meshes are split per-bone using animation truth.

usage: python tools\build_segmented.py <CharName> [MotionName] [--out DIR]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model)
from unity2spine.unity import unity_anim2d as ua  # noqa: E402

from unity2live2d.convert.anim_world import make_sampler  # noqa: E402
from unity2live2d.convert.attribute import attribute, split_triangles  # noqa: E402
from unity2live2d.convert.pipeline import _guid_index, controller_of  # noqa: E402
from unity2live2d.convert.rig import collect_bones  # noqa: E402
from unity2live2d.convert.rigged_model import RigPart, build_rigged  # noqa: E402
from unity2live2d.convert.static_model import verify, write_package  # noqa: E402
from unity2spine.unity import unity_2dmodel as u2d  # noqa: E402

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
ASSETS = PROJ / "Assets"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("motion", nargs="?", default="")
    ap.add_argument("--out", default=str(ROOT / "Products"))
    args = ap.parse_args()

    prefab = ASSETS / "Prefabs" / f"{args.name}.uAnim.prefab"
    if not prefab.exists():
        raise SystemExit(f"prefab not found: {prefab}")

    mdl, parts = build_character_model(str(prefab), str(ASSETS))
    world = _world_matrices(mdl, {})
    bone_ids = {b for p in parts for b in (p.bones or []) if b}
    bones = collect_bones(mdl, bone_ids)

    # 找一个动作来做真值
    guid_index = _guid_index(ASSETS)
    ctrl_guid = controller_of(prefab)
    states = u2d.parse_animator_controller(str(guid_index[ctrl_guid]))
    if args.motion:
        states = [s for s in states if s["name"] == args.motion] or states[:1]
    clip_path = None
    for s in states:
        p = guid_index.get(s["clipGuid"])
        if p and p.suffix == ".anim":
            clip_path = p
            break
    if clip_path is None:
        raise SystemExit("no clip")
    clip = ua.parse_clip(str(clip_path))
    duration = float(clip.get("duration") or 0.0)
    world_at = make_sampler(mdl, clip)
    frame_t = [duration * i / 3.0 for i in range(4)]
    getters = [world_at(t) for t in frame_t]
    print(f"{args.name}: clip={clip_path.stem} dur={duration:.2f} frames={frame_t}")

    seg_parts = []
    for p in parts:
        mesh = p.mesh or {}
        if p.kind != "skinned" or not mesh.get("positions"):
            continue
        rest_v = [(v[0], v[1]) for v in _skin_mesh(p, mesh, world)]
        raw_uvs = list(mesh.get("uvs") or [])
        uvs = ([c for uv in raw_uvs for c in uv]
               if raw_uvs and isinstance(raw_uvs[0], (tuple, list)) else list(raw_uvs))
        tris = list(mesh.get("triangles") or [])
        if len(uvs) != 2 * len(rest_v) or not tris:
            continue

        cand = [b for b in (p.bones or []) if b in bones]
        if not cand:
            continue
        truth_frames = [[(v[0], v[1]) for v in _skin_mesh(p, mesh, {k: g(k) for k in mdl.transforms})]
                        for g in getters]
        bone_worlds = [[g(b) for b in cand] for g in getters]
        bone_rest = [world[b] for b in cand]
        vb = attribute(rest_v, truth_frames, bone_worlds, bone_rest, cand)

        # 统计每根骨分到多少顶点
        from collections import Counter
        cnt = Counter(vb)
        groups = split_triangles(tris, vb, len(cand))
        for bi, tl in groups.items():
            if len(tl) < 3:
                continue
            used = sorted(set(tl))
            remap = {g: i for i, g in enumerate(used)}
            verts = [rest_v[g] for g in used]
            uv2 = [uvs[g * 2] for g in used] + [uvs[g * 2 + 1] for g in used]
            uv_flat = []
            for g in used:
                uv_flat += [uvs[g * 2], uvs[g * 2 + 1]]
            idx = [remap[g] for g in tl]
            seg_parts.append(RigPart(
                name=f"{p.name}_{bones[cand[bi]].name}",
                verts=verts, uvs=uv_flat, indices=idx,
                bone=cand[bi], sorting_order=p.sorting_order, order=p.order))

    print(f"segments: {len(seg_parts)} (from {len(parts)} parts)")
    seg_parts.sort(key=lambda s: (s.sorting_order, s.order))

    out_name = f"{args.name}_seg"
    result = build_rigged(seg_parts, mdl, bones=bones, ppu=1000.0, margin=0.05,
                          angle_range=(-30.0, 30.0))
    tex = next((Path(p.texture_path) for p in parts if p.texture_path), None)
    out = Path(args.out) / out_name
    write_package(result, out_name, out, texture=tex)
    rep = verify(result, out_name)
    print("consistency", rep["consistency"], "max_err", rep["max_err"])
    print("out", out)


if __name__ == "__main__":
    main()
