# -*- coding: utf-8 -*-
r"""Build each UV-variant model and score it under both preview flip modes."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import json
from unity2live2d.moc3 import CubismCore  # noqa: E402
from preview_moc3 import render_model  # noqa: E402
import unity_iou_audit as A  # noqa: E402

REF = ROOT / "Products" / "_unity_ref_nat"


def score(pkg, name, flip):
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    texs = [pkg / t for t in (m3["FileReferences"].get("Textures") or [])]
    img, _ = render_model(model, texs, 512, flip)
    tmp = ROOT / "Products" / f"_tmp_{name}_{int(flip)}.png"
    img.save(tmp)
    ref = REF / f"{name}.png"
    if not ref.exists():
        return None
    return A.iou(A.mask(tmp), A.mask(ref))


def main(names):
    for n in names:
        for tag, d in (("uvfix", ROOT / "Products" / n), ("nouv", ROOT / "Products" / "_uv0" / n)):
            if not (d / f"{n}.model3.json").exists():
                continue
            a = score(d, n, True)
            b = score(d, n, False)
            print(f"{n[:38]:38s} {tag:6s} flip={a if a is None else round(a,3)} "
                  f"noflip={b if b is None else round(b,3)}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["2DModel_3P_Alexandra_N", "2DModel_BR_Brownie_NS1"])
