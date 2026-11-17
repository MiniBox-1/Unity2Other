# -*- coding: utf-8 -*-
r"""Render a motion3 onto a moc3 into a filmstrip (software rasterizer).

usage: python tools\render_motion_frames.py <model3.json> <MotionName> <out.png> [frames] [height]
"""
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from unity2live2d.moc3 import CubismCore  # noqa: E402
from preview_moc3 import render_model  # noqa: E402


def eval_segments(seg, t):
    """motion3 Segments: [t0,v0, type, t1,v1, type, ...]（只实现 Linear/Stepped）。"""
    if not seg:
        return 0.0
    if t <= seg[0]:
        return seg[1]
    i = 2
    while i + 3 < len(seg) + 1:
        if i >= len(seg):
            break
        kind = int(seg[i]) if i < len(seg) else 0
        t1 = seg[i + 1]
        v1 = seg[i + 2]
        if t <= t1:
            t0 = seg[i - 2]
            v0 = seg[i - 1]
            if kind == 2:                    # stepped
                return v0
            if t1 <= t0:
                return v1
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
        i += 3
    return seg[-1]


def main():
    model3_path = Path(sys.argv[1])
    motion_name = sys.argv[2]
    out = Path(sys.argv[3])
    n_frames = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    height = int(sys.argv[5]) if len(sys.argv) > 5 else 700

    base = model3_path.parent
    m3 = json.loads(model3_path.read_text(encoding="utf-8"))
    moc = base / m3["FileReferences"]["Moc"]
    tex = base / m3["FileReferences"]["Textures"][0]
    motion_rel = m3["FileReferences"]["Motions"][motion_name][0]["File"]
    motion = json.loads((base / motion_rel).read_text(encoding="utf-8"))

    core = CubismCore()
    model = core.load(moc.read_bytes())
    if model is None:
        raise SystemExit("moc3 consistency failed")

    known = set(model.parameter_ids())
    unknown = [c["Id"] for c in motion["Curves"] if c["Id"] not in known]
    print(f"curves={len(motion['Curves'])} unknown_params={unknown[:5]} "
          f"duration={motion['Meta']['Duration']}")

    duration = float(motion["Meta"]["Duration"])
    frames = [duration * i / max(1, n_frames - 1) for i in range(n_frames)]
    imgs = []
    for t in frames:
        for c in motion["Curves"]:
            if c["Id"] in known:
                model.set_param(c["Id"], eval_segments(c["Segments"], t))
        model.update()
        img, _ = render_model(model, tex, height, True)
        imgs.append(img)
        print(f"  t={t:5.2f} rendered")

    w, h = imgs[0].size
    strip = Image.new("RGBA", (w * len(imgs), h), (255, 255, 255, 255))
    for i, im in enumerate(imgs):
        strip.paste(im, (i * w, 0), im)
    strip.save(out)
    print("out:", out, strip.size)


if __name__ == "__main__":
    main()
