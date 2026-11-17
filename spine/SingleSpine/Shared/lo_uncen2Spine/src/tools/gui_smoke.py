# -*- coding: utf-8 -*-
r"""GUI 冒烟测试：离屏建窗 + 走一遍与 GUI 完全相同的 `Worker` 路径。

用最小的角色跑一次真转换，确认"选线路 → 填参数 → 后台线程 → 产物"这条链没断。

用法：
    set QT_QPA_PLATFORM=offscreen
    python src/tools\gui_smoke.py                 # 用配置里 lo 的第一个 prefab
    python src/tools\gui_smoke.py <prefab> [输出目录]
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.abspath(__file__))  # <根>/src
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication                        # noqa: E402

from unity2spine.api import discover                              # noqa: E402
from unity2spine.gui.main import (MainWindow, Worker, list_prefabs,  # noqa: E402
                                  parse_env)
from unity2spine.paths import app_root, cfg                       # noqa: E402


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication([])                                        # noqa: F841
    profiles = discover()
    win = MainWindow(profiles)
    print("线路: %s | 窗口: %s"
          % ([p.name for p in profiles], win.windowTitle()))
    print("环境变量解析自检:", parse_env("# c\nU2S_LAYER_PHASE=0.499\n\nBAD"))
    prefab_dir = os.path.join(cfg("lo.assets_dir"), "Prefabs")
    if argv:
        target = argv[0]
    else:
        names = [f for f in sorted(os.listdir(prefab_dir))
                 if f.endswith(".uAnim.prefab")]
        if not names:
            print("配置的 Assets 里没找到 prefab；请显式传一个 prefab 路径")
            return 2
        target = os.path.join(prefab_dir, names[0])
    out_dir = argv[1] if len(argv) > 1 else os.path.join(app_root(), "examples",
                                                         "gui_run")
    print("输入: %s\n输出: %s" % (target, out_dir))
    lines = []
    worker = Worker(next(p for p in profiles if p.name == "lo"),
                    list_prefabs(target), out_dir, cfg("lo.assets_dir"),
                    {"cs": True, "json": False}, {})
    worker.line.connect(lambda s: lines.append(str(s)))
    worker.done.connect(lambda ok, d: print("Worker done:", ok, d))
    worker.run()                       # 同步跑（不开线程，便于退出）
    print("日志末尾:")
    for s in lines[-4:]:
        print("   ", s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
