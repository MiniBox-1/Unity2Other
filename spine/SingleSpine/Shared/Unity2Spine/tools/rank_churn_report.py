# -*- coding: utf-8 -*-
"""统计"相对层级（rank）"随时间的跳变规模，给"多 drawable"方案定量。

对每个角色：
  · 把每条动画的采样时刻上"按 (m_SortingOrder, 静态顺序) 排序"得到的目标顺序算出来；
  · 每个部件在这些时刻上的 rank（第几个被画）构成一个集合；
  · 集合大小 > 1 的部件就是"相对层级会变"的部件 —— 需要分配多个 drawable。

用法: python tools\\rank_churn_report.py <角色…>   （不带参数 = _probe50_rt2 全部）
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from ngui2spine.static_prefab_spine import (   # noqa: E402
    enumerate_clips, load_character, rank_sets)


def main():
    chars = sys.argv[1:]
    root = os.path.join(HERE, "_probe50_rt2")
    if not chars:
        chars = sorted(d for d in os.listdir(root)
                       if os.path.isdir(os.path.join(root, d)))
    A = r"D:\VB\Search\NormalLocal\lastOrign\Assets"
    scene = os.path.join(A, "Scenes", "save.unity")
    print("%-22s %6s %8s %8s %8s  %s" %
          ("角色", "部件", "变层部件", "总槽位", "+槽位", "最多层的部件"))
    tot_p = tot_s = 0
    for ch in chars:
        pf = os.path.join(A, "prefabs", "lo", ch.split("_")[0], ch + ".prefab")
        if not os.path.isfile(pf):
            import glob
            hits = glob.glob(os.path.join(A, "prefabs", "lo", "*", ch + ".prefab"))
            if not hits:
                print("%-22s (找不到 prefab)" % ch)
                continue
            pf = hits[0]
        try:
            mdl, parts = load_character(pf, A, scene=scene)
            entries = enumerate_clips(mdl, A)
        except Exception as ex:                       # noqa: BLE001
            print("%-22s (失败 %s)" % (ch, ex))
            continue
        ranks, _per_entry = rank_sets(mdl, entries, parts)
        n_part = len(ranks)
        multi = {k: v for k, v in ranks.items() if len(v) > 1}
        slots = sum(len(v) for v in ranks.values())
        name_of = {p.tfid: getattr(p, "name", str(p.tfid)) for p in parts}
        worst = max(ranks.items(), key=lambda kv: len(kv[1]),
                    default=(-1, set()))
        worst_name = name_of.get(worst[0], "?")
        tot_p += n_part
        tot_s += slots
        print("%-22s %6d %8d %8d %8d  %s(%d 层)" %
              (ch, n_part, len(multi), slots, slots - n_part,
               worst_name[-24:], len(worst[1])))
    if tot_p:
        print("合计：部件 %d，槽位 %d（+%.1f%%）"
              % (tot_p, tot_s, 100.0 * (tot_s - tot_p) / tot_p))


main()
