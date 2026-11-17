# -*- coding: utf-8 -*-
"""把部件位置对齐到 Spine 参照产物（逐部件刚体吸附）。

用于「bind pose 本身就是散架」的角色：Spine 产物里同名部件的形状与我们一致，
只是摆放位置不同；用「质心 + 等比缩放」把每块吸附过去，就能把角色拼起来。
对本来就正确的角色，拟合出的变换接近恒等，不会破坏。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[3]
SPINE_ROOT = Path(r"D:\VB\Convert\Spine\MultiSpine\LO\Products\Current")
SCALE = 100.0          # Spine 产物坐标 = 我们的模型坐标 × 100


def _spine_module():
    tools = ROOT / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import spine_preview  # noqa: WPS433
    return spine_preview


def load_reference(name: str) -> Dict[str, List[Tuple[float, float]]]:
    """返回 {部件名: [(x,y)…]}（已换算到模型坐标，单位与我们的 moc3 一致）。"""
    base = SPINE_ROOT / f"{name}.uAnim"
    if not base.exists():
        return {}
    js = next((p for p in base.glob("*.json") if p.name.endswith("_static.json")), None)
    if js is None:
        return {}
    sp = _spine_module()
    data = json.loads(js.read_text(encoding="utf-8"))
    world, order = sp.bone_worlds(data)
    slots = {s["name"]: s for s in data.get("slots") or []}
    out: Dict[str, List[Tuple[float, float]]] = {}
    for slot_name, items in (data.get("skins") or [{}])[0].get("attachments", {}).items():
        slot = slots.get(slot_name, {})
        for att_name, att in items.items():
            if att.get("type") != "mesh":
                continue
            try:
                pts = sp.mesh_points(att, world, order, slot.get("bone"))
            except Exception:
                continue
            if pts:
                out[att_name] = [(x / SCALE, y / SCALE) for x, y in pts]
    return out


def _centroid(pts):
    n = len(pts) or 1
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)


def _bbox_area(pts) -> float:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return max(1e-9, (max(xs) - min(xs)) * (max(ys) - min(ys)))


def build_offsets(parts, world, name: str, max_scale_dev: float = 0.25,
                  by_geometry: bool = True):
    """给每个源部件算 (scale, c_ours, c_ref)；返回 {部件名: 变换}。

    默认先按名字匹配，匹配不到再按「顶点数 + 包围盒尺寸」找最像的参照网格
    （分块/重命名后名字对不上时仍能吸附）。
    """
    from unity2spine.convert.convert_2dmodel import _skin_mesh

    ref = load_reference(name)
    if not ref:
        return {}, 0, 0

    by_count: Dict[int, List[Tuple[str, list]]] = {}
    for rn, rp in ref.items():
        by_count.setdefault(len(rp), []).append((rn, rp))

    table = {}
    matched = 0
    used = set()
    for p in parts:
        v = _skin_mesh(p, p.mesh, world)
        if not v:
            continue
        rp = ref.get(p.name)
        if rp is None and by_geometry:
            cands = [(rn, rpts) for rn, rpts in by_count.get(len(v), [])
                     if rn not in used]
            if cands:
                av = _bbox_area(v)
                rp_name, rp = min(
                    cands, key=lambda kv: abs(_bbox_area(kv[1]) / av - 1.0))
                used.add(rp_name)
        if rp is None:
            continue
        matched += 1
        c_ours = _centroid(v)
        c_ref = _centroid(rp)
        s = math.sqrt(_bbox_area(rp) / _bbox_area(v))
        if not (1.0 - max_scale_dev <= s <= 1.0 + max_scale_dev):
            continue
        table[p.name] = (s, c_ours, c_ref)
    return table, matched, len(table)


def drop_unreferenced(rig_parts, table, min_ratio: float = 0.4, pad: float = 0.12):
    """删除「参照里没有、且落在参照包围盒之外」的部件（多出来的特效件）。"""
    if not table:
        return rig_parts, []
    keys = sorted(table, key=len, reverse=True)

    def hit_of(name):
        for k in keys:
            if name == k or name.startswith(k):
                return k
        return None

    covered = sum(1 for p in rig_parts if hit_of(p.name))
    if covered < min_ratio * max(1, len(rig_parts)):
        return rig_parts, []

    xs, ys = [], []
    for p in rig_parts:
        if hit_of(p.name):
            xs += [v[0] for v in p.verts]
            ys += [v[1] for v in p.verts]
    if not xs:
        return rig_parts, []
    lo_x, hi_x = min(xs), max(xs)
    lo_y, hi_y = min(ys), max(ys)
    dx = (hi_x - lo_x) * pad
    dy = (hi_y - lo_y) * pad

    keep, dropped = [], []
    for p in rig_parts:
        if hit_of(p.name) or not p.verts:
            keep.append(p)
            continue
        cx = sum(v[0] for v in p.verts) / len(p.verts)
        cy = sum(v[1] for v in p.verts) / len(p.verts)
        inside = (lo_x - dx <= cx <= hi_x + dx) and (lo_y - dy <= cy <= hi_y + dy)
        (keep if inside else dropped).append(p)
    return keep, dropped


def apply_offsets(rig_parts, table, eps: float = 1e-3):
    """把变换套到 RigPart 上（按最长前缀匹配，兼容分块后的名字）。"""
    if not table:
        return 0
    keys = sorted(table, key=len, reverse=True)
    moved = 0
    for rp in rig_parts:
        hit = None
        for k in keys:
            if rp.name == k or rp.name.startswith(k):
                hit = k
                break
        if hit is None:
            continue
        s, c_ours, c_ref = table[hit]
        if (abs(s - 1.0) < eps and
                math.hypot(c_ref[0] - c_ours[0], c_ref[1] - c_ours[1]) < eps):
            continue
        rp.verts = [(s * (v[0] - c_ours[0]) + c_ref[0],
                     s * (v[1] - c_ours[1]) + c_ref[1]) for v in rp.verts]
        moved += 1
    return moved
