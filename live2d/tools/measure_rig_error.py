# -*- coding: utf-8 -*-
r"""Quantify the rigid-rig error vs true Unity skinning.

Truth = full LBS (bone weights) at time t.
Model = each part rigidly follows its dominant bone (what the current
        RotationDeformer rig does).

usage: python tools\measure_rig_error.py <Prefab> <MotionName> [frames]
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model, mat4_mul, mat4_vec)
from unity2spine.unity import unity_anim2d as ua  # noqa: E402
from unity2spine.unity import unity_2dmodel as u2d  # noqa: E402

from unity2live2d.convert.rig import collect_bones, dominant_bone  # noqa: E402

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
ASSETS = PROJ / "Assets"


def anim_world(mdl, sampler, t):
    """按 clip 采样重建 4x4 世界矩阵。"""
    cache = {}

    def get(tfid):
        if tfid in cache:
            return cache[tfid]
        tr = mdl.transforms[tfid]
        ap = tr.get("anim_path")
        local = None
        if ap:
            s = sampler.sample(ap, t)
            q = s.get("quat")
            if q is None:
                e = s["euler"]
                ang = math.radians(e[2])
                q = (0.0, 0.0, math.sin(ang / 2), math.cos(ang / 2))
            local = ua.trs_mat(tuple(s["pos"]), tuple(q), tuple(s["scale"]))
        if local is None:
            local = ua.trs_mat(tr["pos"], tuple(tr["quat"]), tr["scale"])
        f = tr.get("father")
        m = mat4_mul(get(f), local) if f in mdl.transforms else local
        cache[tfid] = m
        return m

    return get


def find_clip(prefab: Path, state: str):
    import re
    guid = re.search(r"m_Controller: \{fileID: 9100000, guid: ([0-9a-f]+)",
                     prefab.read_text(encoding="utf-8", errors="replace")).group(1)
    ctrl = None
    for meta in ASSETS.rglob("*.controller.meta"):
        if f"guid: {guid}" in meta.read_text(encoding="utf-8", errors="replace"):
            ctrl = meta.with_suffix("")
            break
    states = u2d.parse_animator_controller(str(ctrl))
    st = [s for s in states if s["name"] == state][0]
    for meta in ASSETS.rglob("*.anim.meta"):
        if f"guid: {st['clipGuid']}" in meta.read_text(encoding="utf-8", errors="replace"):
            return meta.with_suffix("")
    raise SystemExit("clip not found")


def main():
    prefab = Path(sys.argv[1])
    motion = sys.argv[2]
    n_frames = int(sys.argv[3]) if len(sys.argv) > 3 else 6

    mdl, parts = build_character_model(str(prefab), str(ASSETS))
    world = _world_matrices(mdl, {})
    bone_ids = {b for p in parts for b in (p.bones or []) if b}
    bones = collect_bones(mdl, bone_ids)

    clip = ua.parse_clip(str(find_clip(prefab, motion)))
    duration = float(clip.get("duration") or 0.0)
    rest = {}
    for tfid, tr in mdl.transforms.items():
        ap = tr.get("anim_path")
        if ap:
            q = tr.get("quat") or (0, 0, 0, 1)
            rest[ap] = {"qx": q[0], "qy": q[1], "qz": q[2], "qw": q[3],
                        "sx": tr["scale"][0], "sy": tr["scale"][1], "sz": tr["scale"][2]}
    sampler = ua.AnimSampler(clip, rest)

    targets = []
    for p in parts:
        if p.kind != "skinned":
            continue
        verts = [(v[0], v[1]) for v in _skin_mesh(p, p.mesh, world)]
        targets.append((p, dominant_bone(p, bones, verts), verts))

    times = [duration * i / max(1, n_frames - 1) for i in range(n_frames)]
    print(f"{prefab.stem}  {motion}  dur={duration:.2f}s frames={len(times)}")
    stats = {}
    for t in times:
        get = anim_world(mdl, sampler, t)
        world_t = {tfid: get(tfid) for tfid in mdl.transforms}
        for p, bone, rest_v in targets:
            if bone is None or bone not in bones:
                continue
            truth = _skin_mesh(p, p.mesh, world_t)
            m_t = get(bone)
            m_0 = world.get(bone)
            # 刚性模型：p(t) = M_bone(t) * inv(M_bone(rest)) * p_rest
            rigid = mat4_mul(m_t, _inverse(m_0))
            pred = [mat4_vec(rigid, (x, y, 0.0)) for x, y in rest_v]
            errs = [math.hypot(a[0] - c[0], a[1] - c[1]) for a, c in zip(truth, pred)]
            rms = math.sqrt(sum(e * e for e in errs) / len(errs))
            cur = stats.setdefault(p.name, [0.0, 0.0])
            cur[0] = max(cur[0], rms)
            cur[1] = max(cur[1], max(errs))

    rows = sorted(stats.items(), key=lambda kv: -kv[1][0])
    print(f"{'part':38s} {'rms_px':>8s} {'max_px':>8s}")
    for name, (rms, mx) in rows:
        print(f"{name:38s} {rms*1000:8.1f} {mx*1000:8.1f}")


def _inverse(m):
    """4x4 逆（行主序 list[16]，带平移的仿射）。"""
    a = [[m[r * 4 + c] for c in range(4)] for r in range(4)]
    # 只处理仿射：旋转/缩放块求逆 + 平移
    r = [[a[i][j] for j in range(3)] for i in range(3)]
    det = (r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
           - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
           + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0]))
    if abs(det) < 1e-12:
        return list(m)
    inv = [[0.0] * 3 for _ in range(3)]
    inv[0][0] = (r[1][1] * r[2][2] - r[1][2] * r[2][1]) / det
    inv[0][1] = (r[0][2] * r[2][1] - r[0][1] * r[2][2]) / det
    inv[0][2] = (r[0][1] * r[1][2] - r[0][2] * r[1][1]) / det
    inv[1][0] = (r[1][2] * r[2][0] - r[1][0] * r[2][2]) / det
    inv[1][1] = (r[0][0] * r[2][2] - r[0][2] * r[2][0]) / det
    inv[1][2] = (r[0][2] * r[1][0] - r[0][0] * r[1][2]) / det
    inv[2][0] = (r[1][0] * r[2][1] - r[1][1] * r[2][0]) / det
    inv[2][1] = (r[0][1] * r[2][0] - r[0][0] * r[2][1]) / det
    inv[2][2] = (r[0][0] * r[1][1] - r[0][1] * r[1][0]) / det
    t = [a[0][3], a[1][3], a[2][3]]
    out = [0.0] * 16
    for i in range(3):
        for j in range(3):
            out[i * 4 + j] = inv[i][j]
    for i in range(3):
        out[i * 4 + 3] = -(inv[i][0] * t[0] + inv[i][1] * t[1] + inv[i][2] * t[2])
    out[15] = 1.0
    return out


if __name__ == "__main__":
    main()
