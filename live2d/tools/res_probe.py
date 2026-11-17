# -*- coding: utf-8 -*-
r"""Does rendering our model at higher resolution change the IoU vs Unity?"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import unity_iou_audit as A  # noqa: E402
from unity2live2d.moc3 import CubismCore  # noqa: E402
from preview_moc3 import render_model  # noqa: E402


def cmp_mask(a, b):
    h = max(a.shape[0], b.shape[0])
    w = max(a.shape[1], b.shape[1])
    oa = np.zeros((h, w), bool)
    ob = np.zeros((h, w), bool)
    oa[:a.shape[0], :a.shape[1]] = a
    ob[:b.shape[0], :b.shape[1]] = b
    return float((oa & ob).sum() / max(1, (oa | ob).sum()))


def main(names, heights=(512, 1024, 2048)):
    for n in names:
        pkg = ROOT / "Products" / n
        m3 = json.loads((pkg / f"{n}.model3.json").read_text(encoding="utf-8"))
        core = CubismCore()
        model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
        texs = [pkg / t for t in m3["FileReferences"]["Textures"]]
        ref = A.mask(ROOT / "Products" / "_unity_ref_nat" / f"{n}.png")
        line = [n[:26]]
        for H in heights:
            img, _ = render_model(model, texs, H, True)
            tmp = ROOT / "Products" / "_tmp_render.png"
            img.save(tmp)
            o = A.mask(tmp)
            line.append(f"H{H}={cmp_mask(o, ref):.3f}")
        print("  ".join(line))


if __name__ == "__main__":
    main(sys.argv[1:] or ["2DModel_BR_Amy_NS1"])
