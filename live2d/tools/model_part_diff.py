# -*- coding: utf-8 -*-
r"""Per-part bbox diff: our moc3 drawables vs Unity true skin bounds (by name)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity2live2d.moc3 import CubismCore  # noqa: E402

REF = ROOT / "Products" / "_unity_ref"


def main(name, pkg_dir=""):
    pkg = Path(pkg_dir) if pkg_dir else ROOT / "Products" / name
    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    ref = json.loads((REF / f"{name}.skinbounds.json").read_text(encoding="utf-8"))["parts"]
    by_name = {r["name"]: r for r in ref}

    pid = model.part_ids()
    rows = []
    for i in range(len(model.drawable_ids())):
        pname = pid[i].split("_", 2)[-1] if "_" in pid[i] else pid[i]
        # 找 Unity 里前缀匹配的部件
        hit = None
        for rn in by_name:
            if pname == rn or pname.startswith(rn + "_"):
                hit = rn
                break
        if hit is None:
            continue
        v = model.vertices(i)
        if not v:
            continue
        xs = [a[0] for a in v]
        ys = [a[1] for a in v]
        c = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        s = (max(xs) - min(xs), max(ys) - min(ys))
        r = by_name[hit]
        d = ((c[0] - r["c"][0]) ** 2 + (c[1] - r["c"][1]) ** 2) ** 0.5
        rows.append((d, pname, c, s, r["c"], r["s"]))

    rows.sort(reverse=True)
    print(f"{name}: matched {len(rows)} drawables")
    same = sum(1 for r in rows if r[0] < 0.02)
    print(f"  偏差 <0.02: {same}/{len(rows)}")
    for d, pn, c, s, uc, us in rows[:10]:
        print(f"  d={d:.3f} {pn[:34]:34s} ours c=({c[0]:6.2f},{c[1]:6.2f}) s=({s[0]:4.2f},{s[1]:4.2f})"
              f"  unity c=({uc[0]:6.2f},{uc[1]:6.2f}) s=({us[0]:4.2f},{us[1]:4.2f})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_BR_Khan_N")
