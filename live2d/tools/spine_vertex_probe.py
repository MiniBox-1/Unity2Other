# -*- coding: utf-8 -*-
r"""Check whether Spine mesh vertices are bone-local: distance from bone origin."""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spine_preview import apply, bone_worlds  # noqa: E402


def main(js: Path, key: str):
    d = json.loads(Path(js).read_text(encoding="utf-8"))
    world, order = bone_worlds(d)
    atts = d["skins"][0]["attachments"]
    att = None
    for slot, items in atts.items():
        if key in items:
            att = items[key]
            break
    v = att["vertices"]
    i = 0
    shown = 0
    while i < len(v) and shown < 6:
        n = int(v[i]); i += 1
        rec = []
        for _ in range(n):
            bi, x, y, w = int(v[i]), v[i + 1], v[i + 2], v[i + 3]
            i += 4
            rec.append((bi, x, y, w))
        if n == 1:
            bi, x, y, w = rec[0]
            bx, by = apply(world(order[bi]), (0, 0))
            px, py = apply(world(order[bi]), (x, y))
            print(f"bone={order[bi][:22]:22s} local=({x:8.1f},{y:8.1f}) "
                  f"world=({px:8.1f},{py:8.1f}) boneOrigin=({bx:8.1f},{by:8.1f}) "
                  f"d={math.hypot(px-bx, py-by):8.1f}")
            shown += 1
        else:
            shown += 1


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2])
