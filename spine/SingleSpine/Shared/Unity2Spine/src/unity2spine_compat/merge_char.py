# -*- coding: utf-8 -*-
"""Compat shim: old name ngui2spine.merge_char -> unity2spine.ngui.merge_char."""
import sys
from unity2spine.ngui import merge_char as _m
sys.modules[__name__] = _m

# 让 python -m ngui2spine.<mod> ... 也能跑（runpy 会执行转发脚本本身）
if __name__ == "__main__":
    _main = getattr(_m, "main", None)
    if _main is not None:
        _rc = _main()
        raise SystemExit(_rc if isinstance(_rc, int) else 0)
