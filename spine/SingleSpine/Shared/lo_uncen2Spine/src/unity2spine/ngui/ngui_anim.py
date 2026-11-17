# -*- coding: utf-8 -*-
"""Legacy AnimationClip 的解析与采样（.anim 文本资源）。"""

import math

from ..unity.unity_parse import load_unity_docs


def _comp(v, key):
    if isinstance(v, dict):
        return float(v.get(key, 0.0))
    return float(v)


def _hermite(p0, p1, m0, m1, s):
    """标准三次 Hermite（单位区间）。m 为值/单位时间。"""
    s2 = s * s
    s3 = s2 * s
    h00 = 2 * s3 - 3 * s2 + 1
    h10 = s3 - 2 * s2 + s
    h01 = -2 * s3 + 3 * s2
    h11 = s3 - s2
    return h00 * p0 + h10 * m0 + h01 * p1 + h11 * m1


class UnityAnimCurve:
    """一条曲线（RotationCurve/PositionCurve/FloatCurve/ScaleCurve）。"""

    def __init__(self, path, kind, keys, slopes=None, attribute=None):
        self.path = path
        self.kind = kind  # 'rot' | 'pos' | 'scale' | 'float'
        self.keys = keys  # [(time, value)] value: dict/float
        self.slopes = slopes or {}
        self.attribute = attribute

    @property
    def times(self):
        return [k[0] for k in self.keys]

    def value_at(self, t, comp=None):
        """按 Unity 无加权 Hermite 求值；comp 只用于 vec/rot 单分量。"""
        keys = self.keys
        if t <= keys[0][0]:
            v = keys[0][1]
            return _comp(v, comp) if comp else v
        if t >= keys[-1][0]:
            v = keys[-1][1]
            return _comp(v, comp) if comp else v
        # 找右侧帧
        lo, hi = 0, len(keys) - 1
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if keys[mid][0] <= t:
                lo = mid
            else:
                hi = mid
        t0, v0 = keys[lo]
        t1, v1 = keys[hi]
        s = (t - t0) / (t1 - t0)
        if self.kind == "float":
            v0 = _comp(v0, None)
            v1 = _comp(v1, None)
            m0 = _comp(self.slopes.get((lo, "out"), 0.0), None)
            m1 = _comp(self.slopes.get((hi, "in"), 0.0), None)
            if math.isinf(m0) or math.isinf(m1):
                # Unity “Constant”段：无穷斜率 = 保持左侧帧值到右侧帧（前一轮结论）
                return v0
            m0 *= (t1 - t0)
            m1 *= (t1 - t0)
            return _hermite(v0, v1, m0, m1, s)
        comps = ["x", "y", "z", "w"] if self.kind == "rot" else ["x", "y", "z"]
        if comp:
            comps = [comp]
        out = {}
        for c in comps:
            p0 = _comp(v0, c)
            p1 = _comp(v1, c)
            m0 = self.slopes.get((lo, "out"), {})
            m1 = self.slopes.get((hi, "in"), {})
            a0 = _comp(m0, c)
            a1 = _comp(m1, c)
            # ±Infinity 斜率 = Unity 编辑器 Constant 切线：这一段**保持左键值**
            # （不插值）。漏判这条会让"该停住的段"被插成一条斜线
            # （KunoichiKaen 的"嘴巴自动向上漂"，2026-10-11 定位）。
            if math.isinf(a0) or math.isinf(a1):
                out[c] = p0
                continue
            m0 = _comp(m0, c) * (t1 - t0)
            m1 = _comp(m1, c) * (t1 - t0)
            out[c] = _hermite(p0, p1, m0, m1, s)
        if self.kind == "rot":
            # 归一化四元数
            norm = math.sqrt(sum(v * v for v in out.values()))
            if norm > 1e-12:
                out = {c: v / norm for c, v in out.items()}
        return out


def parse_clip(path):
    """返回 {'curves': [...], 'settings': {...}}"""
    docs = load_unity_docs(path)
    clip = None
    for c, _, d in docs:
        if c == 74 and "AnimationClip" in d:
            clip = d["AnimationClip"]
            break
    if clip is None:
        raise ValueError("not an AnimationClip: " + path)
    curves = []

    def collect(entries, kind):
        for e in entries or []:
            curve = e.get("curve") or {}
            kfs = curve.get("m_Curve") or []
            keys = []
            slopes = {}
            for idx, kf in enumerate(kfs):
                t = float(kf.get("time", 0))
                val = kf.get("value")
                keys.append((t, val))
                if kind != "float":
                    slopes[(idx, "out")] = kf.get("outSlope") or {}
                    slopes[(idx, "in")] = kf.get("inSlope") or {}
                else:
                    slopes[(idx, "out")] = _float0(kf.get("outSlope"))
                    slopes[(idx, "in")] = _float0(kf.get("inSlope"))
            if keys:
                curves.append(UnityAnimCurve(e.get("path", ""), kind, keys, slopes))

    collect(clip.get("m_RotationCurves"), "rot")
    collect(clip.get("m_PositionCurves"), "pos")
    collect(clip.get("m_ScaleCurves"), "scale")
    for e in clip.get("m_FloatCurves") or []:
        curve = e.get("curve") or {}
        kfs = curve.get("m_Curve") or []
        keys = []
        slopes = {}
        for idx, kf in enumerate(kfs):
            keys.append((float(kf.get("time", 0)), kf.get("value")))
            slopes[(idx, "out")] = _float0(kf.get("outSlope"))
            slopes[(idx, "in")] = _float0(kf.get("inSlope"))
        if keys:
            curves.append(UnityAnimCurve(e.get("path", ""), "float", keys, slopes,
                                        attribute=e.get("attribute", "")))
    return {"curves": curves, "settings": clip.get("m_AnimationClipSettings", {})}


def _float0(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def quat_to_deg_z(q):
    x = float(q.get("x", 0))
    y = float(q.get("y", 0))
    z = float(q.get("z", 0))
    w = float(q.get("w", 1))
    return math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))
