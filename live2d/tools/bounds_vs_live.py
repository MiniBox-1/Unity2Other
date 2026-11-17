# -*- coding: utf-8 -*-
r"""Compare our model's per-part bbox with Unity's live per-part bounds."""
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
    live = {p["n"]: p for p in json.loads(
        (ROOT / "Products" / "_unity_rt" / f"{name}.json").read_text(encoding="utf-8"))["parts"]}

    rows = []
    for i, pid in enumerate(model.part_ids()):
        d = model.drawable(i)
        vs = model.vertices(i)
        xs = [v[0] for v in vs]
        ys = [v[1] for v in vs]
        if not xs:
            continue
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        key = None
        s = src_of(pid)
        for k in live:
            if s == k or s.startswith(k + "_") or k.startswith(s):
                key = k
                break
        if key is None:
            continue
        l = live[key]
        lc = ((l["min"][0] + l["max"][0]) / 2, (l["min"][1] + l["max"][1]) / 2)
        rows.append((pid, cx, cy, lc[0], lc[1]))
    print(f"{name}: matched {len(rows)}")
    for pid, cx, cy, ux, uy in rows[:10]:
        print(f"  {pid[:42]:42s} ours=({cx:.3f},{cy:.3f}) unity=({ux:.3f},{uy:.3f})")
    if rows:
        import statistics
        dx = statistics.median(abs(r[1] - r[3]) for r in rows)
        dy = statistics.median(abs(r[2] - r[4]) for r in rows)
        print(f"  median |dx|={dx:.3f} |dy|={dy:.3f}")


if __name__ == "__main__":
    main(sys.argv[1])
