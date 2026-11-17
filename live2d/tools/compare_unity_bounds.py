# -*- coding: utf-8 -*-
r"""Compare Unity ground-truth renderer bounds with our extracted part bounds."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model)

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")
REF = ROOT / "Products" / "_unity_ref"


def main(name):
    ref_file = REF / f"{name}.skinbounds.json"
    if not ref_file.exists():
        ref_file = REF / f"{name}.bounds.json"
    if not ref_file.exists():
        raise SystemExit(f"no unity bounds: {ref_file}")
    ref = json.loads(ref_file.read_text(encoding="utf-8"))["parts"]
    mdl, parts = build_character_model(
        str(PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"), str(PROJ / "Assets"))
    w = _world_matrices(mdl, {})
    ours = {p.name: p for p in parts}

    # Unity 的名字没有 `_<idx>` 后缀（我们的是 `name_02` 这种）
    by_prefix = {}
    for pname, p in ours.items():
        key = pname
        for r in ref:
            if pname == r["name"] or pname.startswith(r["name"] + "_"):
                key = r["name"]
                break
        by_prefix.setdefault(key, []).append(p)

    rows = []
    for r in ref:
        plist = by_prefix.get(r["name"]) or []
        if not plist:
            continue
        p = plist[0]
        v = _skin_mesh(p, p.mesh, w)
        if not v:
            continue
        xs = [a[0] for a in v]
        ys = [a[1] for a in v]
        cx = (min(xs) + max(xs)) / 2
        cy = (min(ys) + max(ys)) / 2
        dx = r["c"][0] - cx
        dy = r["c"][1] - cy
        rows.append((dx * dx + dy * dy, r["name"], r["c"], r["s"], (cx, cy),
                     (max(xs) - min(xs), max(ys) - min(ys))))

    rows.sort(reverse=True)
    print(f"{name}: matched {len(rows)} / unity {len(ref)}")
    print("--- 偏差最大的 10 个 ---")
    for d2, nm, c, s, o, sz in rows[:10]:
        print(f"  {nm[:28]:28s} d={d2 ** 0.5:7.3f}  unity c=({c[0]:7.3f},{c[1]:7.3f}) "
              f"s=({s[0]:5.2f},{s[1]:5.2f})  ours c=({o[0]:7.3f},{o[1]:7.3f}) "
              f"s=({sz[0]:5.2f},{sz[1]:5.2f})")
    same = sum(1 for r in rows if r[0] < 0.01)
    print(f"偏差 <0.1 的部件: {same}/{len(rows)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2DModel_BR_Khan_N")
