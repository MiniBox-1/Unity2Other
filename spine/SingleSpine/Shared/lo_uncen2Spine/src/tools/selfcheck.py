# -*- coding: utf-8 -*-
r"""项目自检：配置能读、老路径能按当前位置解析、还剩多少硬编码绝对路径。

用法：python src/tools\selfcheck.py
退出码：0 = 配置可读且零硬编码外部路径。
"""
from __future__ import annotations

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from unity2spine.env import resolve                                  # noqa: E402
from unity2spine.paths import app_root, cache_dir, cfg               # noqa: E402

SAMPLES = (
    resolve(r"D:\VB\Unity2Spine\src"),
    resolve(r"D:\VB\Unity2Spine\info\_refshot_u2s"),
    resolve(r"D:\VB\Unity2Spine\_scratch\_csbake\playqueue.txt"),
    resolve(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Assets\Prefabs"),
    resolve(r"D:\VB\Search\NormalLocal\lastOrign\Assets"),
    resolve(r"D:\VB\Viewer\Render\v4\.venv\Scripts\python.exe"),
    resolve(r"D:\VB\Search\BdOne\Assets"),
    resolve(r"D:\VB\vision.js"),
)
KEYS = ("unity2spine.legacy_home", "unity2spine.cache_dir",
        "lo.project_root", "lo.assets_dir", "lo.out_dir", "lo.info_dir",
        "lo.csbake_dir", "bdone.assets_dir", "bdone.out_dir",
        "external.viewer_python", "external.ida_dir")


def main() -> int:
    print("app_root = %s" % app_root())
    print("cache    = %s" % cache_dir())
    for k in KEYS:
        print("  cfg(%-26s) = %s" % (k, cfg(k)))
    print("老路径解析（一律经 unity2spine.env.resolve）：")
    for p in SAMPLES:
        print("  %s" % p)
    print("硬编码绝对路径审计：")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import scan_abspaths                                            # noqa: E402
    return scan_abspaths.main()


if __name__ == "__main__":
    raise SystemExit(main())
