# -*- coding: utf-8 -*-
r"""Use the official Spine runtime binding to get authoritative vertex positions."""
import sys
from pathlib import Path

VIEWER = Path(r"D:\VB\Viewer\newViwer")
sys.path.insert(0, str(VIEWER))
sys.path.insert(0, str(VIEWER / "cWidgets" / "Render" / "Spine"))

import importlib.util  # noqa: E402

_op = VIEWER / "cWidgets" / "Render" / "Spine" / "SpineOperator.py"
_spec = importlib.util.spec_from_file_location("SpineOperator", _op)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["SpineOperator"] = _mod
_spec.loader.exec_module(_mod)
SpineInstance = _mod.SpineInstance


def main(product: Path):
    skel = next(p for p in product.glob("*.json") if p.name.endswith("_static.json"))
    atlas = next(product.glob("*.atlas"))
    inst = SpineInstance(str(skel), [str(atlas)], mixTime=0)
    inst.SetToSetupPose()
    inst.UpdateWorldTransform()
    buf = inst.getGLBuffer()
    print("glArray attrs:", [a for a in dir(buf) if not a.startswith("_")])
    ibo = buf.getIbo()
    print("ibo attrs:", [a for a in dir(ibo) if not a.startswith("_")])
    return inst, buf


if __name__ == "__main__":
    main(Path(sys.argv[1]))
