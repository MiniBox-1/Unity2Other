# -*- coding: utf-8 -*-
r"""Apply the recorded dual-variant choice (copy B packages over Products)."""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "Products" / "_dual2"
REPORT = ROOT / "Products" / "_dual_report2.json"


def main():
    rep = json.loads(REPORT.read_text(encoding="utf-8"))
    n = 0
    for name, v in rep.items():
        if v.get("best") != "B":
            continue
        src = WORK / "B" / name
        if not (src / f"{name}.model3.json").exists():
            print("skip (no B build):", name)
            continue
        dst = ROOT / "Products" / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        n += 1
    print("applied B for", n, "characters")


if __name__ == "__main__":
    main()
