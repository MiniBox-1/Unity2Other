# -*- coding: utf-8 -*-
"""检查：源码里"字符串常量含制表符"的位置 —— 抓 `\\t` 转义写漏（机械改写的后遗症）。

用法：python src\\tools\\lint_string_escapes.py
退出码：0 = 干净；1 = 有（合法的 TSV 分隔符场景请加到下面的白名单）。
"""
import ast
import io
import os
import sys
TAB = chr(9)
ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
#: 允许含制表符的文件（TSV 解析/写出本来就要 \t）
ALLOW = ("batch_cs_convert.py", "batch_static_check.py", "deabs_paths.py",
         "merge_existing_spine.py", "lint_string_escapes.py")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    n = 0
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in ("env", "deps", "dist", ".cache",
                                            "__pycache__", "examples", "misc")]
        for f in fn:
            if not f.endswith(".py"):
                continue
            if f in ALLOW:
                continue
            p = os.path.join(dp, f)
            src = io.open(p, encoding="utf-8-sig", errors="replace").read()
            try:
                tree = ast.parse(src)
            except SyntaxError as ex:
                print("  语法错误 %s: %s" % (os.path.relpath(p, ROOT), ex))
                n += 1
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant):
                    continue
                v = node.value
                if not isinstance(v, str) or TAB not in v:
                    continue
                i = v.find(TAB)
                print("  %s:%d  …%s…"
                      % (os.path.relpath(p, ROOT), node.lineno,
                         v[max(0, i - 24):i + 20].replace(TAB, "<TAB>")))
                n += 1
    print("共 %d 处" % n)
    return 1 if n else 0


if __name__ == "__main__":
    raise SystemExit(main())
