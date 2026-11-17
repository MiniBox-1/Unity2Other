# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "src" / "unity2live2d" / "convert" / "pipeline.py"
s = p.read_text(encoding="utf-8")
marker = "    # ---- 跳过 moc3 v1 无法表达的特效件"
block = '''    # ---- 实验：同名（去掉尾部 _N）部件只保留 sortingOrder 最高的一个 ----
    if os.environ.get("U2L2D_DEDUP_NAME") == "1":
        import re as _re
        groups = {}
        for p in parts:
            key = _re.sub(r"_\\d+$", "", p.name)
            cur = groups.get(key)
            if cur is None or (p.sorting_order, p.order) > (cur.sorting_order, cur.order):
                groups[key] = p
        keep = {id(v) for v in groups.values()}
        before = len(parts)
        parts = [p for p in parts if id(p) in keep]
        print(f"  [dedup-name] {name}: dropped {before - len(parts)}")

'''
if "U2L2D_DEDUP_NAME" not in s and marker in s:
    s = s.replace(marker, block + marker, 1)
    p.write_text(s, encoding="utf-8")
    print("inserted")
else:
    print("skip")
