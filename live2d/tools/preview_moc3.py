# -*- coding: utf-8 -*-
r"""Software preview of a moc3 + texture (no GL), for quick visual checks.

usage: python tools\preview_moc3.py <model.moc3> <texture.png> <out.png> [height]
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from unity2live2d.moc3 import CubismCore  # noqa: E402


def render(moc: Path, texture: Path, out: Path, height: int = 900,
           flip_v: bool = True) -> dict:
    core = CubismCore()
    data = Path(moc).read_bytes()
    model = core.load(data)
    if model is None:
        raise SystemExit("consistency check failed")
    img, info = render_model(model, texture, height, flip_v)
    img.save(out)
    return info


def render_model(model, texture, height: int = 900,
                 flip_v: bool = True):
    """把一个已加载（可已设参数）的模型光栅化成 PIL.Image。

    texture 可以是单张路径，也可以是按 texture index 排列的列表（多图集）。
    """
    w, h, ox, oy, ppu = model.canvas()
    scale = height / h
    W = max(1, int(round(w * scale)))
    H = height

    paths = texture if isinstance(texture, (list, tuple)) else [texture]
    pages = []
    for p in paths:
        arr = np.asarray(Image.open(p).convert("RGBA")).astype(np.float32) / 255.0
        pages.append((arr, arr.shape[1], arr.shape[0]))
    if not pages:
        raise SystemExit("no texture")

    canvas = np.zeros((H, W, 4), np.float32)

    def to_px(x, y):
        px = (x * ppu + ox) * scale
        py = H - (y * ppu + oy) * scale
        return px, py

    n = len(model.drawable_ids())
    order = sorted(range(n), key=lambda i: model.drawable(i)["render_order"])
    for i in order:
        tex_idx = int(model.drawable(i).get("texture", 0)) if hasattr(model, "drawable") else 0
        tex, tw, th = pages[min(tex_idx, len(pages) - 1)]
        verts = model.vertices(i)
        uvs = model.uvs(i)
        idx = model.indices(i)
        pts = [to_px(x, y) for x, y in verts]
        for t in range(0, len(idx), 3):
            a, b, c = idx[t], idx[t + 1], idx[t + 2]
            (x0, y0), (x1, y1), (x2, y2) = pts[a], pts[b], pts[c]
            minx = max(0, int(np.floor(min(x0, x1, x2))))
            maxx = min(W - 1, int(np.ceil(max(x0, x1, x2))))
            miny = max(0, int(np.floor(min(y0, y1, y2))))
            maxy = min(H - 1, int(np.ceil(max(y0, y1, y2))))
            if minx > maxx or miny > maxy:
                continue
            den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(den) < 1e-12:
                continue
            ys, xs = np.mgrid[miny:maxy + 1, minx:maxx + 1]
            xs = xs.astype(np.float32) + 0.5
            ys = ys.astype(np.float32) + 0.5
            w0 = ((y1 - y2) * (xs - x2) + (x2 - x1) * (ys - y2)) / den
            w1 = ((y2 - y0) * (xs - x2) + (x0 - x2) * (ys - y2)) / den
            w2 = 1.0 - w0 - w1
            mask = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not mask.any():
                continue
            u = (w0 * uvs[a][0] + w1 * uvs[b][0] + w2 * uvs[c][0])[mask]
            v = (w0 * uvs[a][1] + w1 * uvs[b][1] + w2 * uvs[c][1])[mask]
            tx = np.clip((u * tw).astype(np.int32), 0, tw - 1)
            vy = (1.0 - v) if flip_v else v
            ty = np.clip((vy * th).astype(np.int32), 0, th - 1)
            src = tex[ty, tx]
            yy = ys[mask].astype(np.int32)
            xx = xs[mask].astype(np.int32)
            dst = canvas[yy, xx]
            a_s = src[:, 3:4]
            canvas[yy, xx, :3] = src[:, :3] * a_s + dst[:, :3] * (1 - a_s)
            canvas[yy, xx, 3] = a_s[:, 0] + dst[:, 3] * (1 - a_s[:, 0])

    out_img = Image.fromarray((np.clip(canvas, 0, 1) * 255).astype(np.uint8), "RGBA")
    return out_img, {"size": (W, H), "drawables": n, "canvas": (w, h, ppu)}


def render_package(model3_path: Path, out: Path, height: int = 900) -> dict:
    """从 model3.json 渲染完整包（支持多张纹理页）。"""
    import json

    m3 = json.loads(Path(model3_path).read_text(encoding="utf-8"))
    base = Path(model3_path).parent
    moc = base / m3["FileReferences"]["Moc"]
    textures = [base / t for t in (m3["FileReferences"].get("Textures") or [])]
    core = CubismCore()
    model = core.load(moc.read_bytes())
    if model is None:
        raise SystemExit("consistency check failed")
    img, info = render_model(model, textures, height, True)
    img.save(out)
    return info


if __name__ == "__main__":
    if str(sys.argv[1]).endswith(".model3.json"):
        pkg, out = Path(sys.argv[1]), Path(sys.argv[2])
        hgt = int(sys.argv[3]) if len(sys.argv) > 3 else 900
        print(render_package(pkg, out, hgt))
    else:
        moc, texture, out = (Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
        hgt = int(sys.argv[4]) if len(sys.argv) > 4 else 900
        print(render(moc, texture, out, hgt))
