# -*- coding: utf-8 -*-
r"""Scan .dll files for a type name."""
import sys
from pathlib import Path

import dnfile


def main(root: Path, needle: str, limit=40):
    hits = 0
    for dll in root.rglob("*.dll"):
        if "Assembly-CSharp" not in dll.name and dll.name != "Assembly-CSharp.dll":
            continue
        try:
            pe = dnfile.dnPE(str(dll))
        except Exception:
            continue
        try:
            names = [str(t.TypeName) for t in pe.net.mdtables.TypeDef if t.TypeName]
        except Exception:
            continue
        if needle in names:
            print("FOUND", dll, len(names), "types")
            hits += 1
            if hits >= limit:
                return
    print("scanned, hits:", hits)


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "ActorPartsView")
