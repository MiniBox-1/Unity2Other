# -*- coding: utf-8 -*-
r"""泛用性抽样：随机挑若干 prefab 跑静态路线，汇总成功率与失败原因。

用法：
  python tools/probe_generality.py [--count 12] [--seed 20260911]
                                   [--out D:\VB\Unity2Spine\_probe]
"""

import argparse
import concurrent.futures as futures
import glob
import json
import os
import random
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ASSETS = r"D:\VB\Search\NormalLocal\lastOrign\Assets"
MAIN = ("audrey_normal.prefab", "blacklilith_normal.prefab",
        "aeda_normal.prefab")


def is_2dmodel(path):
    """2DModel = prefab 里同时有 Animator 和 SkinnedMeshRenderer。"""
    try:
        t = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    return ("Animator:" in t) and ("SkinnedMeshRenderer:" in t)


def collect(assets, exclude_main=True, only_2dmodel=True, exclude_mod=True):
    pats = [os.path.join(assets, "prefabs", "lo", "*", "*.prefab"),
            os.path.join(assets, "prefabs", "*", "*.prefab")]
    out = []
    for p in pats:
        out += glob.glob(p)
    out = sorted(set(out))
    if exclude_main:
        out = [p for p in out if os.path.basename(p) not in MAIN]
    if only_2dmodel:
        out = [p for p in out if is_2dmodel(p)]
    if exclude_mod:
        # 带 mod 的是"改版皮肤"，资源常常只覆盖一部分，先只看原版
        out = [p for p in out if "mod" not in os.path.basename(p).lower()]
    return out


def run_one(prefab, out_root, assets, scene=None):
    name = os.path.splitext(os.path.basename(prefab))[0]
    out = os.path.join(out_root, name)
    cmd = [sys.executable, "-m", "ngui2spine.static_prefab_spine",
           prefab, out, "--assets", assets, "--no-face-check"]
    if scene:
        cmd += ["--scene", scene]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
        rc, log = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        rc, log = -9, "超时(>600s)"
    dt = time.time() - t0
    info = {}
    info_p = os.path.join(out, "_static_info.json")
    if os.path.isfile(info_p):
        try:
            info = json.load(open(info_p, encoding="utf-8-sig"))
        except Exception:
            pass
    check = ""
    m = re.search(r"\[static_check\](.*)", log)
    if m:
        check = m.group(1).strip()
    err = ""
    if rc != 0:
        tail = [ln for ln in log.strip().split("\n") if ln.strip()][-3:]
        err = " | ".join(tail)[-400:]
    return {"prefab": os.path.basename(prefab), "rc": rc,
            "seconds": round(dt, 1),
            "parts": info.get("parts"), "anims": len(info.get("animations") or []),
            "px_per_unit": round(info.get("unitScale") or 0, 1),
            "check": check, "error": err,
            "log_tail": "" if rc == 0 else log[-600:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=12)
    ap.add_argument("--seed", type=int, default=20260911)
    ap.add_argument("--out", default=os.path.join(HERE, "_probe"))
    ap.add_argument("--assets", default=DEFAULT_ASSETS)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--all-prefabs", action="store_true",
                    help="不筛 2DModel，测试全部 prefab")
    ap.add_argument("--include-mod", action="store_true",
                    help="把名字里带 mod 的改版皮肤也算进抽样池")
    a = ap.parse_args()

    pool = collect(a.assets, only_2dmodel=not a.all_prefabs,
                   exclude_mod=not a.include_mod)
    print("候选 prefab %d 个（%s%s，已排除三个主力）"
          % (len(pool),
             "全部 prefab" if a.all_prefabs else "仅 2DModel 结构",
             "＋mod 皮肤" if (a.include_mod and not a.all_prefabs) else
             ("，已排除 mod 皮肤" if not a.include_mod else "")))
    random.seed(a.seed)
    picked = random.sample(pool, min(a.count, len(pool)))
    os.makedirs(a.out, exist_ok=True)
    print("抽样 %d 个：%s\n" % (len(picked),
                              "、".join(os.path.basename(p)
                                        for p in picked)))
    rows = []
    with futures.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = {ex.submit(run_one, p, a.out, a.assets): p for p in picked}
        for f in futures.as_completed(futs):
            row = f.result()
            rows.append(row)
            flag = "OK  " if row["rc"] == 0 else "失败"
            print("%s %-34s %5.1fs 部件=%-4s 动画=%-3s %s"
                  % (flag, row["prefab"], row["seconds"],
                     row["parts"] if row["parts"] is not None else "-",
                     row["anims"] if row["anims"] else "-",
                     (row["check"] or "")[:70]))
            if row["rc"] != 0:
                print("      错误: %s" % row["error"][:200])

    rows.sort(key=lambda r: (r["rc"] != 0, r["prefab"]))
    ok = [r for r in rows if r["rc"] == 0]
    bad = [r for r in rows if r["rc"] != 0]
    print("\n成功 %d / %d" % (len(ok), len(rows)))
    if bad:
        print("失败清单：")
        for r in bad:
            print("  %-34s %s" % (r["prefab"], r["error"][:150]))
    with open(os.path.join(a.out, "summary.json"), "w",
              encoding="utf-8") as fp:
        json.dump({"assets": a.assets, "seed": a.seed,
                   "picked": [os.path.basename(p) for p in picked],
                   "rows": rows}, fp, ensure_ascii=False, indent=1)
    print("汇总: " + os.path.join(a.out, "summary.json"))


if __name__ == "__main__":
    main()
