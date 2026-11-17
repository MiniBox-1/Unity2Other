# -*- coding: utf-8 -*-
r"""Generate a nat-snapshot script for a slice of characters (with per-name try/catch)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "tools" / "unity_snap_nat.cs").read_text(encoding="utf-8-sig")
names = sorted(p.name for p in (ROOT / "Products").iterdir()
               if p.is_dir() and (p / f"{p.name}.model3.json").exists()
               and not p.name.startswith("_"))
start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
count = int(sys.argv[2]) if len(sys.argv) > 2 else 40
sel = names[start:start + count]
arr = ",".join('"' + n + '"' for n in sel)
src = src.replace('new string[] { "2DModel_3P_Alexandra_N" }', "new string[] { " + arr + " }")
# 每个角色单独 try/catch，单个失败不影响整体
src = src.replace("var go = UnityEngine.Object.Instantiate(prefab);",
                  "UnityEngine.GameObject go = null;\n try { go = UnityEngine.Object.Instantiate(prefab);")
src = src.replace('report.Append(name + ":OK;");',
                  'report.Append(name + ":OK;"); } catch (System.Exception e) { report.Append(name + ":EX;"); }')
out = ROOT / "tools" / "unity_snap_batch.cs"
out.write_text(src, encoding="utf-8")
print("batch", start, start + len(sel), "of", len(names))
