# -*- coding: utf-8 -*-
r"""Dump Unity skinbounds for characters that don't have one yet."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "Products" / "_unity_ref"


def main(batch=15):
    have = {p.name.replace(".skinbounds.json", "") for p in REF.glob("*.skinbounds.json")}
    names = [p.name for p in (ROOT / "Products").iterdir()
             if p.is_dir() and (p / f"{p.name}.model3.json").exists()]
    missing = [n for n in sorted(names)
               if n not in have and not n.endswith("_rig") and not n.endswith("_seg")]
    print("missing", len(missing))
    ok = 0
    for i in range(0, len(missing), batch):
        chunk = missing[i:i + batch]
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "unity_dump_some.py")] + chunk,
                           capture_output=True, text=True, encoding="utf-8")
        good = '"isError": false' in (r.stdout or "")
        print(f"batch {i // batch + 1}: {len(chunk)} -> {'ok' if good else 'FAIL'}", flush=True)
        if good:
            ok += len(chunk)
    print("dumped", ok)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 15)
