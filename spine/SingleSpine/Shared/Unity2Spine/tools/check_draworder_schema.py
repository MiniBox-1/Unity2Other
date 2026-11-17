# -*- coding: utf-8 -*-
"""契约检查：Unity 侧 `ExportDrawOrder.cs` 写出的 JSON 键，够不够 `read_draworder.py` 用？

两边是手写 JSON（C# 手拼、Python 手读），改一边忘了另一边就会**静默**读到空值。
这个脚本把两边用到的键名抽出来对一遍，并顺手检查几个必须存在的顶层键。

用法：python tools\\check_draworder_schema.py
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CS = r"D:\VB\Search\NormalLocal\lastOrign\Assets\Editor\ExportDrawOrder.cs"
PY = os.path.join(HERE, "tools", "read_draworder.py")

# 必须出现的顶层键（read_draworder + 下游消费者）
TOP_REQUIRED = ["character", "state", "t", "rendererCount", "renderers",
                "tieGroups", "pairs", "drawOrderFirstToLast", "camera", "explain"]
# 每条渲染器必须有的键
RENDERER_REQUIRED = ["path", "node", "type", "enumIndex", "dfsIndex",
                     "sortingLayerID", "sortingOrder", "camDepth", "sortKey",
                     "tieGroup", "tieRank", "boundsCenter", "boundsSize",
                     "enabled", "activeInHierarchy"]


def keys_written_by_cs(src):
    """C# 里 `Append("  \"key\": ")` / `Append(", \"key\": ")` 形式的键名。"""
    out = set()
    for m in re.finditer(r'Append\(\s*"[^"]*\\"([A-Za-z_][A-Za-z0-9_]*)\\"', src):
        out.add(m.group(1))
    for m in re.finditer(r'Append\(\s*"[,\s]*([A-Za-z_][A-Za-z0-9_]*)\\":\s*', src):
        out.add(m.group(1))
    return out


def keys_read_by_py(src):
    out = set()
    for m in re.finditer(r'\["([A-Za-z_][A-Za-z0-9_]*)"\]', src):
        out.add(m.group(1))
    for m in re.finditer(r'\.get\("([A-Za-z_][A-Za-z0-9_]*)"', src):
        out.add(m.group(1))
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cs = io.open(CS, encoding="utf-8").read()
    py = io.open(PY, encoding="utf-8").read()
    written = keys_written_by_cs(cs)
    want = keys_read_by_py(py)
    print("C# 写出的键 %d 个" % len(written))
    print("read_draworder 要读的键 %d 个" % len(want))
    missing = sorted(want - written)
    print("reader 要但 C# 没写：%s" % (missing if missing else "无 ✅"))
    miss_top = [k for k in TOP_REQUIRED if k not in written]
    miss_rend = [k for k in RENDERER_REQUIRED if k not in written]
    print("顶层必需键缺：%s" % (miss_top if miss_top else "无 ✅"))
    print("渲染器必需键缺：%s" % (miss_rend if miss_rend else "无 ✅"))
    ok = not missing and not miss_top and not miss_rend
    print("结论：" + ("契约一致 ✅" if ok else "**不一致，改完再跑** ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
