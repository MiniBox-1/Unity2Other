# -*- coding: utf-8 -*-
r"""List model drawables that occupy an extreme x region (fraction of canvas)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity2live2d.moc3 import CubismCore  # noqa: E402


def main(name, side="right", thr=0.75):
    pkg = ROOT / "Products" / name
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    w, h, ox, oy, ppu = model.canvas()
    x0 = (0 - ox) / ppu
    x1 = (w - ox) / ppu
    cut = x0 + (x1 - x0) * (thr if side == "right" else 1 - thr)
    pid = model.part_ids()
    hits = []
    for i in range(len(pid)):
        v = model.vertices(i)
        if not v:
            continue
        cx = sum(a[0] for a in v) / len(v)
        if (side == "right" and cx > cut) or (side == "left" and cx < cut):
            xs = [a[0] for a in v]
            hits.append((cx, i, pid[i], max(xs) - min(xs)))
    hits.sort(reverse=(side == "right"))
    print(f"{name}: {len(hits)} drawables in {side} region (cut={cut:.2f})")
    for cx, i, p, wdt in hits[:10]:
        print(f"  cx={cx:6.2f} w={wdt:5.2f} #{i} {p[:52]}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "right")
