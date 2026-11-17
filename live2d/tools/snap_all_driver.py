# -*- coding: utf-8 -*-
r"""Re-snapshot every character in small batches via the Unity MCP CLI.

注意：子进程输出重定向到文件（不用管道），否则在当前沙箱下拿不到 stdout。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "tools" / "unity_snap_nat.cs").read_text(encoding="utf-8-sig")
OUT = ROOT / "tools" / "_snap_driver.cs"
LOG = ROOT / "Products" / "_snap_driver.log"
BATCH = int(sys.argv[1]) if len(sys.argv) > 1 else 3
START = int(sys.argv[2]) if len(sys.argv) > 2 else 0


def names_all():
    return sorted(p.name for p in (ROOT / "Products").iterdir()
                  if p.is_dir() and (p / f"{p.name}.model3.json").exists()
                  and not p.name.startswith("_"))


def main():
    names = names_all()
    total = len(names)
    for i in range(START, total, BATCH):
        sel = names[i:i + BATCH]
        arr = ",".join('"' + n + '"' for n in sel)
        code = BASE.replace('new string[] { "2DModel_3P_Alexandra_N" }',
                            "new string[] { " + arr + " }")
        OUT.write_text(code, encoding="utf-8")
        tag = "?"
        try:
            with LOG.open("w", encoding="utf-8") as fh:
                subprocess.run([sys.executable, str(ROOT / "tools" / "unity_http_mcp.py"),
                                "exec", str(OUT)], stdout=fh, stderr=subprocess.STDOUT,
                               timeout=300)
            txt = LOG.read_text(encoding="utf-8", errors="replace")
            tag = "OK" if (":OK;" in txt or "success" in txt) else "FAIL"
        except Exception as exc:
            tag = f"ERR {type(exc).__name__}"
        print(f"[{i + len(sel)}/{total}] {sel[0][:34]} {tag}", flush=True)


if __name__ == "__main__":
    main()
