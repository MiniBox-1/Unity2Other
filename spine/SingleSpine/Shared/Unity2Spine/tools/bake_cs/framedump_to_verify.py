# -*- coding: utf-8 -*-
r"""把 U2SFrameDump 的一帧，转成 `verify_merge.py` 认的 verify.json，
这样就能直接复用那条**逐顶点、以产物像素为单位**的对账口径（位置校验）。

要点：
  · dump 里记的是**世界顶点**（BakeMesh 后经 TransformPoint）；verify.json 要的是
    **渲染器局部顶点** + `l2w`，所以这里用 l2w 的仿射逆把它变回局部；
  · a=b=该帧顶点（dump 只有一个状态），于是 verify_merge 的
    "基线 vs Unity A" 一列就是**产物位置 vs Unity 位置**的误差（px）；
  · 顶点被 `vertexCap` 截断的渲染器会被跳过（影子这类精灵顶点数很小，能完整比）。

用法:
    python framedump_to_verify.py --dump <jsonl> --time <Unity秒> --state <产物动画名> ^
        --product-time <产物里的秒> --out verify.json
    python verify_merge.py --product <产物目录> --merged <产物目录> ^
        --verify verify.json
"""

import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from read_framedump import frame_at, load_json, obj_paths, read_dump  # noqa: E402


def inv_affine(m):
    """localToWorldMatrix（列主序展开的 16 个数）的逆（只处理仿射）。"""
    # 注意：U2SFrameDump 写出的是 **行主序**（k/4=行、k%4=列），
    # 与 merge_cs_bake.xf3/mm3 读法一致（m[0..2] 是线性部分第一行）。
    # 按列主序取元素会拿到转置 —— 这批部件还带非均匀缩放，会算出错的局部坐标。
    a, b, c = m[0], m[1], m[2]
    d, e, f = m[4], m[5], m[6]
    g, h, i = m[8], m[9], m[10]
    tx, ty, tz = m[3], m[7], m[11]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-20:
        return None
    inv = [
        (e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det,
        (f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det,
        (d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det,
    ]
    # 平移： -inv3 * t
    nx = -(inv[0] * tx + inv[1] * ty + inv[2] * tz)
    ny = -(inv[3] * tx + inv[4] * ty + inv[5] * tz)
    nz = -(inv[6] * tx + inv[7] * ty + inv[8] * tz)
    return (inv, (nx, ny, nz))


def to_local(m, p):
    r = inv_affine(m)
    if r is None:
        return None
    inv, t = r
    return (inv[0] * p[0] + inv[1] * p[1] + inv[2] * p[2] + t[0],
            inv[3] * p[0] + inv[4] * p[1] + inv[5] * p[2] + t[1],
            inv[6] * p[0] + inv[7] * p[1] + inv[8] * p[2] + t[2])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True)
    ap.add_argument("--time", type=float, required=True, help="dump 里的一帧时刻")
    ap.add_argument("--state", required=True, help="产物里的动画名（如 Tep_1）")
    ap.add_argument("--product-time", type=float, default=None,
                    help="产物里的时刻（默认 = dump 时刻，用于对齐循环相位）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--grep", default=None)
    ap.add_argument("--product", default=None,
                    help="产物目录：用它算一份解析标定表（S=unit_k·I、T=原点偏移）")
    ap.add_argument("--calib-out", default=None, help="把标定表写到这个 json")
    ap.add_argument("--calib-in", default=None,
                    help="已有的 merge_report.json（里面拟好的 S/T 优先）")
    a = ap.parse_args()

    meta, _head = read_dump(a.dump)
    names = obj_paths(meta)
    fr = frame_at(a.dump, a.time, None)
    if fr is None:
        raise SystemExit("没找到该帧")
    t_prod = a.time if a.product_time is None else a.product_time
    objs = {o["i"]: o for o in fr.get("obj") or []}
    out_r = []
    skipped = []
    for r in fr.get("rnd") or []:
        o = objs.get(r.get("o"))
        if not o or "v" not in r or not o.get("l2w"):
            continue
        path = names.get(r["o"], "")
        if a.grep and a.grep.lower() not in path.lower():
            continue
        vn = int(r.get("vn") or 0)
        vs = r["v"]
        if vn <= 0 or len(vs) != 3 * vn:
            skipped.append(path)
            continue
        kind = "skinned" if "nv" in r else "sprite"
        loc = []
        ok = True
        for k in range(vn):
            q = to_local(o["l2w"], (vs[3 * k], vs[3 * k + 1], vs[3 * k + 2]))
            if q is None:
                ok = False
                break
            loc.append([q[0], q[1], q[2]])
        if not ok:
            skipped.append(path)
            continue
        out_r.append({"path": path, "kind": kind, "n": vn,
                      "l2w": list(o["l2w"]), "a": loc, "b": loc})

    doc = {"prefab": (meta or {}).get("prefab") or "", "state": a.state,
           "time": t_prod, "fps": float((meta or {}).get("captureFramerate") or 60),
           "renderers": out_r,
           "note": "由 framedump_to_verify.py 从 U2SFrameDump 生成；a=b=该帧顶点"}
    with io.open(a.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    print("写出 %s：渲染器 %d 个（顶点截断跳过 %d 个）"
          % (a.out, len(out_r), len(skipped)))
    if skipped:
        print("  跳过（vertexCap 截断或没有顶点）：")
        for p in skipped[:8]:
            print("   ", p)
    print("  用产物时刻 %.3f（动画 %s）对账" % (t_prod, a.state))

    if a.product and a.calib_out:
        info = load_json(os.path.join(a.product, "_static_info.json"))
        sk = load_json([os.path.join(a.product, f) for f in os.listdir(a.product)
                        if f.endswith("_static.json")][0])
        uk = float(info.get("unitScale") or 1.0)
        fx = -1.0 if info.get("flipX") else 1.0
        ox, oy = (info.get("origin") or [0.0, 0.0])[:2]
        cal = {}
        if a.calib_in and os.path.isfile(a.calib_in):
            cal = dict((load_json(a.calib_in).get("calibration") or {}))
            print("  已并入已拟合标定 %d 个部件" % len(cal))
        S = [[fx * uk, 0.0], [0.0, uk]]
        T = [-fx * uk * float(ox), -uk * float(oy)]
        n_new = 0
        for m in info.get("partsMeta") or []:
            nm = m.get("name")
            if nm and nm not in cal:
                cal[nm] = {"S": S, "T": T, "residPx": None, "n": 0,
                           "how": "解析(单位×原点偏移)"}
                n_new += 1
        with io.open(a.calib_out, "w", encoding="utf-8") as fh:
            json.dump({"product": a.product, "unitScale": uk, "flipX": info.get("flipX"),
                       "calibration": cal}, fh, ensure_ascii=False)
        print("  标定表 -> %s（新增 %d 个，unit_k=%.3f 原点=(%.4f,%.4f)）"
              % (a.calib_out, n_new, uk, ox, oy))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
