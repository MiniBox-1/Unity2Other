# -*- coding: utf-8 -*-
r"""校验 `ExportDrawOrder.cs` 里"谁盖谁"那套判定**方向没搞反**：

  1) 用 Python 按**规范**（不是照抄 C#）重新实现一遍
     `classify()` / `over()` / `topo_order()`，跑合成图用例：
     不透明的 a 盖住 b ⇒ 必须判成 `a-above-b`，且拓扑序是 [b, a]（b 先画）。
  2) 对 C# 源码做**静态断言**：`errA 小 ⇒ a-above-b` 这条对应关系必须在源码里
     出现（2026-09-17 就是在这里写反过：`errB 小` 判成了 `a-above-b`）。

用法：python tools\check_draworder_math.py
"""
import io
import re
import sys

CS = r"D:\VB\Search\NormalLocal\lastOrign\Assets\Editor\ExportDrawOrder.cs"


# ----------------------------------------------------------------- Python 侧规范实现
def over(top, bottom, premultiplied):
    """`top over bottom`；premultiplied=True 时输入/输出都按已预乘的颜色算。"""
    ta, ba = top[3] / 255.0, bottom[3] / 255.0
    oa = ta + ba * (1 - ta)
    if oa <= 1e-6:
        return [0.0, 0.0, 0.0]
    t = list(top[:3]) if premultiplied else [c * ta for c in top[:3]]
    b = list(bottom[:3]) if premultiplied else [c * ba for c in bottom[:3]]
    out = [t[i] + b[i] * (1 - ta) for i in range(3)]
    if not premultiplied:
        out = [c / oa for c in out]
    return out


def dist(x, y):
    return max(abs(x[0] - y[0]), abs(x[1] - y[1]), abs(x[2] - y[2]))


def diff(pred, actual):
    return sum(abs(pred[i] - actual[i]) for i in range(3))


def classify(A, B, AB, ia=0, ib=1):
    """返回 (verdict, votesA, votesB, errA, errB, overlap)。规范：a 在上 ⇒ a-above-b。"""
    sum_pa = sum_pb = sum_sa = sum_sb = 0.0
    both = va = vb = 0
    for a, b, ab in zip(A, B, AB):
        # 只在两个件都覆盖的像素上判定（只覆盖一个的像素没有信息，
        # 拿来投票会产生假票 —— 2026-09-17 修）
        if a[3] < 8 or b[3] < 8:
            continue
        both += 1
        if a[3] > 250:
            da, db = dist(ab, a), dist(ab, b)
            if da <= 6 and db > 24:
                va += 1
        if b[3] > 250:
            da, db = dist(ab, a), dist(ab, b)
            if db <= 6 and da > 24:
                vb += 1
        sum_pa += diff(over(a, b, True), ab)      # a 在上（预乘）
        sum_pb += diff(over(b, a, True), ab)
        sum_sa += diff(over(a, b, False), ab)     # a 在上（straight）
        sum_sb += diff(over(b, a, False), ab)
    if both < 8:
        return "no-overlap", va, vb, 0.0, 0.0, both
    cnt = max(1, both)
    bestA = min(sum_pa, sum_sa) / (3 * cnt)
    bestB = min(sum_pb, sum_sb) / (3 * cnt)
    by_votes = None
    if va > vb * 1.2 and va >= 20:
        by_votes = "a-above-b"
    elif vb > va * 1.2 and vb >= 20:
        by_votes = "b-above-a"
    by_model = None
    if bestA < bestB * 0.5 and bestA < 12.0:
        by_model = "a-above-b"
    elif bestB < bestA * 0.5 and bestB < 12.0:
        by_model = "b-above-a"
    if by_votes and by_model and by_votes == by_model:
        verdict = by_votes
    elif by_votes and not by_model:
        verdict = by_votes + "?votes"
    elif by_model and not by_votes:
        verdict = by_model + "?model"
    elif by_votes and by_model:
        verdict = "conflict"
    else:
        verdict = "ambiguous"
    return verdict, va, vb, bestA, bestB, both


