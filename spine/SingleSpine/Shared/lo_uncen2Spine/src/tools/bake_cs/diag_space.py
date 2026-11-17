# -*- coding: utf-8 -*-
r"""诊断：Unity 的 A/B 顶点到底怎样映射到产物坐标。

做三件事：
  1 打印前几个顶点的 (unity world / unity local / 产物 setup+deform)
  2 拟合"最佳仿射"（含 y 翻转与否、各向异性缩放、平移），看残差能不能收敛到 0
  3 直接检查产物在 t=0 的 deform 是不是 0（判断 setup 参考帧）

用法:
    python diag_space.py --product <基线产物> --verify <verify_*.json> [--part parts_L_hair]
"""

import argparse
import io
import json
import math
import os
import sys


def load_json(path):
    with io.open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def find_json(d):
    for fn in os.listdir(d):
        if fn.endswith("_static.json"):
            return os.path.join(d, fn)


def deform_value_at(frames, t):
    if not frames:
        return None
    if t <= frames[0]["time"]:
        return frames[0]["vertices"]
    if t >= frames[-1]["time"]:
        return frames[-1]["vertices"]
    lo, hi = 0, len(frames) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if frames[mid]["time"] <= t:
            lo = mid
        else:
            hi = mid
    a, b = frames[lo], frames[hi]
    u = 0.0 if b["time"] <= a["time"] else (t - a["time"]) / (b["time"] - a["time"])
    return [x + (y - x) * u for x, y in zip(a["vertices"], b["vertices"])]


