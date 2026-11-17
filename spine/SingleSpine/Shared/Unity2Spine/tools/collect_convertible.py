r"""扫描所有 2DModel prefab，挑出"能转换"的，并把它们的 prefab 收集到指定目录。

轻量检查（不导出图集，只解析 prefab/动画），所以很快。

用法：
  python tools/collect_convertible.py [--assets <Assets>] [--copy-to <目录>]
                                      [--json 报告.json]
"""

import argparse
import glob
import json
import os
import shutil
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ngui2spine.static_prefab_spine import (  # noqa: E402
    enumerate_clips, load_character)

DEFAULT_ASSETS = r"D:\VB\Search\NormalLocal\lastOrign\Assets"
MAIN = ("audrey_normal.prefab", "blacklilith_normal.prefab",
        "aeda_normal.prefab")


def is_2dmodel(path):
    try:
        t = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    return ("Animator:" in t) and ("SkinnedMeshRenderer:" in t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=DEFAULT_ASSETS)
    ap.add_argument("--copy-to", default=None,
                    help="把能转换的 prefab 复制到这里（不含 .meta）")
    ap.add_argument("--json", default=None)
    ap.add_argument("--include-main", action="store_true")
    a = ap.parse_args()

    files = sorted(set(glob.glob(os.path.join(
        a.assets, "prefabs", "lo", "*", "*.prefab"))))
    files = [p for p in files if is_2dmodel(p)]
    if not a.include_main:
        files = [p for p in files if os.path.basename(p) not in MAIN]
    print("2DModel prefab: %d 个" % len(files))

    rows = []
    t0 = time.time()
    for i, p in enumerate(files, 1):
        name = os.path.basename(p)[:-len(".prefab")]
        row = {"prefab": os.path.basename(p), "name": name, "path": p}
        try:
            mdl, parts = load_character(p, a.assets, None,
                                        animated_only=True)
            entries = enumerate_clips(mdl, a.assets)
            row["parts"] = len(parts)
            row["anims"] = len(entries)
            row["excluded"] = len(getattr(mdl, "excluded_parts", []) or [])
            row["ok"] = bool(parts) and bool(entries)
            if not parts:
                row["reason"] = "没有可导出的部件"
            elif not entries:
                row["reason"] = "没有可用的动画 clip"
        except Exception as ex:
            row["ok"] = False
            row["reason"] = "%s: %s" % (type(ex).__name__, ex)
            row["trace"] = traceback.format_exc()[-400:]
        rows.append(row)
        if i % 25 == 0 or i == len(files):
            ok = sum(1 for r in rows if r.get("ok"))
            print("  [%d/%d] 可转换 %d  用时 %.0fs"
                  % (i, len(files), ok, time.time() - t0))

    ok_rows = [r for r in rows if r.get("ok")]
    bad_rows = [r for r in rows if not r.get("ok")]
    print("\n可转换 %d / %d" % (len(ok_rows), len(rows)))
    reasons = {}
    for r in bad_rows:
        key = (r.get("reason") or "?").split(":")[0]
        reasons[key] = reasons.get(key, 0) + 1
    for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print("   失败原因 %-40s %d" % (k, v))

    if a.copy_to:
        os.makedirs(a.copy_to, exist_ok=True)
        n = 0
        for r in ok_rows:
            dst = os.path.join(a.copy_to, r["prefab"])
            if not os.path.exists(dst):
                shutil.copy2(r["path"], dst)
                n += 1
        print("已复制 %d 个 prefab -> %s" % (n, a.copy_to))

    if a.json:
        with open(a.json, "w", encoding="utf-8") as fp:
            json.dump({"assets": a.assets, "total": len(rows),
                       "ok": len(ok_rows), "rows": rows}, fp,
                      ensure_ascii=False, indent=1)
        print("报告: " + a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
