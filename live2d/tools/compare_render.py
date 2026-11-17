# -*- coding: utf-8 -*-
r"""Compare Live2D package render vs Spine product render (silhouette IoU).

usage:
  python tools\compare_render.py <CharName> [--out PNG]
  python tools\compare_render.py --all [--limit N]
"""
import argparse
import io
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from preview_moc3 import render_package  # noqa: E402
from spine_preview import render as spine_render  # noqa: E402

PRODUCTS = ROOT / "Products"
SPINE = Path(r"D:\VB\Convert\Spine\MultiSpine\LO\Products\Current")


def _fit(img: Image.Image, height=512) -> Image.Image:
    a = np.array(img.convert("RGBA"))[:, :, 3]
    ys, xs = np.where(a > 8)
    if len(xs) == 0:
        return Image.new("RGBA", (1, height))
    box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    crop = img.convert("RGBA").crop(box)
    s = height / max(1, crop.height)
    return crop.resize((max(1, int(crop.width * s)), height), Image.LANCZOS)


def _mask(img: Image.Image, size=(512, 512), target_area=45000) -> np.ndarray:
    """按「面积 + 质心」归一化，比按包围盒更抗远端碎片。"""
    a = np.array(img.convert("RGBA"))[:, :, 3] > 8
    ys, xs = np.where(a)
    canvas = np.zeros(size, bool)
    if len(xs) == 0:
        return canvas
    # 按面积缩放
    s = math.sqrt(target_area / max(1, len(xs)))
    # 裁剪到内容，再缩放
    sub = img.convert("RGBA").crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    w = max(1, int(round(sub.width * s)))
    h = max(1, int(round(sub.height * s)))
    sub = sub.resize((w, h), Image.LANCZOS)
    m = np.array(sub)[:, :, 3] > 8
    # 质心对齐到画布中心
    ys2, xs2 = np.where(m)
    cx = (xs2.min() + xs2.max()) / 2.0 if len(xs2) else 0
    cy = (ys2.min() + ys2.max()) / 2.0 if len(ys2) else 0
    ox = int(round(size[0] / 2 - cx))
    oy = int(round(size[1] / 2 - cy))
    ys3, xs3 = np.where(m)
    ys3 = ys3 + oy
    xs3 = xs3 + ox
    ok = (ys3 >= 0) & (ys3 < size[1]) & (xs3 >= 0) & (xs3 < size[0])
    canvas[ys3[ok], xs3[ok]] = True
    return canvas


def _eval_segments(seg, t):
    if not seg:
        return 0.0
    if t <= seg[0]:
        return seg[1]
    i = 2
    while i + 2 < len(seg):
        kind = int(seg[i]); t1 = seg[i + 1]; v1 = seg[i + 2]
        if t <= t1:
            t0 = seg[i - 2]; v0 = seg[i - 1]
            if kind == 2:
                return v0
            if t1 <= t0:
                return v1
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
        i += 3
    return seg[-1]


def _render_l2d_motion(m3_path: Path, motion: str, t: float, out: Path, height: int):
    """按 motion3 在时刻 t 设参数后渲染（复用软件光栅化）。"""
    from unity2live2d.moc3 import CubismCore
    from preview_moc3 import render_model

    m3 = json.loads(Path(m3_path).read_text(encoding="utf-8"))
    base = Path(m3_path).parent
    core = CubismCore()
    model = core.load((base / m3["FileReferences"]["Moc"]).read_bytes())
    entry = (m3["FileReferences"].get("Motions") or {}).get(motion)
    if entry and model is not None:
        mot = json.loads((base / entry[0]["File"]).read_text(encoding="utf-8"))
        for c in mot.get("Curves", []):
            model.set_param(c["Id"], _eval_segments(c["Segments"], t))
        model.update()
        texs = [base / x for x in (m3["FileReferences"].get("Textures") or [])]
        img, _ = render_model(model, texs, height, True)
        img.save(out)
        return
    render_package(m3_path, out, height)


def compare(name: str, save: Path | None = None, motion: str = "", time: float = 0.0) -> dict:
    pkg = PRODUCTS / name
    m3 = pkg / f"{name}.model3.json"
    if not m3.exists():
        return {"name": name, "error": "no live2d package"}
    base = SPINE / f"{name}.uAnim"
    js = next((p for p in base.glob("*.json") if p.name.endswith("_static.json")), None) \
        if base.exists() else None
    if js is None:
        return {"name": name, "error": "no spine product"}

    # Spine 产物完整度：mesh 数 vs 我们的源部件数（产物可能只导出了部分部件）
    spine_meshes = 0
    try:
        sd = json.loads(js.read_text(encoding="utf-8"))
        for items in (sd.get("skins") or [{}])[0].get("attachments", {}).values():
            spine_meshes += sum(1 for a in items.values() if a.get("type") == "mesh")
    except Exception:
        pass
    src_parts = None
    mf = pkg / "manifest.json"
    if mf.exists():
        try:
            src_parts = json.loads(mf.read_text(encoding="utf-8")).get("source_parts")
        except Exception:
            pass

    l2d_png = pkg / "_cmp_l2d.png"
    m3j = json.loads(m3.read_text(encoding="utf-8"))
    if motion and (m3j["FileReferences"].get("Motions") or {}).get(motion):
        _render_l2d_motion(m3, motion, time, l2d_png, 512)
    else:
        render_package(m3, l2d_png, 512)
    l2d = Image.open(l2d_png)

    sp_png = pkg / "_cmp_spine.png"
    spine_render(js, base, sp_png, 512, motion or None, time, False)
    sp = Image.open(sp_png)

    ma, mb = _mask(l2d), _mask(sp)
    inter = np.logical_and(ma, mb).sum()
    union = np.logical_or(ma, mb).sum()
    iou = float(inter) / max(1, union)

    if save:
        canvas = Image.new("RGBA", (1024, 512), (255, 255, 255, 255))
        canvas.paste(_fit(l2d, 512), (0, 0))
        canvas.paste(_fit(sp, 512), (512, 0))
        canvas.save(save)
    cover = float(inter) / max(1, mb.sum())        # Spine 被 L2D 覆盖的比例
    return {"name": name, "iou": round(iou, 3), "cover": round(cover, 3),
            "spine_meshes": spine_meshes, "src_parts": src_parts,
            "l2d_area": int(ma.sum()), "spine_area": int(mb.sum())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="")
    ap.add_argument("--motion", default="")
    ap.add_argument("--time", type=float, default=0.0)
    args = ap.parse_args()

    if args.all:
        names = sorted(p.name for p in PRODUCTS.iterdir()
                       if p.is_dir() and (p / f"{p.name}.model3.json").exists())
        if args.limit:
            names = names[:args.limit]
        rows = []
        for n in names:
            r = compare(n, motion=args.motion, time=args.time)
            rows.append(r)
            print(f"{r.get('iou', '-')!s:>6}  {n}  {r.get('error', '')}")
        out = PRODUCTS / "_compare_report.json"
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print("report:", out)
    else:
        print(compare(args.name, Path(args.out) if args.out else None,
                      args.motion, args.time))


if __name__ == "__main__":
    main()
