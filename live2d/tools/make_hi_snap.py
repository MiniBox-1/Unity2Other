# -*- coding: utf-8 -*-
r"""Create a high-resolution snapshot variant for one character."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "tools" / "unity_snap_many.cs").read_text(encoding="utf-8-sig")
name = sys.argv[1] if len(sys.argv) > 1 else "2DModel_AGS_Aeda_N"
src = src.replace('new string[] { "2DModel_3P_Alexandra_N" }', 'new string[] { "' + name + '" }')
src = src.replace("int H = 768;", "int H = 1536;")
src = src.replace("_unity_ref", "_unity_ref_hi")
out = ROOT / "tools" / "unity_snap_hi.cs"
out.write_text(src, encoding="utf-8")
print("wrote", out)
