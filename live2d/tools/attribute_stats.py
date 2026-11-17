# -*- coding: utf-8 -*-
r"""How much does per-vertex bone attribution help vs whole-part rigid?

usage: python tools\attribute_stats.py <CharName> [MotionName]
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model)
from unity2spine.unity import unity_anim2d as ua  # noqa: E402
from unity2spine.unity import unity_2dmodel as u2d  # noqa: E402

from unity2live2d.convert.anim_world import mat4_inverse, make_sampler  # noqa: E402
from unity2live2d.convert.attribute import attribute  # noqa: E402
from unity2live2d.convert.pipeline import _guid_index, controller_of  # noqa: E402
from unity2spine.convert.convert_2dmodel import mat4_mul, mat4_vec  # noqa: E402

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
ASSETS = PROJ / "Assets"


def main():
    name = sys.argv[1]
    prefab = ASSETS / "Prefabs" / f"{name}.uAnim.prefab"
    mdl, parts = build_character_model(str(prefab), str(ASSETS))
    world = _world_matrices(mdl, {})
    bones = {}
    for p in parts:
        for b in (p.bones or []):
            if b:
                bones[b] = mdl.transforms[b]

    guid_index = _guid_index(ASSETS)
    ctrl = guid_index[controller_of(prefab)]
    states = u2d.parse_animator_controller(str(ctrl))
    clip = None
    for s in states:
        p = guid_index.get(s["clipGuid"])
        if p and p.suffix == ".anim":
            clip = ua.parse_clip(str(p))
            break
    dur = float(clip.get("duration") or 0)
    world_at = make_sampler(mdl, clip)
    ts = [dur * i / 3.0 for i in range(4)]
    getters = [world_at(t) for t in ts]

    tot_rigid = 0.0
    tot_seg = 0.0
    n_verts = 0
    for p in parts:
        mesh = p.mesh or {}
        if p.kind != "skinned" or not mesh.get("positions"):
            continue
        rest_v = [(v[0], v[1]) for v in _skin_mesh(p, mesh, world)]
        cand = [b for b in (p.bones or []) if b in bones]
        if not cand:
            continue
        truth = [[(v[0], v[1]) for v in _skin_mesh(p, mesh, {k: g(k) for k in mdl.transforms})]
                 for g in getters]
        bw = [[g(b) for b in cand] for g in getters]
        br = [world[b] for b in cand]
        vb = attribute(rest_v, truth, bw, br, cand)

        # 每根骨的相对变换
        rels = []
        for f in range(len(ts)):
            rels.append([mat4_mul(bw[f][k], mat4_inverse(br[k])) for k in range(len(cand))])

        for vi in range(len(rest_v)):
            # 整部件刚性：用该部件票数最多的骨
            from collections import Counter
            dom = Counter(vb).most_common(1)[0][0]
            e_rigid = 0.0
            e_seg = 0.0
            for f in range(len(ts)):
                m = rels[f][dom]
                px, py, _ = mat4_vec(m, (rest_v[vi][0], rest_v[vi][1], 0.0))
                e_rigid += (px - truth[f][vi][0]) ** 2 + (py - truth[f][vi][1]) ** 2
                m2 = rels[f][vb[vi]]
                qx, qy, _ = mat4_vec(m2, (rest_v[vi][0], rest_v[vi][1], 0.0))
                e_seg += (qx - truth[f][vi][0]) ** 2 + (qy - truth[f][vi][1]) ** 2
            tot_rigid += e_rigid
            tot_seg += e_seg
            n_verts += 1

    rms_r = math.sqrt(tot_rigid / max(1, n_verts * len(ts))) * 1000
    rms_s = math.sqrt(tot_seg / max(1, n_verts * len(ts))) * 1000
    print(f"{name}: verts={n_verts} frames={len(ts)}")
    print(f"  整部件刚性 RMS = {rms_r:8.1f} px")
    print(f"  逐顶点分块 RMS = {rms_s:8.1f} px  ({100*(1-rms_s/max(rms_r,1e-9)):.0f}% 降低)")


if __name__ == "__main__":
    main()
