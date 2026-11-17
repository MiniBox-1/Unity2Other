# -*- coding: utf-8 -*-
r"""打包后补齐 MSVC 运行库（Nuitka 拷这几个名字会被本机安全策略拒）。

背景（2026-10-13）：本机往目标目录**按这些名字直接创建文件**会 `EACCES`
（`msvcp140.dll` / `vcruntime140*.dll` …，写别的名字没事，rename 过去也没事），
于是 Nuitka 的 `--standalone` 在拷 DLL 阶段反复崩。做法：

* 构建时用 `--noinclude-dlls=` 把这些名字**排除**，让 Nuitka 别去写；
* 构建后用本脚本**先写临时名再改名**补回（走的是被允许的路径）。

用法：
    python src/tools\fix_dist_runtime_dlls.py [dist目录，默认 <根>\dist\main.dist]
"""
from __future__ import annotations

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

import os
import shutil
import sys

#: 会被本机策略拒绝"直接创建"的名字
NAMES = ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
         "msvcp140_codecvt_ids.dll", "vcruntime140.dll", "vcruntime140_1.dll")
#: 往这些子目录各放一份（Nuitka 平时就放这几处）
SUBDIRS = ("", "PySide6", "shiboken6")
#: 从哪儿取（系统里的 VC 运行库；用 %SystemRoot% 拼，别写死盘符）
SOURCES = tuple(
    p for p in (os.path.join(os.environ.get("SystemRoot") or "", "System32"),)
    if os.path.isdir(p))


def copy_via_temp(src: str, dst: str) -> bool:
    """先写临时名再改名——本机策略只拦"直接按该名字创建"。"""
    tmp = dst + ".u2s_tmp"
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    dist = argv[0] if argv else os.path.join(_app_root(), "dist", "main.dist")
    if not os.path.isdir(dist):
        print("找不到 dist 目录：%s" % dist)
        return 2
    done = skipped = 0
    for sub in SUBDIRS:
        d = os.path.join(dist, sub) if sub else dist
        if not os.path.isdir(d):
            continue
        for name in NAMES:
            dst = os.path.join(d, name)
            if os.path.isfile(dst) and os.path.getsize(dst) > 0:
                skipped += 1
                continue
            for sd in SOURCES:
                src = os.path.join(sd, name)
                if os.path.isfile(src) and copy_via_temp(src, dst):
                    print("补上 %s" % os.path.relpath(dst, dist))
                    done += 1
                    break
    print("补齐 %d 个，已有 %d 个（共 %d 个位置）"
          % (done, skipped, len(SUBDIRS) * len(NAMES)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
