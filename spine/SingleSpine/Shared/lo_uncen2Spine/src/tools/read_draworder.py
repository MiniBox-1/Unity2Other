# -*- coding: utf-8 -*-
r"""读 Unity 导出的绘制顺序 JSON（`Assets/Editor/ExportDrawOrder.cs` 的产物），
回答三个问题并把结论打成人能看的表：

  ① 枚举序（GetComponentsInChildren）与**层级 DFS 序**是不是一回事？
  ② 每个"排序键完全并列"的组里，**实测顺序**与 DFS 序是否一致？
  ③ 全局顺序能不能用 `(sortingLayer, sortingOrder, camDepth)` + 组内实测顺序解释，
     以及"用 DFS 当并列内的次序"会不会产生逆序（= 我们的转换规则对不对）。

用法：
    python src/tools\read_draworder.py <目录或 json 文件…> [--verbose]
    # 目录会递归找 *_draworder_*/*.json
"""
import argparse
import glob
import io
import json
import os
import sys


def load(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += glob.glob(os.path.join(p, "**", "*.json"), recursive=True)
        else:
            files.append(p)
    out = []
    for f in sorted(set(files)):
        try:
            d = json.load(io.open(f, encoding="utf-8-sig"))
        except Exception:
            continue
        if isinstance(d, dict) and "drawOrderFirstToLast" in d:
            out.append((f, d))
    return out


def invert_count(seq, key):
    """seq 里有多少对是"按 key 应该反过来"的（逆序对）。"""
    n = 0
    for i in range(len(seq)):
        for j in range(i + 1, len(seq)):
            if key(seq[i]) > key(seq[j]):
                n += 1
    return n


def report(path, d, verbose):
    R = {r["i"]: r for r in d["renderers"]}
    name = lambda i: (R[i]["node"] if R[i].get("node") else R[i]["path"].split("/")[-1])
    print("=" * 92)
    print("%s  [%s / %s @ t=%ss]" % (os.path.basename(path), d.get("character"),
                                     d.get("state"), d.get("t")))
    mismatch = [r for r in d["renderers"] if r["enumIndex"] != r["dfsIndex"]]
    print("渲染器 %d 个；枚举序==DFS序：%s%s"
          % (len(d["renderers"]), "是" if not mismatch else "否",
             "" if not mismatch else "（%d 个不同，例如 %s）"
             % (len(mismatch), name(mismatch[0]["i"]))))

    groups = d.get("tieGroups") or []
    multi = [g for g in groups if len(g.get("visibleMembers") or []) > 1]
    ok = [g for g in multi if g.get("matchesDfs")]
    print("并列组：%d 个（其中可见成员≥2 的 %d 个）；实测顺序与 DFS 一致：%d/%d"
          % (len(groups), len(multi), len(ok), len(multi)))
    bad = [g for g in multi if not g.get("matchesDfs")]
    for g in bad[:8]:
        dfs = [name(i) for i in g["dfsOrder"]]
        emp = [name(i) for i in g["empiricalOrder"]]
        print("   ✗ layer=%s order=%s depth=%s"
              % (g.get("sortingLayerID"), g.get("sortingOrder"), g.get("camDepth")))
        print("       DFS : %s" % " → ".join(dfs))
        print("       实测: %s" % " → ".join(emp))
    if verbose:
        for g in multi:
            print("   · order=%s depth=%s  %s"
                  % (g.get("sortingOrder"), g.get("camDepth"),
                     "DFS==实测" if g.get("matchesDfs") else "**不一致**"))
            print("       %s" % " → ".join(name(i) for i in g["empiricalOrder"]))

    pairs = d.get("pairs") or []
    verdicts = {}
    for p in pairs:
        verdicts[p["verdict"]] = verdicts.get(p["verdict"], 0) + 1
    if pairs:
        print("成对实测 %d 对：%s" % (len(pairs), dict(sorted(verdicts.items()))))
        weak = [p for p in pairs if p["verdict"] in ("ambiguous", "conflict")]
        for p in weak[:6]:
            print("   ? %s vs %s  votes=%d/%d err=%.1f/%.1f overlap=%d"
                  % (name(p["a"]), name(p["b"]), p["votesA"], p["votesB"],
                     p["errA"], p["errB"], p["overlapPx"]))

    order = d.get("drawOrderFirstToLast") or []
    if order:
        # 用"DFS 当并列内的次序"复查：全局顺序里有多少对是反的
        def key_rule(i):
            r = R[i]
            return (r["sortingLayerID"], r["sortingOrder"], -r["camDepth"],
                    r["tieRank"] if r["tieRank"] >= 0 else r["dfsIndex"])

        def key_dfs(i):
            r = R[i]
            return (r["sortingLayerID"], r["sortingOrder"], -r["camDepth"],
                    r["dfsIndex"])

        inv_rule = invert_count(order, key_rule)
        inv_dfs = invert_count(order, key_dfs)
        na = [i for i in order if R[i]["dfsIndex"] < 0]
        print("全局顺序 %d 个：与「规则+tieRank」的逆序对 %d；"
              "改用「DFS 当并列次序」后逆序对 %d%s"
              % (len(order), inv_rule, inv_dfs,
                 "" if not na else "（%d 个没有 dfsIndex）" % len(na)))
        if inv_dfs == 0 and inv_rule == 0:
            print("   ⇒ **DFS 序可以完全解释这份实测顺序**")
        elif inv_dfs == 0:
            print("   ⇒ DFS 序也能解释（与实测一致）")
        else:
            print("   ⇒ DFS 序解释不了全部；先看上面的 ✗ 组")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    files = load(a.paths)
    if not files:
        print("没找到带 drawOrderFirstToLast 的 json；传入目录或文件")
        return
    print("读到 %d 份导出" % len(files))
    for f, d in files:
        report(f, d, a.verbose)


if __name__ == "__main__":
    main()
