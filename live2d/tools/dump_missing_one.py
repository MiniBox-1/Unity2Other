# -*- coding: utf-8 -*-
r"""Dump Unity skinbounds one character at a time; report failures."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "Products" / "_unity_ref"


def main():
    names = [p.name for p in (ROOT / "Products").iterdir()
             if p.is_dir() and (p / f"{p.name}.model3.json").exists()]
    have = {p.name.replace(".skinbounds.json", "") for p in REF.glob("*.skinbounds.json")}
    missing = [n for n in sorted(names)
               if n not in have and not n.endswith("_rig") and not n.endswith("_seg")]
    print("missing", len(missing), flush=True)
    ok = 0
    fails = []
    for n in missing:
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "unity_dump_some.py"), n],
                           capture_output=True, text=True, encoding="utf-8")
        if '"isError": false' in (r.stdout or ""):
            ok += 1
        else:
            fails.append(n)
            print("FAIL", n, (r.stdout or "")[:160], flush=True)
    print("ok", ok, "/", len(missing), "fails", len(fails))


if __name__ == "__main__":
    main()
