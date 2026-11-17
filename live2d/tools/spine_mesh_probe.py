# -*- coding: utf-8 -*-
r"""Probe one Spine mesh attachment: bone indices used and world positions."""
import json
import math
import sys
from pathlib import Path


def main(js: Path, key: str):
    d = json.loads(Path(js).read_text(encoding="utf-8"))
    bones = d["bones"]
    order = [b["name"] for b in bones]
    atts = d["skins"][0]["attachments"]
    att = None
    for slot, items in atts.items():
        if key in items:
            att = items[key]
            break
    if att is None:
        raise SystemExit("attachment not found")
    v = att["vertices"]
    used = set()
    i = 0
    while i < len(v):
        n = int(v[i]); i += 1
        for _ in range(n):
            used.add(int(v[i])); i += 4
    print("vertices bones used:", sorted(used))
    print("names:", [order[b] for b in sorted(used)][:8])


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2])
