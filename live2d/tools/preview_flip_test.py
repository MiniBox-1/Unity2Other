# -*- coding: utf-8 -*-
r"""Render one package with flip_v True/False to check texture orientation."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from unity2live2d.moc3 import CubismCore  # noqa: E402
from preview_moc3 import render_model  # noqa: E402


def main(name):
    pkg = ROOT / "Products" / name
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    texs = [pkg / t for t in m3["FileReferences"]["Textures"]]
    for flip in (True, False):
        img, info = render_model(model, texs, 600, flip)
        out = ROOT / "Products" / f"_{name}_{'flip' if flip else 'noflip'}.png"
        img.save(out)
        print(flip, out.name, info)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_BR_Khan_N")
