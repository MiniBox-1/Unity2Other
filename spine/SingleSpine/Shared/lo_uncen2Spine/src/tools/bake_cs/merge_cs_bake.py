# -*- coding: utf-8 -*-
r"""把 Unity 烘出来的「CS 脚本运行态形变 (B - A)」合并进 Spine 产物。

两个必须钉死的事实（都来自实测，别再猜）
----------------------------------------
① 产物顶点空间 != Unity 世界空间
      产物顶点 = S * (Unity 世界顶点) + T
   S 是各部件**同一份**、对角、无翻转的线性映射；它不等于 info 里的
   unitScale。Alexandra 实测 S=+5367.0*I 而 unitScale=732.6，比值 7.326
   正好等于 1/渲染器 lossyScale（0.1365）；Alice unitScale=803.7。
   所以本工具用 bake.json 里的 absA 做最小二乘**标定** S/T，并同时打印
   解析候选 S=unit_k/lossyScale 供交叉验证。
② 顶点是 3 维、且 2D 模型的局部网格躺在 XZ 平面（"竖直"= 局部 z）。
   只取 x,y 会丢掉整个纵向，必须用 l2w 把 3 维局部增量转成世界增量。

合并量：delta(产物) = S * (l2w_linear * (B_local - A_local))

用法:
    python merge_cs_bake.py --product <产物目录> --bake <bake.json> --out <输出目录>
        [--calib auto|lossy|unitk] [--prune-tol PX] [--no-skel] [--report r.json]
"""

import argparse
import io
import json
import math
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))

from unity2spine.spine.spine_out import fnum  # noqa: E402

DEFORM_PRECISION = 4


def load_json(path):
    with io.open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def solve2(M, V):
    det = M[0][0] * M[1][1] - M[0][1] * M[1][0]
    if abs(det) < 1e-9:
        return None
    return [(V[0] * M[1][1] - V[1] * M[0][1]) / det,
            (V[1] * M[0][0] - V[0] * M[1][0]) / det]


def xf3(m, d):
    """渲染器局部 3 维增量 -> 世界增量（只取线性部分，丢掉平移列）。"""
    return (m[0] * d[0] + m[1] * d[1] + m[2] * d[2],
            m[4] * d[0] + m[5] * d[1] + m[6] * d[2])


def mm3(m, v):
    return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2] + m[3],
            m[4] * v[0] + m[5] * v[1] + m[6] * v[2] + m[7])


def interp_frames(frames, t):
    """产物 deform 曲线在 t 处的线性插值（与 Spine 运行时的采样一致）。

    2026-10-09：合并网格不再只取"产物已有的关键帧"。产物对"纯 clip 几乎不动"
    的部件裁得很稀（Alice Tep_1 的 parts_Tail_B 在 1.55→7.95 之间只有 2 个键），
    而脚本形变在那段时间一直变化 —— 只按产物网格取值会把形变插成一条直线，
    实测在 t=4.0 让尾巴偏 97px（对 Unity 真值）。所以这里必须能在任意时刻取值。
    """
    if t <= frames[0]["time"]:
        return list(frames[0]["vertices"])
    if t >= frames[-1]["time"]:
        return list(frames[-1]["vertices"])
    lo, hi = 0, len(frames) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if frames[mid]["time"] <= t:
            lo = mid
        else:
            hi = mid
    a, b = frames[lo], frames[hi]
    span = b["time"] - a["time"]
    u = 0.0 if span <= 1e-12 else (t - a["time"]) / span
    return [x + (y - x) * u
            for x, y in zip(a["vertices"], b["vertices"])]


