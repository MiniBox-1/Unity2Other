# -*- coding: utf-8 -*-
r"""用 Unity 拆开的中间态（pre / after1 / after2）逐粒子定位差异：
  ① 每粒子的 damping/elasticity/stiffness/boneLength 到底是多少；
  ② 移植版 update1 公式 vs Unity 的 after1；
  ③ 移植版 update2 公式（以 Unity 的 after1 为起点）vs Unity 的 after2。
哪一步对不上，差异就在那一步。

用法: python diag_db_split.py --dump <alice_db_split.json>
"""

import argparse
import io
import json
import math
import sys


def sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def add(a, b):
    return [a[i] + b[i] for i in range(3)]


def mul(a, k):
    return [a[i] * k for i in range(3)]


def norm(a):
    return math.sqrt(sum(c * c for c in a))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True)
    a = ap.parse_args()
    D = json.load(io.open(a.dump, encoding="utf-8-sig"))
    for st in D["steps"]:
        pre, a1, a2 = st["pre"], st["after1"], st["after2"]
        n = len(pre)
        print("=== frame %d  go=%s  粒子=%d" % (st["frame"], st.get("go"), n))
        if not a1 or not a2:
            print("   （没拿到中间态）")
            continue
        par = [int(pre[i][9]) for i in range(n)]
        print("   父索引=%s" % par)
        for i in range(n):
            print("   #%d damping=%.6f elasticity=%.6f stiffness=%.6f boneLength=%.6f  bonePos=(%.5f,%.5f,%.5f)"
                  % (i, pre[i][10], pre[i][11], pre[i][12], pre[i][13],
                     pre[i][6], pre[i][7], pre[i][8]))
        # ① update1：pos += (pos-prev)*(1-damping)；根粒子 pos = bonePos
        e1 = []
        pred1 = []
        for i in range(n):
            p0 = pre[i][0:3]
            v0 = pre[i][3:6]
            if i == 0:
                p = list(pre[i][6:9])
            else:
                p = add(p0, mul(sub(p0, v0), 1.0 - pre[i][10]))
            pred1.append(p)
            e1.append(math.dist(p, a1[i][0:3]))
        print("   ① update1 误差: 中位 %.3e 最大 %.3e" % (sorted(e1)[n // 2], max(e1)))
        # ② update2：以 Unity 的 after1 为起点
        e2 = {"fresh": [], "stale": []}
        for i in range(1, n):
            pos = list(a1[i][0:3])
            prevb = list(a1[i][3:6])
            pi = par[i]
            bone_n = pre[i][13]                     # Unity 的 m_BoneLength
            elas = pre[i][11]
            num2 = 1.0 + (pre[i][12] - 1.0) * 1.0   # weight=1
            tgt = list(pre[i][6:9])                 # 占位（dump 里 bonePos 在 6..8）
            # dump 没存 target；用"父粒子 after1 − pre"做平移修正需要步前 target，
            # 这里只能验证：update1 一致 ⇒ 再看 after2 与"用 after1 重算"的差
            v3 = sub(a1[pi][0:3], pos)
            m2 = norm(v3)
            if m2 > 0:
                pos_keep = add(pos, mul(v3, (m2 - bone_n) / m2))
            else:
                pos_keep = pos
            e2["fresh"].append(math.dist(pos_keep, a2[i][0:3]))
        print("   ② 只做 keep-length（从 after1 起）与 Unity after2 的差: 中位 %.3e 最大 %.3e"
              % (sorted(e2["fresh"])[(n - 1) // 2], max(e2["fresh"])))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
