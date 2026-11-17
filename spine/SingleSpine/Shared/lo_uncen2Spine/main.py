# -*- coding: utf-8 -*-
r"""lo_uncen2Spine 启动器 —— 唯一入口（GUI / CLI / Nuitka 打包都用它）。

开发态：

    python main.py                 # 打开 GUI
    python main.py --cli list      # 命令行

打包（Nuitka，用 `env\.venv-build` 那套独立解释器，见 `env\README.md`）：

    build_nuitka.bat               # → dist\main.dist\lo_uncen2Spine.exe

目录约定（`src\` 放代码、`config\` 放设定、`deps\` 放第三方、`docs\` 放文档、
`misc\` 放 Unity 侧脚本与检验结果、`examples\` 放样例产物），见 `README.md`。

打包后要一起带的东西（`build_nuitka.bat` 里已写好）：两个扩展库
（`--include-package=ext_bdone --include-package=ext_lo`，冻结后没有 entry point
的 dist-info，`discover()` 会按包名兜底 import）、`config\lo_uncen2Spine.json`、
`src/tools\{static_check,face_check}.py`、`config\per_char_env.txt`、根标记 `.u2s_root`。
"""
from __future__ import annotations

import os
import sys


def _bootstrap() -> str:
    """把 `src\\` 放到 sys.path 上（打包态不用——模块已经编译进去了）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    if not (getattr(sys, "frozen", False)
            or "__compiled__" in globals()):
        src = os.path.join(here, "src")
        if os.path.isdir(src) and src not in sys.path:
            sys.path.insert(0, src)
    return here


def app_root() -> str:
    """打包后＝exe 目录；开发时＝项目根。"""
    _bootstrap()
    try:
        from unity2spine.paths import app_root as _root
        return _root()
    except Exception:                                            # noqa: BLE001
        return os.path.dirname(os.path.abspath(__file__))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _bootstrap()
    if argv and argv[0] in ("--cli", "cli"):
        from unity2spine.cli import main as cli_main
        return cli_main(argv[1:])
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    from unity2spine.gui.main import main as gui_main
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
