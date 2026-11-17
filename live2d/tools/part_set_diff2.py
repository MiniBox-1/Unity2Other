# -*- coding: utf-8 -*-
r"""Diff a given package's part names against Unity mats names (normalized)."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity2live2d.moc3 import CubismCore  # noqa: E402

REF = ROOT / "Products" / "_unity_ref"


def norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"_+", "_", s)
    s = re.sub(r"\d+$", "", s)
    return s.strip("_")


def src_of(pid: str) -> str:
    s = pid
    if s.startswith("Part_"):
        s = s.split("_", 2)[-1]
    for marker in ("_bone_", "_Bone_"):
        if marker.lower() in s.lower():
            i = s.lower().find(marker.lower())
            s = s[:i]
    return s


def main(name, pkg_dir):
    pkg = Path(pkg_dir)
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    ours = {norm(src_of(p)) for p in model.part_ids()}

    mats = json.loads((REF / f"{name}.mats.json").read_text(encoding="utf-8"))["parts"]
    uni = {norm(p["name"]): p["name"] for p in mats}

    missing = sorted({v for k, v in uni.items() if k not in ours})
    print(f"{name}: ours={len(ours)} unity={len(uni)} missing={len(missing)}")
    for m in missing[:12]:
        print("   ", m)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
