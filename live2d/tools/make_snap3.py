# -*- coding: utf-8 -*-
r"""Create a nat-snapshot script for a small list of characters."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "tools" / "unity_snap_nat.cs").read_text(encoding="utf-8-sig")
names = sys.argv[1:] or ["2DModel_AGS_Aeda_N"]
arr = ",".join('"' + n + '"' for n in names)
src = src.replace('new string[] { "2DModel_3P_Alexandra_N" }', "new string[] { " + arr + " }")
out = ROOT / "tools" / "_snap_list.cs"
out.write_text(src, encoding="utf-8")
print("wrote", out, len(names), "names")
