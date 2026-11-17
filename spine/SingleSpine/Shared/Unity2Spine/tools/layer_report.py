# -*- coding: utf-8 -*-
"""报告"渲染顺序"的诊断数据：静态排序 / 全局 rank 跳变 / **相对层级**跳变。

用途：判断某个角色的画面问题是不是"前后层交换"引起的，以及按
`relative_layers()` 的口径会给它开多少个 drawable（槽位）。

用法：
    python tools\\layer_report.py <角色名> [...]          # 默认在 _probe50_rt2 里找
"""
import glob
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from ngui2spine.static_prefab_spine import (          # noqa: E402
    _part_points, _sample_world_multi, assignments_for_entry, enumerate_clips,
    hierarchy_ranks, load_character, make_samplers, order_at, probe_times_for,
    relative_layers, slot_key_with_rank, sorting_value_of)

ASSETS = r"D:\VB\Search\NormalLocal\lastOrign\Assets"
SCENE = os.path.join(ASSETS, "Scenes", "save.unity")


def prefab_of(ch):
    hits = glob.glob(os.path.join(ASSETS, "prefabs", "lo", "*", ch + ".prefab"))
    return hits[0] if hits else None


def diag(ch, mdl, entries, kept, sample):
    n_sort_anim = 0
    for e in entries:
        if not (e.get("clip") or {}).get("sorting"):
            continue
        for ke in kept:
            ts = probe_times_for(e)
            if len({sorting_value_of(mdl, e, ke["part"], t)
                    for t in ts}) > 1:
                n_sort_anim += 1
                break
    ranks = {i: set() for i in range(len(kept))}
    for e in entries:
        pl = [k["part"] for k in kept]
        for t in probe_times_for(e):
            for r, i in enumerate(order_at(mdl, e, pl, t)):
                ranks[i].add(r)

    def aabb_of(entry_name, tm, i):
        ent = next(x for x in entries if x["name"] == entry_name)
        w = sample(mdl, ent, tm)
        pts = _part_points(kept[i]["part"], w)
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    depths, _at = relative_layers(mdl, entries, kept, aabb_of,
                                  times_of=probe_times_for)
    nbr = _neighbour_stats(mdl, entries, kept, aabb_of)
    multi = {i: d for i, d in depths.items() if len(d) > 1}
    print("%-22s 部件 %3d | 排序值会变 %2d | 全局 rank 会变 %3d | "
          "**相对层级会变 %3d** | 槽位 %3d (%.1f%%) | 有重叠邻居 %3d(平均 %.1f)"
          % (ch, len(kept), n_sort_anim,
             sum(1 for v in ranks.values() if len(v) > 1),
             len(multi), len(kept) + len(multi),
             100.0 * len(multi) / max(1, len(kept)),
             nbr[0], nbr[1]))
    for i, d in sorted(multi.items(), key=lambda kv: -len(kv[1]))[:5]:
        print("      %-28s %s" % (kept[i]["part"].name[-28:], sorted(d)))


def _make_sampler(mdl, entries):
    samplers = make_samplers(mdl, entries)
    assign = {e["name"]: assignments_for_entry(mdl, samplers, entries, e)
              for e in entries}

    def sample(m, ent, tm):
        return _sample_world_multi(m, assign[ent["name"]], tm)
    return sample


def _neighbour_stats(mdl, entries, kept, aabb_of, sample_times=9):
    """复算一次"空间重叠"关系，返回 (有邻居的部件数, 平均邻居数)。"""
    n = len(kept)
    boxes = [None] * n
    for e in entries:
        ts = probe_times_for(e)
        if len(ts) > sample_times:
            ts = ts[::max(1, len(ts) // sample_times)]
        for t in ts:
            for i in range(n):
                b = aabb_of(e["name"], t, i)
                if not b:
                    continue
                cur = boxes[i]
                if cur is None:
                    boxes[i] = list(b)
                else:
                    cur[0] = min(cur[0], b[0]); cur[1] = min(cur[1], b[1])
                    cur[2] = max(cur[2], b[2]); cur[3] = max(cur[3], b[3])
    for b in boxes:
        if b is None:
            continue
        w = max(1e-6, (b[2] - b[0]) * 0.2)
        h = max(1e-6, (b[3] - b[1]) * 0.2)
        b[0] -= w; b[1] -= h; b[2] += w; b[3] += h
    have = 0
    tot = 0
    for i in range(n):
        cnt = 0
        for j in range(n):
            if i == j:
                continue
            a, b = boxes[i], boxes[j]
            if a is None or b is None:
                continue
            if not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1]):
                cnt += 1
        if cnt:
            have += 1
            tot += cnt
    return have, (tot / float(have) if have else 0.0)


def main():
    chars = sys.argv[1:]
    if not chars:
        root = os.path.join(HERE, "_probe50_rt3")
        chars = sorted(d for d in os.listdir(root)
                       if os.path.isdir(os.path.join(root, d)))
    for ch in chars:
        try:
            pf = prefab_of(ch)
            if not pf:
                print("%-22s (找不到 prefab)" % ch)
                continue
            mdl, parts = load_character(pf, ASSETS, scene=SCENE)
            entries = enumerate_clips(mdl, ASSETS)
            kept = [{"part": p} for p in parts if p.mesh or p.kind == "sprite"]
            kept.sort(key=slot_key_with_rank(hierarchy_ranks(mdl)))
            diag(ch, mdl, entries, kept, _make_sampler(mdl, entries))
        except Exception as ex:                        # noqa: BLE001
            print("%-22s (失败 %r)" % (ch, ex))


if __name__ == "__main__":
    main()
