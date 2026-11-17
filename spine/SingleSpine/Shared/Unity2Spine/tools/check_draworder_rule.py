# -*- coding: utf-8 -*-
r"""拿 Unity 实测的"谁盖谁"关系，去检验**候选排序规则**。

`ExportDrawOrder.cs` 会为每对渲染器给出 `verdict`（`a-above-b` = a 后画、盖住 b）。
这里把每条**实测到的**关系与几条候选规则对照，看谁解释得了：

  enum ↑ / enum ↓    按**枚举序**（GetComponentsInChildren）升/降序画
  dfs  ↑ / dfs  ↓    按**层级 DFS 序**（脚本自算）升/降序画

注意：只有 `verdict` 是 `a-above-b` / `b-above-a`（可带 `?votes` / `?model`）的对
才算"实测到"；`no-overlap`/`ambiguous`/`conflict` 不参与计分。

用法：python tools\check_draworder_rule.py <目录或 json…>
"""
import argparse
import glob
import io
import json
import os
import sys

RULES = ("enum↑", "enum↓", "dfs↑", "dfs↓", "ukey↑")


def rule_position(r, rule):
    """返回"该规则下先后的位置值"，越小越先画。"""
    if rule == "enum↑":
        return (r["sortingLayerID"], r["sortingOrder"], -r["camDepth"], r["enumIndex"])
    if rule == "enum↓":
        return (r["sortingLayerID"], r["sortingOrder"], -r["camDepth"], -r["enumIndex"])
    if rule == "dfs↑":
        return (r["sortingLayerID"], r["sortingOrder"], -r["camDepth"], r["dfsIndex"])
    if rule == "dfs↓":
        return (r["sortingLayerID"], r["sortingOrder"], -r["camDepth"], -r["dfsIndex"])
    if rule == "ukey↑":
        # Unity 自己的排序键（反射读的内部属性 `Renderer.sortingKey`）优先，
        # 然后才是深度。键读不到（-1）时整对不用这条规则。
        return (r.get("unitySortingKey", -1), -r["camDepth"])
    raise ValueError(rule)


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
        if isinstance(d, dict) and "pairs" in d and "renderers" in d:
            out.append((f, d))
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    a = ap.parse_args()
    files = load(a.paths)
    if not files:
        print("没找到导出 json"); return 1
    total = {k: [0, 0] for k in RULES}
    worst = {k: [] for k in RULES}
    for f, d in files:
        R = {r["i"]: r for r in d["renderers"]}
        nm = lambda i: (R[i].get("node") or R[i]["path"].split("/")[-1])
        score = {k: [0, 0] for k in RULES}          # [符合, 违反]
        bad_examples = {k: [] for k in RULES}
        n = 0
        for p in d["pairs"]:
            v = p["verdict"]
            if v.startswith("a-above-b"):
                ia, ib, sa, sb = p["a"], p["b"], R[p["a"]], R[p["b"]]
            elif v.startswith("b-above-a"):
                ia, ib, sa, sb = p["b"], p["a"], R[p["b"]], R[p["a"]]
            else:
                continue
            n += 1
            for rule in RULES:
                if rule == "ukey↑" and (sa.get("unitySortingKey", -1) < 0
                                        or sb.get("unitySortingKey", -1) < 0):
                    continue
                # 实测：ia 后画（在上）；规则：位置大的后画
                if rule_position(sa, rule) > rule_position(sb, rule):
                    score[rule][0] += 1
                else:
                    score[rule][1] += 1
                    bad_examples[rule].append(
                        "%s 应在 %s 之上（%s votes=%d/%d vp=%d）"
                        % (nm(ia), nm(ib), v, p["votesA"], p["votesB"], p["overlapPx"]))
        print("=" * 88)
        print("%s  [%s/%s @t=%s]" % (os.path.basename(f), d.get("character"),
                                     d.get("state"), d.get("t")))
        print("可用的实测关系 %d 条（no-overlap/ambiguous 不算）" % n)
        if n == 0:
            print("  ⇒ 这次没测到任何关系（PairScope=off 或全不重叠）")
            continue
        for rule in RULES:
            ok, no = score[rule]
            flag = "✅" if no == 0 else "❌"
            print("  %-6s 符合 %2d / 违反 %2d  %s" % (rule, ok, no, flag))
        best = [r for r in RULES if score[r][1] == 0]
        print("  ⇒ 能完全解释的规则：%s" % (", ".join(best) if best else "（没有，需要新规则）"))
        # 逐条列出被关键规则违反的实例（只看 dfs↑，也就是当前转换器用的规则）
        for rule in ("dfs↑", "enum↑"):
            if score[rule][1]:
                print("  %s 的反例（最多 8 条）：" % rule)
                for s in bad_examples[rule][:8]:
                    print("     - " + s)

        # 累计到合计
        for rule in RULES:
            total[rule][0] += score[rule][0]
            total[rule][1] += score[rule][1]
            for s in bad_examples[rule]:
                if len(worst[rule]) < 6:
                    worst[rule].append(s + "   @" + os.path.basename(f))

    print("=" * 88)
    print("【合计】%d 份导出" % len(files))
    for rule in RULES:
        ok, no = total[rule]
        tot = ok + no
        print("  %-6s 符合 %6d / 违反 %6d  (符合率 %.2f%%)  %s"
              % (rule, ok, no, 100.0 * ok / max(1, tot), "✅" if no == 0 else "❌"))
    best = [r for r in RULES if total[r][1] == 0]
    print("  ⇒ 全量能完全解释的规则：%s" % (", ".join(best) if best else "（没有）"))
    for rule in ("dfs↑", "enum↑"):
        if total[rule][1]:
            print("  %s 的反例示例：" % rule)
            for s in worst[rule]:
                print("     - " + s)


if __name__ == "__main__":
    sys.exit(main())
