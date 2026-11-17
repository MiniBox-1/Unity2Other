# -*- coding: utf-8 -*-
r"""Diff our model part names against Unity's active renderer names (from mats.json)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity2live2d.moc3 import CubismCore  # noqa: E402

REF = ROOT / "Products" / "_unity_ref"


def src_of(part_id: str) -> str:
    s = part_id
    if s.startswith("Part_"):
        s = s.split("_", 2)[-1]
    for marker in ("_Bone_", "_bone_"):
        if marker in s:
            s = s.split(marker)[0]
    return s


def main(name):
    pkg = ROOT / "Products" / name
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    ours = sorted({src_of(p) for p in model.part_ids()})

    mats = json.loads((REF / f"{name}.mats.json").read_text(encoding="utf-8"))["parts"]
    uni = sorted({p["name"] for p in mats})

    def hit(a, names):
        return any(a == b or a.startswith(b + "_") or b.startswith(a + "_") for b in names)

    missing = [u for u in uni if not hit(u, ours)]
    extra = [o for o in ours if not hit(o, uni)]
    print(f"{name}: ours={len(ours)} unity={len(uni)} missing={len(missing)} extra={len(extra)}")
    print("  missing:", missing[:8])
    print("  extra  :", extra[:8])


if __name__ == "__main__":
    for n in sys.argv[1:] or ["2DModel_3P_Eternity_NS2"]:
        main(n)
