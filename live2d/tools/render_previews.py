# -*- coding: utf-8 -*-
r"""Re-render package previews at a given height (higher = smoother edges for IoU)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from preview_moc3 import render_package  # noqa: E402

H = int(sys.argv[1]) if len(sys.argv) > 1 else 1024


def main():
    pkgs = sorted(p for p in (ROOT / "Products").iterdir()
                  if p.is_dir() and (p / f"{p.name}.model3.json").exists()
                  and not p.name.startswith("_"))
    for i, pkg in enumerate(pkgs):
        try:
            render_package(pkg / f"{pkg.name}.model3.json", pkg / "preview.png", H)
        except Exception as exc:
            print("ERR", pkg.name, type(exc).__name__, flush=True)
        if (i + 1) % 20 == 0:
            print(f"[{i + 1}/{len(pkgs)}]", flush=True)
    print("done", len(pkgs))


if __name__ == "__main__":
    main()