def topo_order(nodes, rel):
    """rel: [(above, below)]；返回**先画 → 后画**。"""
    before = {n: set() for n in nodes}
    after = {n: set() for n in nodes}
    for top, bot in rel:
        if top not in before or bot not in before:
            continue
        before[top].add(bot)
        after[bot].add(top)
    indeg = {n: len(before[n]) for n in nodes}
    ready = sorted(n for n in nodes if indeg[n] == 0)
    out = []
    while ready:
        n = ready.pop(0)
        out.append(n)
        for m in after[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
                ready.sort()
    for n in nodes:
        if n not in out:
            out.append(n)
    return out


# ----------------------------------------------------------------- 合成图用例
def solid(n, rgba):
    return [list(rgba)[:4] for _ in range(n)]


def case_a_over_b():
    n = 100
    A = solid(n, (255, 0, 0, 255))       # 红，不透明
    B = solid(n, (0, 0, 255, 255))       # 蓝，不透明
    AB = solid(n, (255, 0, 0, 255))      # 最终是红 ⇒ a 在上
    v, va, vb, ea, eb, ov = classify(A, B, AB)
    assert v == "a-above-b", v
    assert topo_order([0, 1], [(0, 1)]) == [1, 0]
    return v, va, vb, round(ea, 2), round(eb, 2)


def case_b_over_a():
    n = 100
    A = solid(n, (255, 0, 0, 255))
    B = solid(n, (0, 0, 255, 255))
    AB = solid(n, (0, 0, 255, 255))      # 最终是蓝 ⇒ b 在上
    v, va, vb, ea, eb, ov = classify(A, B, AB)
    assert v == "b-above-a", v
    assert topo_order([0, 1], [(1, 0)]) == [0, 1]
    return v, va, vb, round(ea, 2), round(eb, 2)


def case_half_transparent():
    """a 半透明盖在不透明 b 上：预乘模型应当仍然判出 a 在上。"""
    n = 100
    A = solid(n, (255, 0, 0, 128))
    B = solid(n, (0, 0, 255, 255))
    ap = [255 * 128 // 255, 0, 0, 128]                  # 预乘后的 a（预乘页）
    AB = solid(n, (128, 0, 127, 255))                   # 手工算的 a over b
    v, va, vb, ea, eb, ov = classify(A, B, AB)
    assert v.startswith("a-above-b"), (v, ea, eb)
    return v, va, vb, round(ea, 2), round(eb, 2)


def case_no_overlap():
    """a 只占左半、b 只占右半：没有共同覆盖的像素 ⇒ 必须报 no-overlap。"""
    n = 40
    A, B, AB = [], [], []
    for i in range(n):
        left = i < n // 2
        A.append([255, 0, 0, 255] if left else [0, 0, 0, 0])
        B.append([0, 0, 255, 255] if not left else [0, 0, 0, 0])
        AB.append(list(A[-1]))
    v, *_ = classify(A, B, AB)
    assert v == "no-overlap", v
    return v, 0, 0, 0.0, 0.0


def case_big_nonoverlap_small_overlap():
    """a 面积大得多、只在很小一块里与 b 重叠，且**b 在上** ⇒ 必须判 b-above-a。

    这是"只覆盖一个的像素会投假票"的老 bug 的回归用例。
    """
    n = 400
    A, B, AB = [], [], []
    for i in range(n):
        left = i < 20            # 20 个像素里 a、b 都在（b 在上）
        only_a = 20 <= i < 400   # 380 个像素只有 a
        A.append([255, 0, 0, 255])
        B.append([0, 0, 255, 255] if left else [0, 0, 0, 0])
        AB.append([0, 0, 255, 255] if left else [255, 0, 0, 255])
    v, va, vb, ea, eb, ov = classify(A, B, AB)
    assert v.startswith("b-above-a"), (v, va, vb, ea, eb)
    return v, va, vb, round(ea, 2), round(eb, 2), ov


def case_cycle_fallback():
    """有环时拓扑排序必须仍然把全部节点吐出来（C# 里是兜底追加）。"""
    out = topo_order([0, 1, 2], [(0, 1), (1, 2), (2, 0)])
    assert sorted(out) == [0, 1, 2], out
    return out


def static_check_cs():
    src = io.open(CS, encoding="utf-8").read()
    ok_a = re.search(r'bestA\s*<\s*bestB\s*\*\s*0\.5[^\n]*byModel\s*=\s*"a-above-b"', src)
    ok_b = re.search(r'bestB\s*<\s*bestA\s*\*\s*0\.5[^\n]*byModel\s*=\s*"b-above-a"', src)
    bad = re.search(r'bestB\s*<\s*bestA\s*\*\s*0\.5[^\n]*byModel\s*=\s*"a-above-b"', src)
    ok_ov = bool(re.search(
        r'double\[\]\s+Over\(\s*Color32\s+top\s*,\s*Color32\s+bottom\s*,'
        r'\s*bool\s+storedPremultiplied\s*\)', src))
    ok_top = "mustBefore[top].Add(bot)" in src
    return ok_a and ok_b and not bad and ok_ov and ok_top, {
        "errA小⇒a-above-b": bool(ok_a),
        "errB小⇒b-above-a": bool(ok_b),
        "没有写反的老分支": not bool(bad),
        "有 Over(top,bottom,premultiplied)": ok_ov,
        "拓扑里 bot 先于 top": ok_top,
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("合成图用例：")
    for fn in (case_a_over_b, case_b_over_a, case_half_transparent,
               case_no_overlap, case_big_nonoverlap_small_overlap,
               case_cycle_fallback):
        print("  %-24s %s" % (fn.__name__, fn()))
    ok, detail = static_check_cs()
    print("C# 源码静态断言：")
    for k, v in detail.items():
        print("   %-34s %s" % (k, "✅" if v else "❌"))
    print("结论：" + ("方向与语义都对 ✅" if ok else "**有问题 ❌**"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
