# -*- coding: utf-8 -*-
"""按动作真值把每个顶点归属到「最能解释它运动」的骨骼，并把三角形切块。

不依赖 SMR 的 `m_Bones` 顺序（那批资产里存在错位），只依赖运动结果：
    预测_b(t) = M_b(t) · inv(M_b(rest)) · v_rest
    选择使 Σ_t |预测_b(t) - 真值(t)|² 最小的骨骼 b。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

import sys
from pathlib import Path

U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
if str(U2S) not in sys.path:
    sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import mat4_mul, mat4_vec  # noqa: E402

from .anim_world import mat4_inverse  # noqa: E402


def attribute(rest_verts: Sequence[Tuple[float, float]],
              truth_frames: Sequence[Sequence[Tuple[float, float]]],
              bone_worlds: Sequence[Sequence[list]],
              bone_rest: Sequence[list],
              bone_ids: Sequence[int]) -> List[int]:
    """返回每个顶点的骨骼下标（对应 bone_ids 顺序）。

    truth_frames[f][v] = 第 f 帧该顶点的真实位置；
    bone_worlds[f][b]   = 第 f 帧第 b 根骨的世界矩阵。
    """
    n_v = len(rest_verts)
    n_b = len(bone_ids)
    err = [[0.0] * n_b for _ in range(n_v)]

    for f, truth in enumerate(truth_frames):
        inv_rest = [mat4_inverse(m) for m in bone_rest]
        rel = [mat4_mul(bone_worlds[f][b], inv_rest[b]) for b in range(n_b)]
        for b in range(n_b):
            m = rel[b]
            row = err
            for v in range(n_v):
                px, py, _ = mat4_vec(m, (rest_verts[v][0], rest_verts[v][1], 0.0))
                dx = px - truth[v][0]
                dy = py - truth[v][1]
                row[v][b] += dx * dx + dy * dy

    out = []
    for v in range(n_v):
        out.append(min(range(n_b), key=lambda b: err[v][b]))
    return out


def split_triangles(triangles: Sequence[int], vert_bone: Sequence[int],
                    n_bones: int) -> Dict[int, List[int]]:
    """三角形按「多数顶点的骨骼」分块，返回 bone_idx -> 三角形顶点列表。"""
    groups: Dict[int, List[int]] = defaultdict(list)
    for t in range(0, len(triangles) - 2, 3):
        a, b, c = triangles[t], triangles[t + 1], triangles[t + 2]
        votes: Dict[int, int] = defaultdict(int)
        for v in (a, b, c):
            votes[vert_bone[v]] += 1
        bone = max(votes.items(), key=lambda kv: kv[1])[0]
        groups[bone].extend([a, b, c])
    return dict(groups)
