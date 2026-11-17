# -*- coding: utf-8 -*-
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "src" / "unity2live2d" / "convert" / "pipeline.py"
s = p.read_text(encoding="utf-8")
start = s.find('    # ---- 实验：同名（去掉尾部 _N）部件只保留 sortingOrder 最高的一个 ----')
end = s.find("    # ---- 跳过 moc3 v1 无法表达的特效件", start)
if start > 0 and end > start:
    s = s[:start] + s[end:]
    p.write_text(s, encoding="utf-8")
    print("removed")
else:
    print("not found")
