# -*- coding: utf-8 -*-
"""AnimationClip → Live2D motion3.json。

映射：每根骨的本地 Z 旋转增量 Δ（Unity 逆时针为正）→ 参数
`P_<Bone>_Rz = -Δ`（Live2D 角度顺时针为正）。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

import sys

U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
if str(U2S) not in sys.path:
    sys.path.insert(0, str(U2S))

from unity2spine.unity import unity_anim2d as ua  # noqa: E402

from .rig import param_id  # noqa: E402


@dataclass
class MotionCurve:
    param: str
    times: List[float]
    values: List[float]


def quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def quat_inv(q):
    x, y, z, w = q
    n = x * x + y * y + z * z + w * w
    if n < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    return (-x / n, -y / n, -z / n, w / n)


def quat_z_deg(q) -> float:
    """四元数 → 绕 Z 的旋转角（度，CCW 正）。"""
    x, y, z, w = q
    return math.degrees(2.0 * math.atan2(z, w))


def _unwrap(prev: float, cur: float) -> float:
    d = cur - prev
    while d > 180.0:
        cur -= 360.0
        d -= 360.0
    while d < -180.0:
        cur += 360.0
        d += 360.0
    return cur


def sample_clip(clip: Dict, bones: Dict[int, object], transforms: Dict,
                fps: float = 30.0, max_bones: int | None = None) -> List[MotionCurve]:
    """把一个 clip 采样成参数曲线。

    bones: tfid -> Bone（含 name）；transforms: tfid -> transform（含 quat/anim_path）
    """
    rest = {}
    for tfid, t in transforms.items():
        ap = t.get("anim_path")
        if not ap:
            continue
        q = t.get("quat") or (0, 0, 0, 1)
        rest[ap] = {"rx": 0.0, "ry": 0.0, "rz": 0.0,
                    "qx": q[0], "qy": q[1], "qz": q[2], "qw": q[3],
                    "sx": t["scale"][0], "sy": t["scale"][1], "sz": t["scale"][2]}

    sampler = ua.AnimSampler(clip, rest)

    # 只保留真被旋转曲线驱动的骨骼
    animated = set()
    for cu in clip["curves"]:
        if cu.kind in ("rot", "euler"):
            animated.add(cu.path)

    duration = float(clip.get("duration") or 0.0)
    n = max(2, int(round(duration * fps)) + 1)
    times = [min(duration, i / fps) for i in range(n)]

    curves: List[MotionCurve] = []
    for tfid, bone in bones.items():
        ap = transforms.get(tfid, {}).get("anim_path")
        if not ap or ap not in animated:
            continue
        q_rest = transforms[tfid].get("quat") or (0, 0, 0, 1)
        vals: List[float] = []
        prev = None
        for t in times:
            s = sampler.sample(ap, t)
            q = s.get("quat")
            if q is None:
                e = s["euler"]
                q = (0.0, 0.0, math.sin(math.radians(e[2]) / 2),
                     math.cos(math.radians(e[2]) / 2))
            rel = quat_mul(quat_inv(q_rest), tuple(q))
            ang = quat_z_deg(rel)
            if prev is not None:
                ang = _unwrap(prev, ang)
            prev = ang
            # Unity 逆时针正 → Live2D 参数取负
            vals.append(-ang)

        if max(abs(v) for v in vals) < 0.01:
            continue                                   # 常量曲线，省略
        curves.append(MotionCurve(param_id(bone), times, vals))

    return curves


def _clean(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in (name or "Bone"))


def to_motion3(curves: Sequence[MotionCurve], duration: float, fps: float = 30.0,
               loop: bool = True, fade_in: float = 0.5,
               fade_out: float = 0.5) -> Dict:
    out_curves = []
    for c in curves:
        seg: List[float] = [round(c.times[0], 4), round(c.values[0], 5)]
        for i in range(1, len(c.times)):
            seg += [0, round(c.times[i], 4), round(c.values[i], 5)]   # 0 = Linear
        out_curves.append({
            "Target": "Parameter",
            "Id": c.param,
            "Segments": seg,
        })
    return {
        "Version": 3,
        "Meta": {
            "Duration": round(duration, 4),
            "Fps": fps,
            "Loop": bool(loop),
            "FadeInTime": fade_in,
            "FadeOutTime": fade_out,
        },
        "Curves": out_curves,
    }


def write_motion(motion: Dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(motion, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