def nearest_times_index(times, t, tol=1e-3):
    """录制关键帧表里最接近 t 的下标（超出 tol 则 None）。"""
    if not times:
        return None
    lo, hi = 0, len(times) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if times[mid] <= t:
            lo = mid
        else:
            hi = mid
    best = lo if abs(times[lo] - t) <= abs(times[hi] - t) else hi
    return best if abs(float(times[best]) - t) <= tol else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--bake", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--calib", choices=["auto", "lossy", "unitk"], default="auto")
    ap.add_argument("--prune-tol", type=float, default=None)
    ap.add_argument("--no-skel", action="store_true")
    ap.add_argument("--report", default=None)
    a = ap.parse_args()

    info = load_json(os.path.join(a.product, "_static_info.json"))
    jpath = None
    for fn in os.listdir(a.product):
        if fn.endswith("_static.json"):
            jpath = os.path.join(a.product, fn)
    if jpath is None:
        raise SystemExit("产物目录里没有 *_static.json")
    skeleton = load_json(jpath)
    bake = load_json(a.bake)

    unit_k = float(info.get("unitScale") or 1.0)
    fx = -1.0 if info.get("flipX") else 1.0
    tol = a.prune_tol if a.prune_tol is not None else 0.001 * unit_k

    meta = info.get("partsMeta") or []
    slots = skeleton["skins"][0]["attachments"]

    def slot_of(rel, kind, n):
        rel = rel.replace("\\", "/")
        for m in meta:
            p = (m.get("path") or "").replace("\\", "/")
            if p.endswith(rel) and m.get("kind") == kind:
                nm = m["name"]
                att = slots.get(nm)
                if att:
                    an = nm if nm in att else list(att.keys())[0]
                    if len(att[an]["vertices"]) // 2 == n:
                        return nm, an
        return None, None

    clips = bake.get("clips") or []
    by_state = {c["state"]: c for c in clips}
    print("bake state: %s" % ", ".join(sorted(by_state)))

    # ---------------------------------------------------------- 标定
    part_rows = {}
    for cl in clips:
        if cl.get("absState") != cl["state"]:
            continue                      # absA 只在一个 state 里记
        times = cl["times"]
        aevery = int(cl.get("absEvery") or 1)
        dfrd = ((skeleton["animations"].get(cl["state"]) or {}).get("deform")
                or {}).get("default") or {}
        for i, r in enumerate(cl["renderers"]):
            nm, an = slot_of(r["path"], r["kind"], r["n"])
            if nm is None:
                continue
            setup = slots[nm][an]["vertices"]
            n = r["n"]
            dfr = (dfrd.get(nm) or {}).get(an)
            if not dfr:
                continue
            # 关键帧时刻 -> 该槽位 deform 值
            kmap = {}
            for fr in dfr:
                kmap[round(float(fr["time"]), 6)] = fr["vertices"]
            data = cl["data"][i]
            rows = part_rows.setdefault(nm, [])
            for k, t in enumerate(times):
                if k % aevery:
                    continue
                ai = k // aevery
                if ai >= len(data.get("absA") or []):
                    break
                dv = kmap.get(round(float(t), 6))
                if dv is None:
                    continue
                av = data["absA"][ai]
                m = data["l2w"][k]
                for vi in range(n):
                    w = mm3(m, (av[3 * vi], av[3 * vi + 1], av[3 * vi + 2]))
                    rows.append((w[0], w[1],
                                 setup[2 * vi] + dv[2 * vi],
                                 setup[2 * vi + 1] + dv[2 * vi + 1]))

    calib = {}
    if a.calib == "auto" and part_rows:
        # ---- 先按"逐部件解析式"标定：S = unit_k / |lossyScale|
        # 依据（2026-10-08 实测，见 Mobile-old_CS烘焙_方法与进展.md §4.1）：
        #   Alice parts_Body：601 帧 × 85 顶点，用 unit_k/|lossy|=6459 残差 0.002px；
        #   用"全局 S"=822 残差 159px。两个部件的 lossyScale 差 8 倍（0.124 vs 0.99），
        #   全局拟合会被多数派带偏 —— 所以必须逐部件。
        ls_of = {}
        for cl in clips:
            for r in cl["renderers"]:
                nmx, _ = slot_of(r["path"], r["kind"], r["n"])
                if nmx and r.get("lossyScale"):
                    ls_of[nmx] = abs(r["lossyScale"][0])
        # 汇总拟合只作为"旁证"（残差大说明解析式口径有问题）
        MA = [[0.0, 0.0], [0.0, 0.0]]
        Rx = [0.0, 0.0]
        Ry = [0.0, 0.0]
        for nm, rows in part_rows.items():
            if len(rows) < 3:
                continue
            mx = sum(r[0] for r in rows) / len(rows)
            my = sum(r[1] for r in rows) / len(rows)
            px = sum(r[2] for r in rows) / len(rows)
            py = sum(r[3] for r in rows) / len(rows)
            for (ax, ay, qx, qy) in rows:
                ax -= mx; ay -= my; qx -= px; qy -= py
                MA[0][0] += ax * ax; MA[0][1] += ax * ay
                MA[1][0] += ax * ay; MA[1][1] += ay * ay
                Rx[0] += ax * qx; Rx[1] += ay * qx
                Ry[0] += ax * qy; Ry[1] += ay * qy
        sxa = solve2(MA, Rx)
        sya = solve2(MA, Ry)
        if sxa and sya:
            print("汇总拟合 S = [[%9.3f,%8.3f],[%9.3f,%9.3f]]（仅作旁证；逐部件见下）unit_k=%.3f fx=%+.1f"
                  % (sxa[0], sxa[1], sya[0], sya[1], unit_k, fx))
            lss = sorted(set(abs(r["lossyScale"][0]) for cl in clips
                             for r in cl["renderers"] if r.get("lossyScale")))
            if lss:
                print("   lossyScale 取值: %s -> unit_k/lossy = %s"
                      % (", ".join("%.6f" % v for v in lss[:4]),
                         ", ".join("%.3f" % (unit_k / v) for v in lss[:4])))
            resid = []
            for nm, rows in part_rows.items():
                if len(rows) < 3:
                    continue
                ls = ls_of.get(nm)
                if ls and ls > 1e-9:
                    k = unit_k / ls
                    gsz = [[k, 0.0], [0.0, k]]
                    src = "unit_k/|lossy|=%.1f" % k
                else:
                    gsz = [[sxa[0], sxa[1]], [sya[0], sya[1]]]
                    src = "汇总拟合(缺 lossyScale)"
                mx = sum(r[0] for r in rows) / len(rows)
                my = sum(r[1] for r in rows) / len(rows)
                px = sum(r[2] for r in rows) / len(rows)
                py = sum(r[3] for r in rows) / len(rows)
                tx = px - (gsz[0][0] * mx + gsz[0][1] * my)
                ty = py - (gsz[1][0] * mx + gsz[1][1] * my)
                ee = []
                for (ax, ay, qx, qy) in rows:
                    ee.append(max(abs(gsz[0][0] * ax + gsz[0][1] * ay + tx - qx),
                                  abs(gsz[1][0] * ax + gsz[1][1] * ay + ty - qy)))
                ee.sort()
                rmed = ee[len(ee) // 2]
                rp90 = ee[int(len(ee) * 0.9)]
                resid.append((nm, ee[-1], [tx, ty], len(rows), rmed, rp90,
                              gsz, src))
            resid.sort(key=lambda x: -x[1])
            print("   %-24s %9s %9s %9s  %s" % ("部件", "中位px", "p90px", "最大px", "用的 S"))
            for nm, rmax, _t, cnt, rmed, rp90, _gs, src in resid[:12]:
                print("   %-24s %9.4f %9.4f %9.4f  %s  n=%d"
                      % (nm, rmed, rp90, rmax, src, cnt))
            if resid:
                vs = sorted(x[1] for x in resid)
                print("   标定残差: 中位 %.4fpx / 最大 %.4fpx"
                      % (vs[len(vs) // 2], vs[-1]))
            for nm, rmax, txy, cnt, _rm, _rp, gsz, src in resid:
                calib[nm] = {"S": gsz, "T": txy, "residPx": rmax, "n": cnt,
                             "how": src}

    if not calib or a.calib != "auto":
        # 退路：S = unit_k / lossyScale（解析式，实测与拟合差 < 0.3%）
        n_ls = 0
        for cl in clips:
            for r in cl["renderers"]:
                nm, _an = slot_of(r["path"], r["kind"], r["n"])
                if nm is None:
                    continue
                ls = (r.get("lossyScale") or [None])[0]
                if a.calib == "unitk" or not ls:
                    calib[nm] = {"S": [[fx * unit_k, 0.0], [0.0, unit_k]],
                                 "T": None, "residPx": None, "n": 0}
                else:
                    s = unit_k / abs(ls)
                    sgnx = -1.0 if ls < 0 else 1.0
                    sgny = -1.0 if ls < 0 else 1.0
                    calib[nm] = {"S": [[fx * sgnx * s, 0.0], [0.0, sgny * s]],
                                 "T": None, "residPx": None, "n": 0}
                    n_ls += 1
        print("标定: 解析式 S=unit_k/lossyScale（%d 个部件）" % n_ls)

    # ---------------------------------------------------------- 合并
    report = {"product": a.product, "bake": a.bake, "unitScale": unit_k,
              "flipX": info.get("flipX"), "pruneTol": tol, "calibMode": a.calib,
              "calibration": calib, "slots": []}
    total_before = total_after = 0

    for anim_name, anim in skeleton.get("animations", {}).items():
        cl = by_state.get(anim_name)
        if cl is None:
            print("[skip] 产物动画 %s 无对应 bake state" % anim_name)
            continue
        deform_root = (anim.get("deform") or {}).get("default")
        if not deform_root:
            continue
        times = cl["times"]
        kmap = {round(float(t), 6): k for k, t in enumerate(times)}
        for i, r in enumerate(cl["renderers"]):
            nm, an = slot_of(r["path"], r["kind"], r["n"])
            if nm is None or nm not in calib:
                continue
            frames = deform_root.get(nm, {}).get(an)
            if not frames:
                continue
            S = calib[nm]["S"]
            data = cl["data"][i]
            delta = data["delta"]
            l2w = data["l2w"]
            n = r["n"]
            # ★ 合并网格 = 产物关键帧 ∪ 录制关键帧（见 interp_frames 注释）。
            t_lo = float(frames[0]["time"])
            t_hi = float(frames[-1]["time"])
            grid = set(round(float(f["time"]), 6) for f in frames)
            n_base_keys = len(grid)
            for rt in times:
                rt = round(float(rt), 6)
                if t_lo - 1e-9 <= rt <= t_hi + 1e-9:
                    grid.add(rt)
            new_frames = []
            last = None
            maxd = 0.0
            for t in sorted(grid):
                k = kmap.get(t)
                if k is None:
                    k = nearest_times_index(times, t)
                if k is None:
                    continue
                d = delta[k] if k < len(delta) else None
                if d is None:
                    continue
                m = l2w[min(k, len(l2w) - 1)]
                cur = interp_frames(frames, t)
                for vi in range(n):
                    wd = xf3(m, (d[3 * vi], d[3 * vi + 1], d[3 * vi + 2]))
                    dx = S[0][0] * wd[0] + S[0][1] * wd[1]
                    dy = S[1][0] * wd[0] + S[1][1] * wd[1]
                    if math.hypot(dx, dy) > maxd:
                        maxd = math.hypot(dx, dy)
                    cur[2 * vi] += dx
                    cur[2 * vi + 1] += dy
                if last is not None and all(abs(x - y) <= tol
                                            for x, y in zip(cur, last)):
                    continue
                last = cur
                new_frames.append({"time": fnum(t),
                                   "vertices": [fnum(v, DEFORM_PRECISION)
                                                for v in cur]})
            if new_frames and t > new_frames[-1]["time"] + 1e-6:
                new_frames.append({"time": fnum(t),
                                   "vertices": list(new_frames[-1]["vertices"])})
            total_before += len(frames)
            total_after += len(new_frames)
            deform_root.setdefault(nm, {})[an] = new_frames
            report["slots"].append({"anim": anim_name, "slot": nm,
                                    "keysBefore": len(frames),
                                    "keysAfter": len(new_frames),
                                    "gridBaseKeys": n_base_keys,
                                    "gridTotalKeys": len(grid),
                                    "maxDeltaPx": round(maxd, 2)})

    os.makedirs(a.out, exist_ok=True)
    base = os.path.basename(jpath)
    out_json = os.path.join(a.out, base)
    with io.open(out_json, "w", encoding="utf-8") as fh:
        json.dump(skeleton, fh, ensure_ascii=False, separators=(",", ":"))
    for fn in os.listdir(a.product):
        src = os.path.join(a.product, fn)
        dst = os.path.join(a.out, fn)
        if os.path.isfile(src) and fn != base and not fn.endswith(".skel"):
            shutil.copy2(src, dst)
    print("关键帧总数: %d -> %d (%+.1f%%)"
          % (total_before, total_after,
             100.0 * (total_after - total_before) / max(1, total_before)))
    print("写出: %s" % out_json)

    if not a.no_skel:
        env = dict(os.environ)
        env["PYTHONPATH"] = ROOT
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        r = subprocess.run([sys.executable, "-m", "ngui2spine.spine38_binary_writer",
                            out_json], cwd=ROOT, env=env,
                           capture_output=True, text=True)
        print("[skel] rc=%d %s" % (r.returncode, (r.stdout or "").strip()[-300:]))
        if r.returncode != 0:
            print((r.stderr or "")[-1200:])

    if a.report:
        with io.open(a.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
        print("报告: %s" % a.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
