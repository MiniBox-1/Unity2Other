# -*- coding: utf-8 -*-
"""命令行版本：python run_cli.py <prefab路径> [输出目录] [采样间隔]"""

import os
import sys

import os as _os
import sys as _sys
_SRC = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "src")
if _SRC not in _sys.path:
    _sys.path.insert(0, _SRC)

from unity2spine.ngui.convert_chr import convert_character
from unity2spine.validate.validate_spine import validate_tree


def main():
    if len(sys.argv) < 2:
        print("用法: python run_cli.py <prefab路径> [输出目录] [sample_dt]")
        return 2
    prefab = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "output"
    dt = float(sys.argv[3]) if len(sys.argv) > 3 else 0.05
    assets = None
    for root in (r"D:\VB\Search\BdOne\Assets", os.path.dirname(os.path.abspath(__file__))):
        if os.path.isdir(os.path.join(root, "prefab")):
            assets = root
            break
    if assets is None:
        assets = input("请输入 Unity Assets 目录: ").strip()
    convert_character(prefab, assets, out, sample_dt=dt)
    ok, fails = validate_tree(out)
    print("校验：通过 %d / 失败 %d" % (ok, len(fails)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
