# -*- coding: utf-8 -*-
r"""Probe Spine product bone setup values (local vs world?)."""
import json
import sys
from pathlib import Path


def main(js: Path):
    d = json.loads(Path(js).read_text(encoding="utf-8"))
    for b in d["bones"][:10]:
        print(f"{b['name'][:26]:26s} parent={str(b.get('parent'))[:26]:26s} "
              f"x={b.get('x', 0):9.2f} y={b.get('y', 0):9.2f} "
              f"rot={b.get('rotation', 0):8.2f} sx={b.get('scaleX', 1):.3f}")
    print("slots[0]:", d["slots"][0])
    print("first attachment keys:", list((d["skins"][0]["attachments"] or {}))[:3])


if __name__ == "__main__":
    main(Path(sys.argv[1]))
