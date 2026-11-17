# -*- coding: utf-8 -*-
"""把 Unity 2D 角色的 bindpose 转成一个静态 Live2D 模型包。

输入：unity2spine 的 `build_character_model()` 产出的 parts（含蒙皮网格、
UV、三角形、纹理路径、sortingOrder）。
输出：<out>/<name>.moc3 + <name>.model3.json + textures/texture_00.png

当前阶段只做「静态」：所有 ArtMesh 直接挂在模型空间（deformer=-1），
按 Unity 的 sortingOrder 从后往前排；骨骼/参数/动作在后续阶段叠加。
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from ..moc3 import ArtMeshKeyform, Moc3Builder


@dataclass
class StaticPart:
    name: str
    verts: List[Tuple[float, float]]
    uvs: List[float]
    indices: List[int]
    texture: Path
    sorting_order: int = 0
    order: int = 0


@dataclass
class StaticResult:
    moc: bytes
    canvas_w: float
    canvas_h: float
    ppu: float
    bbox: Tuple[float, float, float, float]   # 源坐标（未居中）
    center: Tuple[float, float]
    parts: List[StaticPart]


def build_static(parts: List[StaticPart], name: str, ppu: float = 1000.0,
                 margin: float = 0.05) -> StaticResult:
    """把 parts 合成一个 moc3（模型空间居中、Y 向上）。"""
    xs = [v[0] for p in parts for v in p.verts]
    ys = [v[1] for p in parts for v in p.verts]
    if not xs:
        raise ValueError("no vertices")
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    cx = (minx + maxx) / 2.0
    cy = (miny + maxy) / 2.0
    w = (maxx - minx) * (1 + 2 * margin)
    h = (maxy - miny) * (1 + 2 * margin)
    canvas_w = w * ppu
    canvas_h = h * ppu

    b = Moc3Builder(canvas_w, canvas_h, ppu=ppu)
    for i, p in enumerate(parts):
        pid = f"Part_{i:02d}_{p.name}"
        part_index = b.add_part(pid)
        verts = [(x - cx, y - cy) for x, y in p.verts]
        # Unity 的 UV 是 v 向上；moc3 的 UV 原点在左上（v 向下），必须翻一次。
        # 依据：官方样例 Koharu 用 (1-v) 采样才正确（见 tools/preview_moc3.py）。
        uvs = [c if k % 2 == 0 else 1.0 - c for k, c in enumerate(p.uvs)]
        b.add_artmesh(f"Art_{i:02d}", part=part_index, texture=0,
                      uvs=uvs, indices=p.indices,
                      keyforms=[ArtMeshKeyform(verts)])

    return StaticResult(b.build(), canvas_w, canvas_h, ppu,
                        (minx, maxx, miny, maxy), (cx, cy), parts)


def write_package(result, name: str, out_dir: Path,
                  texture: Path | None = None,
                  textures: list | None = None) -> Path:
    """写 moc3 + model3.json + 贴图。

    textures: 纹理页列表（多页时按顺序复制成 texture_00/01/…）；
    不传则退回单张 `texture`。
    """
    out_dir = Path(out_dir)
    (out_dir / "textures").mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.moc3").write_bytes(result.moc)
    if textures is None:
        if texture is None:
            for p in result.parts:
                if p.texture:
                    texture = Path(p.texture)
                    break
        textures = [texture] if texture else []
    tex_refs = []
    for i, tex in enumerate(textures):
        if tex and Path(tex).exists():
            fname = f"texture_{i:02d}.png"
            shutil.copyfile(tex, out_dir / "textures" / fname)
            tex_refs.append(f"textures/{fname}")

    model3 = {
        "Version": 3,
        "Name": name,
        "FileReferences": {
            "Moc": f"{name}.moc3",
            "Textures": tex_refs,
            "Physics": None,
            "Pose": None,
            "DisplayInfo": None,
            "Motions": {},
        },
        "Groups": [],
        "HitAreas": [],
    }
    (out_dir / f"{name}.model3.json").write_text(
        json.dumps(model3, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_dir


def verify(result: StaticResult, name: str = "") -> dict:
    """用真实 Core 读回，逐顶点与源数据比对。"""
    from ..moc3 import CubismCore

    core = CubismCore()
    ok = core.consistency(result.moc)
    model = core.load(result.moc) if ok else None
    report = {"name": name, "consistency": ok, "parts": len(result.parts),
              "canvas": [result.canvas_w, result.canvas_h, result.ppu],
              "max_err": None, "checked": 0}
    if model is None:
        return report
    max_err = 0.0
    checked = 0
    cx, cy = result.center
    for i, p in enumerate(result.parts):
        got = model.vertices(i)
        assert len(got) == len(p.verts), (i, len(got), len(p.verts))
        for (gx, gy), (sx, sy) in zip(got, p.verts):
            max_err = max(max_err, abs(gx - (sx - cx)), abs(gy - (sy - cy)))
            checked += 1
    report["max_err"] = max_err
    report["checked"] = checked
    return report
