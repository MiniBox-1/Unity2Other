# -*- coding: utf-8 -*-
r"""Software-render a Spine 3.8 JSON product (setup pose) to PNG.

Used as the reference for comparing against our Live2D conversion.

usage: python tools\spine_preview.py <spine_json> <atlas_dir> <out.png> [height]
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def affine(a=1.0, b=0.0, c=0.0, d=1.0, tx=0.0, ty=0.0):
    return (a, b, c, d, tx, ty)


def mul(m, n):
    a, b, c, d, tx, ty = m
    e, f, g, h, ux, uy = n
    return (a * e + c * f, b * e + d * f, a * g + c * h, b * g + d * h,
            a * ux + c * uy + tx, b * ux + d * uy + ty)


def apply(m, p):
    return (m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5])


def _sample(keys, t):
    """线性采样 Spine 时间轴：[{time, value/x/y, curve}]。"""
    if not keys:
        return None
    if t <= keys[0].get("time", 0):
        return keys[0]
    for i in range(len(keys) - 1):
        k0, k1 = keys[i], keys[i + 1]
        t0, t1 = k0.get("time", 0), k1.get("time", 0)
        if t <= t1:
            if t1 <= t0:
                return k1
            a = (t - t0) / (t1 - t0)
            if k0.get("curve") == "stepped":
                return k0
            out = dict(k1)
            for key in ("value", "x", "y", "angle"):
                if key in k0 and key in k1:
                    out[key] = k0[key] + (k1[key] - k0[key]) * a
            return out
    return keys[-1]


def bone_worlds(data, anim=None, t=0.0):
    bones = data.get("bones") or []
    by_name = {b["name"]: b for b in bones}
    order = [b["name"] for b in bones]
    cache = {}
    abones = ((anim or {}).get("bones") or {})

    def get(name):
        if name in cache:
            return cache[name]
        b = by_name[name]
        rot = float(b.get("rotation", 0)) + (
            (_sample((abones.get(name) or {}).get("rotate"), t) or {}).get("angle", 0.0)
            if name in abones else 0.0)
        tx = float(b.get("x", 0))
        ty = float(b.get("y", 0))
        if name in abones and (abones[name].get("translate")):
            tr = _sample(abones[name]["translate"], t) or {}
            tx += tr.get("x", 0.0)
            ty += tr.get("y", 0.0)
        sx = float(b.get("scaleX", 1))
        sy = float(b.get("scaleY", 1))
        r = math.radians(rot)
        local = (math.cos(r) * sx, math.sin(r) * sx,
                 -math.sin(r) * sy, math.cos(r) * sy, tx, ty)
        p = b.get("parent")
        m = mul(get(p), local) if p else local
        cache[name] = m
        return m

    return get, order


def mesh_points(att, world, bone_order, slot_bone=None):
    """Spine 3.8 网格顶点：有权重是 [n,(bone,x,y,w)…]，无权重是扁平 [x,y,…]。"""
    verts = att.get("vertices") or []
    uv_n = len(att.get("uvs") or [])
    if uv_n and len(verts) == uv_n:
        # 扁平：顶点在 slot 骨骼的局部空间
        m = world(slot_bone) if slot_bone else (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        return [apply(m, (verts[i], verts[i + 1])) for i in range(0, len(verts), 2)]

    pts = []
    i = 0
    while i < len(verts):
        n = int(verts[i])
        i += 1
        px = py = 0.0
        for _ in range(n):
            bi = int(verts[i])
            x, y, w = verts[i + 1], verts[i + 2], verts[i + 3]
            i += 4
            q = apply(world(bone_order[bi]), (x, y))
            px += q[0] * w
            py += q[1] * w
        pts.append((px, py))
    return pts


def render(spine_json: Path, atlas_dir: Path, out: Path, height: int = 800,
           anim_name: str | None = None, time: float = 0.0, flip_v: bool = True):
    data = json.loads(Path(spine_json).read_text(encoding="utf-8"))
    anim = (data.get("animations") or {}).get(anim_name) if anim_name else None
    world, bone_order = bone_worlds(data, anim, time)
    skin = (data.get("skins") or [{}])[0]
    atts = skin.get("attachments") or {}
    slots = data.get("slots") or []

    # 图集：优先解析 .atlas（多页 + 区域偏移），否则退回单页
    atlas = None
    pngs = sorted(Path(atlas_dir).glob("*.png"))
    if not pngs:
        raise SystemExit("no texture")
    atlas_path = Path(spine_json).with_suffix("")
    # 同目录下找同名 .atlas（*_static.atlas）
    cand = list(Path(atlas_dir).glob("*.atlas"))
    if cand:
        try:
            from unity2live2d.convert.atlas import load_atlas
            atlas = load_atlas(cand[0])
        except Exception:
            atlas = None

    pages = []
    if atlas:
        for p in atlas.pages:
            ap = Path(atlas_dir) / p
            if not ap.exists():
                ap = pngs[0]
            pages.append(np.asarray(Image.open(ap).convert("RGBA")).astype(np.float32) / 255.0)
    if not pages:
        pages = [np.asarray(Image.open(pngs[0]).convert("RGBA")).astype(np.float32) / 255.0]
    page_sizes = [(p.shape[1], p.shape[0]) for p in pages]

    items = []
    for si, slot in enumerate(slots):
        name = slot.get("attachment")
        if not name:
            continue
        att = (atts.get(slot["name"]) or {}).get(name)
        if not att or att.get("type") != "mesh":
            continue
        pts = mesh_points(att, world, bone_order, slot.get("bone"))
        uvs = att.get("uvs") or []
        tris = att.get("triangles") or []
        if not pts or not tris:
            continue
        region = None
        if atlas:
            rname = att.get("path") or name
            region = atlas.regions.get(rname) or atlas.regions.get(name)
        items.append((si, pts, uvs, tris, region))

    xs = [p[0] for _, pts, _, _, _ in items for p in pts]
    ys = [p[1] for _, pts, _, _, _ in items for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    scale = height / max(1e-6, (maxy - miny))
    W = max(1, int(round((maxx - minx) * scale)))
    H = height

    canvas = np.zeros((H, W, 4), np.float32)

    def to_px(x, y):
        return ((x - minx) * scale, H - (y - miny) * scale)

    for si, pts, uvs, tris, region in items:
        pp = [to_px(x, y) for x, y in pts]
        for t in range(0, len(tris) - 2, 3):
            a, b, c = tris[t], tris[t + 1], tris[t + 2]
            (x0, y0), (x1, y1), (x2, y2) = pp[a], pp[b], pp[c]
            minx2 = max(0, int(np.floor(min(x0, x1, x2))))
            maxx2 = min(W - 1, int(np.ceil(max(x0, x1, x2))))
            miny2 = max(0, int(np.floor(min(y0, y1, y2))))
            maxy2 = min(H - 1, int(np.ceil(max(y0, y1, y2))))
            if minx2 > maxx2 or miny2 > maxy2:
                continue
            den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(den) < 1e-12:
                continue
            ys2, xs2 = np.mgrid[miny2:maxy2 + 1, minx2:maxx2 + 1]
            xs2 = xs2.astype(np.float32) + 0.5
            ys2 = ys2.astype(np.float32) + 0.5
            w0 = ((y1 - y2) * (xs2 - x2) + (x2 - x1) * (ys2 - y2)) / den
            w1 = ((y2 - y0) * (xs2 - x2) + (x0 - x2) * (ys2 - y2)) / den
            w2 = 1.0 - w0 - w1
            mask = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not mask.any():
                continue
            u = (w0 * uvs[a * 2] + w1 * uvs[b * 2] + w2 * uvs[c * 2])[mask]
            v = (w0 * uvs[a * 2 + 1] + w1 * uvs[b * 2 + 1] + w2 * uvs[c * 2 + 1])[mask]
            pg = region.page if region is not None else 0
            pg = max(0, min(pg, len(pages) - 1))
            tex = pages[pg]
            th, tw = page_sizes[pg][1], page_sizes[pg][0]
            if region is None:
                px = u * tw
                py = (1.0 - v) * th if flip_v else v * th
            else:
                px = region.x + u * region.w
                py = (region.y + (1.0 - v) * region.h) if flip_v else (region.y + v * region.h)
            tx = np.clip(px.astype(np.int32), 0, tw - 1)
            ty = np.clip(py.astype(np.int32), 0, th - 1)
            src = tex[ty, tx]
            yy = ys2[mask].astype(np.int32)
            xx = xs2[mask].astype(np.int32)
            dst = canvas[yy, xx]
            a_s = src[:, 3:4]
            canvas[yy, xx, :3] = src[:, :3] * a_s + dst[:, :3] * (1 - a_s)
            canvas[yy, xx, 3] = a_s[:, 0] + dst[:, 3] * (1 - a_s[:, 0])

    img = Image.fromarray((np.clip(canvas, 0, 1) * 255).astype(np.uint8), "RGBA")
    img.save(out)
    return {"size": img.size, "items": len(items), "bbox": (minx, maxx, miny, maxy)}


if __name__ == "__main__":
    h = int(sys.argv[4]) if len(sys.argv) > 4 else 800
    an = sys.argv[5] if len(sys.argv) > 5 else None
    tt = float(sys.argv[6]) if len(sys.argv) > 6 else 0.0
    print(render(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), h, an, tt))
