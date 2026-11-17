# -*- coding: utf-8 -*-
r"""Create a render-dump script for one or more characters."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "tools" / "unity_render_dump.cs").read_text(encoding="utf-8-sig")
names = sys.argv[1:] or ["2DModel_3P_Alice_NS1_DL_N"]
arr = ",".join('"' + n + '"' for n in names)
src = src.replace('new string[] { "2DModel_AGS_RheinRitter_NS1" }', "new string[] { " + arr + " }")
out = ROOT / "tools" / "_render_dump_list.cs"
out.write_text(src, encoding="utf-8")
print("wrote", out, len(names))
