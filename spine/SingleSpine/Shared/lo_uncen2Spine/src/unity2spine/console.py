# -*- coding: utf-8 -*-
"""控制台输出修正（Windows 中文环境的老坑）。

* 控制台是 GBK 时，打印 `⇒`、`Δ`、`\ufffd` 这类字符会直接
  `UnicodeEncodeError: 'gbk' codec can't encode character ...` 把脚本打断；
* 控制台代码页是 65001（Windows Terminal 常见）时，我们按 UTF-8 写才对得上；
* 起子进程时统一喂 `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1`，读回来按 UTF-8 解
  （见 `subproc_env()`）。

用法：脚本开头 `from unity2spine.console import fix_console; fix_console()`。
"""
from __future__ import annotations

import os
import sys


def console_encoding() -> str:
    """控制台输出编码：跟着控制台代码页走（Windows；65001 = UTF-8）。"""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        cp = ctypes.windll.kernel32.GetConsoleOutputCP()
    except Exception:                                            # noqa: BLE001
        cp = 0
    return {65001: "utf-8"}.get(cp, ("cp%d" % cp) if cp else "")


def fix_console() -> None:
    """编码跟随控制台代码页，且**永不因编不出的字符抛错**。"""
    enc = console_encoding()
    for fh in (sys.stdout, sys.stderr):
        try:
            fh.reconfigure(encoding=enc or None, errors="replace")
        except (AttributeError, ValueError, LookupError):
            pass


def subproc_env(extra=None):
    """给子进程的环境：UTF-8 输出（我们这边也按 UTF-8 解）。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env
