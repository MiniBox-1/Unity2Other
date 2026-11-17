# -*- coding: utf-8 -*-
r"""Compare our kept parts with Unity's active/inactive renderer names."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity2live2d.moc3 import CubismCore  # noqa: E402


def src_of(pid):
    s = pid
    if s.startswith("Part_"):
        s = s.split("_", 2)[-1]
    for m in ("_Bone_", "_bone_"):
        if m in s:
            s = s.split(m)[0]
    return s


def main(name):
    pkg = ROOT / "Products" / name
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    ours = {src_of(p) for p in model.part_ids()}

    hier = json.loads((ROOT / "Products" / "_unity_ref" / f"{name}.hier.json")
                      .read_text(encoding="utf-8"))["parts"]
    act = {p["name"] for p in hier if p["active"]}
    inact = {p["name"] for p in hier if not p["active"]}

    def hit(nm, pool):
        return any(nm == b or nm.startswith(b + "_") or b.startswith(nm + "_") for b in pool)

    kept_but_inactive = sorted(o for o in ours if hit(o, inact) and not hit(o, act))
    missing_active = sorted(a for a in act if not hit(a, ours))
    print(f"{name}: ours={len(ours)} unity_active={len(act)}")
    print(f"  ours 里 Unity 是 inactive 的: {len(kept_but_inactive)}")
    for k in kept_but_inactive[:10]:
        print("    ", k[:48])
    print(f"  Unity active 但我们没有的: {len(missing_active)}")
    for k in missing_active[:10]:
        print("    ", k[:48])


if __name__ == "__main__":
    for n in sys.argv[1:]:
        main(n)
