# -*- coding: utf-8 -*-
"""按 AnimationClip 重建 Unity 世界矩阵（用于真值计算与骨骼归属反推）。"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Callable, Dict

U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
if str(U2S) not in sys.path:
    sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import mat4_mul  # noqa: E402
from unity2spine.unity import unity_anim2d as ua  # noqa: E402


def rest_dict(mdl) -> Dict[str, dict]:
    out = {}
    for tfid, tr in mdl.transforms.items():
        ap = tr.get("anim_path")
        if not ap:
            continue
        q = tr.get("quat") or (0, 0, 0, 1)
        pos = tr.get("pos") or (0, 0, 0)
        out[ap] = {"px": pos[0], "py": pos[1], "pz": pos[2],
                   "qx": q[0], "qy": q[1], "qz": q[2], "qw": q[3],
                   "sx": tr["scale"][0], "sy": tr["scale"][1], "sz": tr["scale"][2]}
    return out


def make_sampler(mdl, clip):
    sampler = ua.AnimSampler(clip, rest_dict(mdl))

    def world_at(t: float):
        cache = {}

        def get(tfid):
            if tfid in cache:
                return cache[tfid]
            tr = mdl.transforms[tfid]
            local = None
            ap = tr.get("anim_path")
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

    return world_at


def affine_world_at(mdl, clip, t: float) -> Dict[int, tuple]:
    """t 时刻的 2D 仿射世界矩阵（与 rig.from_trs 同约定），用于「以动画姿势为基准」。"""
    from .rig import from_trs, mul

    sampler = ua.AnimSampler(clip, rest_dict(mdl))
    cache: Dict[int, tuple] = {}

    def get(tfid):
        if tfid in cache:
            return cache[tfid]
        tr = mdl.transforms[tfid]
        ap = tr.get("anim_path")
        if ap:
            s = sampler.sample(ap, t)
            q = s.get("quat")
            if q is None:
                e = s["euler"]
                ang = math.radians(e[2])
                q = (0.0, 0.0, math.sin(ang / 2), math.cos(ang / 2))
            local = from_trs(tuple(s["pos"]), tuple(q), tuple(s["scale"]))
        else:
            local = from_trs(tr["pos"], tuple(tr["quat"]), tr["scale"])
        f = tr.get("father")
        m = mul(get(f), local) if f in mdl.transforms else local
        cache[tfid] = m
        return m

    for tfid in mdl.transforms:
        get(tfid)
    return cache


def mat4_inverse(m) -> list:
    """4x4 仿射逆（行主序 list[16]）。"""
    a = [[m[r * 4 + c] for c in range(4)] for r in range(4)]
    r = [[a[i][j] for j in range(3)] for i in range(3)]
    det = (r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
           - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
           + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0]))
    out = [0.0] * 16
    if abs(det) < 1e-12:
        out[0] = out[5] = out[10] = out[15] = 1.0
        return out
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
    for i in range(3):
        for j in range(3):
            out[i * 4 + j] = inv[i][j]
        out[i * 4 + 3] = -(inv[i][0] * t[0] + inv[i][1] * t[1] + inv[i][2] * t[2])
    out[15] = 1.0
    return out
