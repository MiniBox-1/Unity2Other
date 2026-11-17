# -*- coding: utf-8 -*-
r"""Flat-color render of a Spine product (geometry check, no texture)."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from spine_preview import bone_worlds, mesh_points  # noqa: E402

COLORS = [(220, 60, 60), (60, 120, 220), (60, 180, 90), (200, 160, 40),
          (160, 80, 200), (30, 160, 160), (230, 120, 30), (90, 90, 90),
          (200, 60, 160), (100, 160, 60), (60, 60, 200), (180, 100, 100),
          (120, 200, 220), (150, 150, 60)]


def main(js: Path, out: Path, height=800):
    d = json.loads(js.read_text(encoding="utf-8"))
    world, order = bone_worlds(d)
    atts = d["skins"][0]["attachments"]
    items = []
    for slot in d["slots"]:
        name = slot.get("attachment")
        if not name:
            continue
        att = (atts.get(slot["name"]) or {}).get(name)
        if not att or att.get("type") != "mesh":
            continue
        items.append((mesh_points(att, world, order, slot.get("bone")), att))
    xs = [p[0] for pts, _ in items for p in pts]
    ys = [p[1] for pts, _ in items for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    s = height / max(1e-6, maxy - miny)
    W = int((maxx - minx) * s) + 1
    img = Image.new("RGBA", (W, height), (255, 255, 255, 255))
    dr = ImageDraw.Draw(img)
    for i, (pts, att) in enumerate(items):
        pp = [((x - minx) * s, height - (y - miny) * s) for x, y in pts]
        tris = att.get("triangles") or []
        for t in range(0, len(tris) - 2, 3):
            a, b, c = tris[t], tris[t + 1], tris[t + 2]
            dr.polygon([pp[a], pp[b], pp[c]], fill=COLORS[i % len(COLORS)] + (255,),
                       outline=(0, 0, 0, 60))
    img.save(out)
    print("items", len(items), "size", img.size)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]),
         int(sys.argv[3]) if len(sys.argv) > 3 else 800)