def mm(m, v):
    return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2] + m[3],
            m[4] * v[0] + m[5] * v[1] + m[6] * v[2] + m[7],
            m[8] * v[0] + m[9] * v[1] + m[10] * v[2] + m[11])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--verify", required=True)
    ap.add_argument("--part", default=None)
    a = ap.parse_args()

    info = load_json(os.path.join(a.product, "_static_info.json"))
    sk = load_json(find_json(a.product))
    vf = load_json(a.verify)
    unit_k = float(info["unitScale"])
    ox, oy = info["origin"][:2]
    fx = -1.0 if info.get("flipX") else 1.0
    t = float(vf["time"])
    state = vf["state"]
    slots = sk["skins"][0]["attachments"]
    meta = info["partsMeta"]

    # --- ① 产物 deform 在 t=0 是否为 0（setup 参考帧检查）
    print("== 产物 deform(0) 是否为零（应为 0 才说明 setup 就是该动画 t=0）==")
    for nm in ("parts_L_hair_08", "parts_B_hair_23", "parts_breast_12", "parts_chair_49"):
        dd = ((sk["animations"].get(state) or {}).get("deform") or {}).get("default") or {}
        fr = (dd.get(nm) or {}).get(nm)
        if not fr:
            print("   %-20s 无 deform" % nm)
            continue
        v0 = fr[0]["vertices"]
        print("   %-20s 首键 t=%.3f  max|v|=%.4f  末键 t=%.3f"
              % (nm, fr[0]["time"], max(abs(x) for x in v0) if v0 else 0.0, fr[-1]["time"]))

    # --- ② 逐部件拟合 产物 = S * (unity world) + T，看 S 是否各部件一致
    print()
    print("== 逐部件仿射拟合 产物 = S*(unity world) + T  ==")
    print("%-22s %10s %10s %10s | %10s %10s %10s | %8s" %
          ("part", "sxx", "sxy", "cx", "syx", "syy", "cy", "resid"))
    for rr in vf["renderers"]:
        nm2 = None
        for m in meta:
            if (m.get("path") or "").endswith(rr["path"]):
                nm2 = m["name"]
        if nm2 is None or nm2 not in slots:
            continue
        an2 = nm2 if nm2 in slots[nm2] else list(slots[nm2].keys())[0]
        su2 = slots[nm2][an2]["vertices"]
        l2 = rr["l2w"]
        n2 = len(su2) // 2
        if n2 != rr["n"]:
            continue
        dd2 = ((sk["animations"].get(state) or {}).get("deform") or {}).get("default") or {}
        dv2 = deform_value_at((dd2.get(nm2) or {}).get(an2), t) or [0.0] * len(su2)
        A2, bx2, by2 = [], [], []
        for k in range(n2):
            w = mm(l2, rr["a"][k])
            A2.append([w[0], w[1], 1.0])
            bx2.append(su2[2 * k] + dv2[2 * k])
            by2.append(su2[2 * k + 1] + dv2[2 * k + 1])
        out = []
        for b in (bx2, by2):
            M = [[sum(A2[i][p] * A2[i][q] for i in range(n2)) for q in range(3)]
                 for p in range(3)]
            V = [sum(A2[i][p] * b[i] for i in range(n2)) for p in range(3)]
            for i in range(3):
                pv = max(range(i, 3), key=lambda z: abs(M[z][i]))
                M[i], M[pv] = M[pv], M[i]
                V[i], V[pv] = V[pv], V[i]
                for j in range(i + 1, 3):
                    f = M[j][i] / M[i][i]
                    for q in range(i, 3):
                        M[j][q] -= f * M[i][q]
                    V[j] -= f * V[i]
            sol = [0.0, 0.0, 0.0]
            for i in (2, 1, 0):
                s = V[i] - sum(M[i][q] * sol[q] for q in range(i + 1, 3))
                sol[i] = s / M[i][i]
            res = max(abs(sol[0] * A2[i][0] + sol[1] * A2[i][1] + sol[2] - b[i])
                      for i in range(n2))
            out.append(sol + [res])
        print("%-22s %10.3f %10.3f %10.3f | %10.3f %10.3f %10.3f | %8.4f"
              % (rr["path"].split("/")[-1], out[0][0], out[0][1], out[0][2],
                 out[1][0], out[1][1], out[1][2], max(out[0][3], out[1][3])))
    print("   参考 unit_k=%.3f  origin=(%.4f,%.4f)  fx=%+.1f"
          % (unit_k, ox, oy, fx))

    r = None
    for rr in vf["renderers"]:
        if a.part is None or rr["path"].endswith(a.part):
            r = rr
            break
    if r is None:
        print("找不到部件")
        return 1
    rel = r["path"]
    nm = None
    for m in meta:
        if (m.get("path") or "").endswith(rel):
            nm = m["name"]
    an = nm if nm in slots[nm] else list(slots[nm].keys())[0]
    setup = slots[nm][an]["vertices"]
    dd = ((sk["animations"].get(state) or {}).get("deform") or {}).get("default") or {}
    dv = deform_value_at((dd.get(nm) or {}).get(an), t) or [0.0] * len(setup)
    n = len(setup) // 2
    print()
    print("== 部件 %s (slot=%s) n=%d t=%.3f ==" % (rel, nm, n, t))
    print("%4s %-30s %-30s %-30s" % ("i", "unity world", "unity local", "产物 setup+deform"))
    for k in range(min(6, n)):
        w = mm(r["l2w"], r["a"][k])
        print("%4d (%9.4f,%9.4f)   (%9.4f,%9.4f)   (%9.2f,%9.2f)"
              % (k, w[0], w[1], r["a"][k][0], r["a"][k][1],
                 setup[2 * k] + dv[2 * k], setup[2 * k + 1] + dv[2 * k + 1]))

    # --- ② 最小二乘拟合 产物 = S * (unity_world) + T（各向异性 + 独立平移）
    ux = [set(setup[2 * k] + dv[2 * k] for k in range(n))]
    A = []
    bx, by = [], []
    for k in range(n):
        w = mm(r["l2w"], r["a"][k])
        A.append([w[0], w[1], 1.0])
        bx.append(setup[2 * k] + dv[2 * k])
        by.append(setup[2 * k + 1] + dv[2 * k + 1])
    print()
    print("== 线性拟合 产物x/y = a*ux + b*uy + c ==")
    for label, b in (("x", bx), ("y", by)):
        # 正规方程 3x3
        M = [[sum(A[i][p] * A[i][q] for i in range(n)) for q in range(3)] for p in range(3)]
        V = [sum(A[i][p] * b[i] for i in range(n)) for p in range(3)]
        # 高斯消元
        for i in range(3):
            p = max(range(i, 3), key=lambda r2: abs(M[r2][i]))
            M[i], M[p] = M[p], M[i]
            V[i], V[p] = V[p], V[i]
            for j in range(i + 1, 3):
                f = M[j][i] / M[i][i]
                for q in range(i, 3):
                    M[j][q] -= f * M[i][q]
                V[j] -= f * V[i]
        sol = [0.0, 0.0, 0.0]
        for i in (2, 1, 0):
            s = V[i] - sum(M[i][q] * sol[q] for q in range(i + 1, 3))
            sol[i] = s / M[i][i]
        res = []
        for i in range(n):
            pred = sol[0] * A[i][0] + sol[1] * A[i][1] + sol[2]
            res.append(abs(pred - b[i]))
        print("   产物%s = %+.4f*ux %+.4f*uy %+.4f ; 残差 中位 %.4f 最大 %.4f"
              % (label, sol[0], sol[1], sol[2],
                 sorted(res)[len(res) // 2], max(res)))
    print()
    print("   参考：unit_k=%+.4f  fx=%+.1f  origin=(%.4f,%.4f)" % (unit_k, fx, ox, oy))
    print("   若 y 行解出 ≈ +unit_k 且 c ≈ -oy*unit_k ⇒ 无 y 翻转；")
    print("   若 y 行解出 ≈ -unit_k 且 c ≈ +oy*unit_k ⇒ 有 y 翻转。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
