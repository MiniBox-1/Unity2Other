# -*- coding: utf-8 -*-
r"""对 `_spine_conv_cs_port` 下所有角色跑 `tools/static_check.py`，汇总成一张表。

用法:
    python src/tools\batch_static_check.py [--limit N] [--only 子串] [--max 0]

输出:
    _scratch\qc_<时间戳>.log        实时日志
    _scratch\qc_<时间戳>_summary.tsv 每角色一行：sceneRenderers / exportedParts /
                                     missingAnimated / missingStatic /
                                     visibilityConflicts / unknownCurvePaths
    _scratch\qc\<角色>.json          逐角色完整报告
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
import io
import json
import os
import subprocess
import sys
import time

REPO = _app_root()
ASSETS = _resolve(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Assets")
PROD = _resolve(r"D:\VB\Search\New\归档-proj-Mobile-old\_spine_conv_cs_port")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=ASSETS)
    ap.add_argument("--prod", default=PROD)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default=None)
    ap.add_argument("--timeout", type=float, default=600.0)
    a = ap.parse_args()
    ts = time.strftime("%Y%m%d_%H%M%S")
    qdir = os.path.join(REPO, ".cache", "qc")
    os.makedirs(qdir, exist_ok=True)
    logp = os.path.join(REPO, ".cache", "logs", "qc_%s.log" % ts)
    sump = os.path.join(REPO, ".cache", "logs", "qc_%s_summary.tsv" % ts)
    os.makedirs(os.path.dirname(logp), exist_ok=True)
    log = io.open(logp, "w", encoding="utf-8")

    def w(m):
        print(m)
        log.write(m + "\n")
        log.flush()

    names = sorted(os.listdir(a.prod))
    if a.only:
        keys = [s.strip() for s in a.only.split(",") if s.strip()]
        names = [n for n in names if any(k in n for k in keys)]
    if a.limit:
        names = names[:a.limit]
    rows = []
    w("QC 开始 %s  角色数=%d" % (ts, len(names)))
    t0 = time.time()
    for i, nm in enumerate(names, 1):
        d = os.path.join(a.prod, nm)
        pre = os.path.join(a.assets, "Prefabs", nm + ".uAnim.prefab")
        rep = os.path.join(qdir, nm + ".json")
        if not os.path.isfile(pre):
            w("[%3d/%d] 跳过 %s（找不到 prefab）" % (i, len(names), nm))
            continue
        t1 = time.time()
        try:
            subprocess.run([sys.executable, os.path.join(REPO, "src", "tools",
                                                         "static_check.py"),
                            pre, "--assets", a.assets, "--spine-dir", d,
                            "--json", rep],
                           cwd=REPO, capture_output=True, timeout=a.timeout,
                           encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            w("[%3d/%d] 超时 %s" % (i, len(names), nm))
            rows.append((nm, -1, -1, -1, -1, -1, -1, "timeout"))
            continue
        dt = time.time() - t1
        try:
            r = json.load(io.open(rep, encoding="utf-8"))
        except (ValueError, OSError):
            w("[%3d/%d] 报告读取失败 %s" % (i, len(names), nm))
            rows.append((nm, -1, -1, -1, -1, -1, -1, "no-report"))
            continue
        g = lambda k: len(r.get(k) or [])                          # noqa: E731
        row = (nm, r.get("sceneRenderers", -1), r.get("exportedParts", -1),
               g("missingAnimated"), g("missingStatic"),
               g("visibilityConflicts"), g("unknownCurvePaths"), "")
        rows.append(row)
        flag = "OK " if max(row[3:7]) == 0 else "!! "
        w("[%3d/%d] %s%-46s %5.1fs  缺动画 %d / 缺静态 %d / 显隐冲突 %d / path 对不上 %d"
          % (i, len(names), flag, nm, dt, row[3], row[4], row[5], row[6]))
    bad = [r for r in rows if max(r[3:7]) > 0 or r[7]]
    with io.open(sump, "w", encoding="utf-8") as fh:
        fh.write("角色\tsceneRenderers\texportedParts\tmissingAnimated\tmissingStatic"
                 "\tvisibilityConflicts\tunknownCurvePaths\tnote\n")
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")
    w("")
    w("QC 结束：%d 个角色，%.1f 分钟；有问题的 %d 个"
      % (len(rows), (time.time() - t0) / 60.0, len(bad)))
    for r in bad:
        w("   !! %-46s 缺动画 %d / 缺静态 %d / 显隐冲突 %d / path %d %s"
          % (r[0], r[3], r[4], r[5], r[6], r[7]))
    w("日志 %s" % logp)
    w("汇总 %s" % sump)
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
