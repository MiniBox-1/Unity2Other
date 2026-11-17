# -*- coding: utf-8 -*-
r"""Generate a nat-snapshot script covering every packaged character."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "tools" / "unity_snap_nat.cs").read_text(encoding="utf-8-sig")
names = sorted(p.name for p in (ROOT / "Products").iterdir()
               if p.is_dir() and (p / f"{p.name}.model3.json").exists()
               and not p.name.startswith("_"))
arr = ",".join('"' + n + '"' for n in names)
src = src.replace('new string[] { "2DModel_3P_Alexandra_N" }', "new string[] { " + arr + " }")
out = ROOT / "tools" / "unity_snap_all.cs"
out.write_text(src, encoding="utf-8")
print("wrote", out, len(names), "names")
