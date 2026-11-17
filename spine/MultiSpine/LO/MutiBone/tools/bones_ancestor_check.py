# -*- coding: utf-8 -*-
r"""查多骨骼骨表的隐患：**保留的骨，其 Unity 父链上是否有被剔除的节点**（非平面/退化）。

有 ⇒ 那层变换丢了，该骨及其后代/部件会整体错位（与"探针 quad 正常、真实部件散开"吻合）。

用法：python _scratch\bones_ancestor_check.py <prefab>
"""
import os
import sys

LIB = r"D:\VB\Unity2Spine"
sys.path.insert(0, LIB)
sys.path.insert(0, os.path.join(LIB, "src"))

from unity2spine.convert.static_prefab_spine import (  # noqa: E402
    load_character, _sample_world_multi, assignments_for_entry, make_samplers,
    enumerate_clips)

ASSETS = r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Assets"
SCENE = os.path.join(ASSETS, "Sences", "save.unity")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    mdl, parts = load_character(sys.argv[1], ASSETS, SCENE)
    es = enumerate_clips(mdl, ASSETS)
    sm = make_samplers(mdl, es)
    w = _sample_world_multi(mdl, assignments_for_entry(mdl, sm, es, es[0]), 0.0)

    def mat(tf):
        v = [float(x) for x in list(w.get(tf) or [])]
        return v if len(v) >= 16 else None

    def planar(tf):
        v = mat(tf)
        return bool(v) and abs(v[2]) < 1e-4 and abs(v[6]) < 1e-4 \
            and abs(v[8]) < 1e-4 and abs(v[9]) < 1e-4

    def alive(tf):
        v = mat(tf)
        if not v:
            return False
        return ((v[0] ** 2 + v[4] ** 2) ** 0.5 > 1e-4
                and (v[1] ** 2 + v[5] ** 2) ** 0.5 > 1e-4)

    need = set()

    def add(tf):
        cur, h = tf, 0
        while cur is not None and h < 300:
            if cur in need:
                break
            if not (planar(cur) and alive(cur)):
                break
            need.add(cur)
            cur = (mdl.transforms.get(cur) or {}).get("father")
            h += 1

    for p in parts:
        if not (p.mesh or p.kind == "sprite"):
            continue
        bs = [b for b in (getattr(p, "bones", None) or []) if b]
        for b in (bs or [p.tfid]):
            add(b)

    nm = lambda t: ((mdl.transforms.get(t) or {}).get("name") or "?")
    broken = []
    for t in list(need):
        cur = (mdl.transforms.get(t) or {}).get("father")
        h = 0
        while cur is not None and h < 300 and cur in mdl.transforms:
            if cur in need:
                break
            broken.append((nm(t), nm(cur), "" if planar(cur) else "非平面"))
            break
        cur = (mdl.transforms.get(cur) or {}).get("father") if cur else None
        h += 1
    print("保留骨 %d 根；父链上有被剔除节点的骨 %d 根" % (len(need), len(broken)))
    for a, b, why in broken[:12]:
        print("    %-30s <- 被剔除的 %-30s %s" % (a, b, why))


if __name__ == "__main__":
    main()
