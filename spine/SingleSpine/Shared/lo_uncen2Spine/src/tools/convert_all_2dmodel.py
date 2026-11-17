r"""把扫描出"可转换"的 2DModel prefab 全部跑一遍完整转换，统计结果。

用法：
  python tools/convert_all_2dmodel.py [--jobs 5] [--out _probe_all]
                                      [--json 报告.json] [--limit N]
"""
# --- lo_uncen2Spine: 位置解析（自动插入，见 src/tools\deabs_paths.py）------
import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while _ROOT and not _os.path.isdir(_os.path.join(_ROOT, 'unity2spine')):
    _ROOT = _os.path.dirname(_ROOT)
if _ROOT and _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from unity2spine.env import resolve as _resolve  # noqa: E402
from unity2spine.console import fix_console as _fix_console  # noqa: E402
_fix_console()
from unity2spine.paths import app_root as _app_root  # noqa: E402
# ---------------------------------------------------------------------


import argparse
import concurrent.futures as futures
import glob
import json
import os
import sys
import time

HERE = _app_root()
sys.path.insert(0, _ROOT)
sys.path.insert(0, HERE)

from probe_generality import run_one  # noqa: E402

ASSETS = _resolve(r"D:\VB\Search\NormalLocal\lastOrign\Assets")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=ASSETS)
    ap.add_argument("--out", default=os.path.join(HERE, "_probe_all"))
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", default=None)
    ap.add_argument("--names-from", default=None,
                    help="只转换这个清单里的（collect_convertible 的报告）")
    ap.add_argument("--prefab-dir", default=None,
                    help="从哪个目录取 prefab（默认 Assets/prefabs/lo/<角色>/）。"
                         "例：--prefab-dir …\\Assets\\prefabs\\Change50 —— 直接转"
                         "那个目录里的 50 个副本，不再按角色名去 lo 里找。")
    ap.add_argument("--scene", default=None,
                    help="传给转换器的 --scene（用场景实例的姿态/覆盖；"
                         "要和 Play 真值比对时建议带上，"
                         "例：…\\Assets\\Scenes\\save.unity）")
    a = ap.parse_args()

    if a.names_from:
        d = json.load(open(a.names_from, encoding="utf-8-sig"))
        names = [r["name"] for r in d["rows"] if r.get("ok")]
    else:
        names = None

    if a.prefab_dir:
        paths = sorted(glob.glob(os.path.join(a.prefab_dir, "*.prefab")))
        if names:
            want = set(names)
            paths = [p for p in paths
                     if os.path.splitext(os.path.basename(p))[0] in want]
    else:
        idx = {}
        for p in glob.glob(os.path.join(a.assets, "prefabs", "lo", "*",
                                        "*.prefab")):
            idx.setdefault(os.path.splitext(os.path.basename(p))[0], p)
        paths = [idx[n] for n in (names or sorted(idx)) if n in idx]
    if a.limit:
        paths = paths[:a.limit]
    os.makedirs(a.out, exist_ok=True)
    print("待转换 %d 个，并行 %d" % (len(paths), a.jobs))

    rows = []
    t0 = time.time()
    done = 0
    with futures.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = {ex.submit(run_one, p, a.out, a.assets, a.scene): p for p in paths}
        for f in futures.as_completed(futs):
            r = f.result()
            rows.append(r)
            done += 1
            if done % 10 == 0 or done == len(paths):
                ok = sum(1 for x in rows if x["rc"] == 0)
                print("  [%d/%d] 成功 %d  用时 %.0fs"
                      % (done, len(paths), ok, time.time() - t0))
            if r["rc"] != 0:
                print("  失败 %-44s %s" % (r["prefab"], r["error"][:90]))

    ok = [r for r in rows if r["rc"] == 0]
    bad = [r for r in rows if r["rc"] != 0]
    print("\n完成：成功 %d / %d，总用时 %.0f 分钟"
          % (len(ok), len(rows), (time.time() - t0) / 60))
    if bad:
        print("失败清单：")
        for r in bad:
            print("  %-46s %s" % (r["prefab"], r["error"][:100]))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fp:
            json.dump({"assets": a.assets, "ok": len(ok), "total": len(rows),
                       "rows": rows}, fp, ensure_ascii=False, indent=1)
        print("报告: " + a.json)


if __name__ == "__main__":
    main()
