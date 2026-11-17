#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""给一批产物批量补写 Spine 3.8 二进制骨架（.skel）。

为什么需要：`tools/convert_all_2dmodel.py` 走的是 `probe_generality.run_one`，
它调 `static_prefab_spine` 时**没有透传 `--skel`**，所以批量转出来的目录里
没有 .skel。这里按 docs 里"事后补写"的做法，用同一份 JSON 补出来
（`write_skeleton_binary` 和转换器 `--skel` 走的是同一个函数）。

用法：
    python tools/write_all_skel.py <产物根目录>          # 例如 _probe50
    python tools/write_all_skel.py <产物根目录> --force  # 已存在也重写
"""
# --- lo_uncen2Spine: 位置解析（自动插入，见 src/tools\deabs_paths.py）--
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
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = _app_root()  # 项目根
sys.path.insert(0, HERE)

from ngui2spine.spine38_binary_writer import write_skeleton_binary  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="产物根目录（里面有 <角色>/<角色>_static.json）")
    ap.add_argument("--force", action="store_true", help="已存在也重写")
    a = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(a.root, "*", "*_static.json")))
    if not paths:
        raise SystemExit("没找到 *_static.json：%s" % a.root)
    print("待补写 %d 个" % len(paths))
    ok = skip = 0
    for p in paths:
        skel = p[:-5] + ".skel"
        if os.path.exists(skel) and not a.force:
            skip += 1
            continue
        try:
            d = json.load(open(p, encoding="utf-8-sig"))
            write_skeleton_binary(d, skel)
            ok += 1
            print("  %-52s %.1f MB" % (os.path.basename(skel),
                                       os.path.getsize(skel) / 1048576.0))
        except Exception as e:                       # noqa: BLE001
            print("  失败 %s: %s" % (os.path.basename(p), e))
    print("完成：写出 %d，跳过 %d" % (ok, skip))


if __name__ == "__main__":
    main()
