# -*- coding: utf-8 -*-
r"""Compare moc3 drawable bboxes against extraction world bboxes (same names)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
U2S = Path(r"D:\VB\Convert\Spine\SingleSpine\Shared\Unity2Spine\src")
sys.path.insert(0, str(U2S))

from unity2spine.convert.convert_2dmodel import (  # noqa: E402
    _skin_mesh, _world_matrices, build_character_model)
from unity2live2d.moc3 import CubismCore  # noqa: E402

PROJ = Path(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old")


def main(name, pkg):
    mdl, parts = build_character_model(
        str(PROJ / "Assets" / "Prefabs" / f"{name}.uAnim.prefab"), str(PROJ / "Assets"))
    world = _world_matrices(mdl, {})
    ext = {}
    for p in parts:
        v = _skin_mesh(p, p.mesh, world)
        if not v:
            continue
        xs = [a[0] for a in v]
        ys = [a[1] for a in v]
        ext[p.name] = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                       max(xs) - min(xs), max(ys) - min(ys))

    m3 = json.loads((pkg / f"{name}.model3.json").read_text(encoding="utf-8"))
    core = CubismCore()
    model = core.load((pkg / m3["FileReferences"]["Moc"]).read_bytes())
    pid = model.part_ids()
    for i in range(min(6, len(pid))):
        src = pid[i].split("_", 2)[-1]
        for marker in ("_Bone_", "_bone_"):
            if marker in src:
                src = src.split(marker)[0]
        e = ext.get(src)
        v = model.vertices(i)
        xs = [a[0] for a in v]
        ys = [a[1] for a in v]
        print(f"{src[:30]:30s} model c=({(min(xs)+max(xs))/2:6.2f},{(min(ys)+max(ys))/2:6.2f}) "
              f"s=({max(xs)-min(xs):5.2f},{max(ys)-min(ys):5.2f}) | "
              f"extract c=({e[0]:6.2f},{e[1]:6.2f}) s=({e[2]:5.2f},{e[3]:5.2f})" if e else
              f"{src[:30]:30s} model s=({max(xs)-min(xs):5.2f}) | extract: none")


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]))
